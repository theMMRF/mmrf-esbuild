import logging
import os
import subprocess
import time
from collections.abc import Iterable
from datetime import datetime
from functools import lru_cache
from hashlib import md5
from pathlib import Path
from reprlib import repr
from typing import ClassVar

import psqlgraph
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from gdc_ng_models.models.submission import TransactionSnapshot
from gdcdatamodel2 import models
from gdcmodels import esutils
from indexclient.client import IndexClient
from psqlgraph import PsqlGraphDriver
from queueclient import DepotQueueClient, RabbitMQClient
from requests import HTTPError

from esbuild.graph.common import builder
from esbuild.graph.common.builder import GraphIndexBuilder

logger = logging.getLogger(__name__)


def get_file_state(doc):
    state = None
    for url, meta in doc.urls_metadata.items():
        if meta.get("type") == GraphIndexBuilder.INDEXD_URL_TYPE:
            state = state or meta.get("state")
    return state


INDEXD_METADATA_FIELDS = [*GraphIndexBuilder.data_file_indexd_fields, "file_id"]
INDEXD_METADATA_VALUE_GETTERS = {
    "file_id": lambda doc: doc.did,
    "md5sum": lambda doc: doc.hashes["md5"],
    "file_size": lambda doc: doc.size,
    "file_state": get_file_state,
}

load_dotenv()

ES_CONFIG = {
    "hosts": [os.getenv("ES_HOST", "localhost")],
    "port": os.getenv("ES_PORT", 9200),
    "use_ssl": os.getenv("ES_USE_SSL", "False").lower() == "true",
    "verify_certs": os.getenv("ES_VERIFY_CERTS", "False").lower() == "true",
    "http_auth": (os.getenv("ES_USER", ""), os.getenv("ES_PASSWORD", "")),
    "ca_certs": os.getenv("CA_CERT_PATH", ""),
    "timeout": os.getenv("ES_REQUEST_TIMEOUT", 9999),
}


def get_default_pg_driver():
    return PsqlGraphDriver(
        user=os.getenv("PG_USER"),
        host=os.getenv("PG_HOST"),
        password=os.getenv("PG_PASS"),
        database=os.getenv("PG_NAME"),
    )


def get_default_index_client():
    return IndexClient(
        baseurl=os.getenv("INDEXD_HOST"),
        auth=(None, None),  # Safe guard from potential updates
    )


def get_queue_client(queue_type, queue_id=None):
    if queue_type == "depot":
        return DepotQueueClient(
            host=os.getenv("DEPOT_HOST", "depot.service.consul"),
            port=os.getenv("DEPOT_PORT"),
            queue_id=queue_id or os.getenv("DEPOT_QUEUE_ID", "esbuild"),
        )
    elif queue_type == "rabbitmq":
        return RabbitMQClient(
            host=os.getenv("RABBITMQ_HOST", "rabbitmq.service.consul"),
            port=int(os.getenv("RABBITMQ_PORT", 5672)),
            queue_id=queue_id or os.getenv("RABBITMQ_QUEUE_ID", "esbuild"),
            username=os.getenv("RABBITMQ_USER", "guest"),
            password=os.getenv("RABBITMQ_PASS", "guest"),
            durable=True,
        )

    raise ValueError(f"Unsupported queue type: '{queue_type}'")


def get_elasticsearch_client():
    return Elasticsearch(**ES_CONFIG)


# TODO: Refactor esbuild.graph.common.builder to use this method to extract IndexD properties
def extract_indexd_metadata(doc, fields=None, getters=None):
    if fields is None:
        fields = INDEXD_METADATA_FIELDS
    if getters is None:
        getters = INDEXD_METADATA_VALUE_GETTERS

    metadata = {}
    for field in fields:
        if hasattr(doc, field):
            metadata[field] = getattr(doc, field)
        else:
            getter = getters[field]
            metadata[field] = getter(doc)
    return metadata


class VersionedNodesDiffCollector:
    """collects differences between corresponding new and old version.

    pre-processing step to identify files that haven't been yet released,
    but have old versions. Look up metadata nodes in the same TransactionLog that
    the version action happened
    """

    TARGET_NODE_STATES: ClassVar[list[str]] = ["validated", "submitted"]

    def __init__(
        self,
        allowed_gencode_versions: frozenset[str],
        project_ids=None,
        graph=None,
        indexd_client=None,
    ):
        if isinstance(project_ids, str):
            self.project_ids = project_ids.split(",")
        else:
            self.project_ids = project_ids

        self.g = graph or get_default_pg_driver()
        self.i = indexd_client or get_default_index_client()
        self.allowed_gencode_versions = allowed_gencode_versions
        self.diffs = {}

    def query_nodes(self):
        with self.g.session_scope():
            q = (
                self.g.nodes()
                .prop_in("state", self.TARGET_NODE_STATES)
                .filter(models.Node._props.has_key("file_name"))
            )

            if self.project_ids and isinstance(self.project_ids, list):
                q = q.prop_in("project_id", self.project_ids)

            nodes = q.yield_per(1000).enable_eagerloads(False)
            yield from nodes

    def iter_nodes(self, strategy="query"):
        if strategy == "query":
            return self.query_nodes()
        else:
            raise NotImplementedError(f"Node loading strategy '{strategy}' is not implemented")

    def get_props_from_snapshot(self, node_id, action):
        with self.g.session_scope():
            ts = (
                self.g.nodes(TransactionSnapshot)
                .filter(
                    TransactionSnapshot.id == node_id,
                    TransactionSnapshot.action == action,
                )
                .order_by(TransactionSnapshot.transaction_id.desc())
                .first()
            )

            if not ts:
                return {}

            old = ts.old_props
            new = ts.new_props

            diff = {}
            for key, value in old.items():
                if new.get(key) != value:
                    diff[key] = value
            return diff

    def get_props_from_indexd(self, versions, latest_id):
        # get only unreleased files
        unreleased_all = [
            v for v in versions if not (v.version and v.metadata.get("release_number"))
        ]

        if len(unreleased_all) > 1:
            if len([v for v in unreleased_all if v.did == latest_id]) < 1:
                raise ValueError("No unreleased document found")

            extra = [v for v in unreleased_all if v.did != latest_id]

            for e in extra:
                logger.debug(f"Extra unreleased IndexD doc: '{e.did}'")

        # Get latest released
        released = sorted(
            (v for v in versions if v.version and v.metadata.get("release_number")),
            key=lambda x: int(x.version),
        )[-1]

        gencode_of_latest_released = getattr(released, "metadata", {}).get("gencode_version")

        # Get primary url ('type' should be 'cleversafe')
        primary_urls = {
            url: meta
            for url, meta in released.urls_metadata.items()
            if meta.get("type") == "cleversafe"
        }

        if len(primary_urls) > 1:
            raise ValueError("Multiple primary urls for doc")

        _, meta = primary_urls.popitem()

        old_props = {
            "file_state": meta["state"],
            "gencode_version": gencode_of_latest_released,
        }

        indexd_meta = extract_indexd_metadata(released)

        old_props.update(indexd_meta)

        return old_props

    def list_versions(self, node):
        for _ in range(5):
            try:
                versions = self.i.list_versions(node.node_id)
            except HTTPError as e:
                if e.response and e.response.status_code != 404:
                    logger.error(f"Error while making request to IndexD: {e!s}. Retrying")
                    time.sleep(5)
                    continue
                # Return an empty list if record doesn't exist
                return []
            return versions

        logger.debug(f"IndexD is being weird with: {node.project_id} '{node}'")
        # Return an empty list if unable to query IndexD
        return []

    def get_old_props(self, node: psqlgraph.Node) -> dict:
        """Given a Node, collect old properties from TransactionSnapshot and IndexD."""
        # Lookup TransactionSnapshot with 'version' action
        transaction_props = self.get_props_from_snapshot(node.node_id, "version")

        # This will mean that the given node never created a new file version
        if not transaction_props:
            return {}

        versions = self.list_versions(node)
        if len(versions) <= 1:
            # Latest version isn't released or IndexD didn't return anything,
            # so no older version to look for
            return {}

        # Lookup differences in IndexD
        indexd_props = self.get_props_from_indexd(versions, node.node_id)
        gencode_from_indexd = indexd_props.pop("gencode_version")

        is_node_submittable = node._dictionary.get("submittable", False)
        if is_node_submittable or gencode_from_indexd in self.allowed_gencode_versions:
            # Prioritize IndexD metadata over Graph metadata
            transaction_props.update(indexd_props)
            return transaction_props
        else:  # harmonized file with wrong or none gencode_version
            logger.debug(
                f"Found old version of {node.node_id}, omitting it due to"
                f"undesired gencode_version: {gencode_from_indexd}"
            )
            return {}

    def collect_differences(self):
        for node in self.iter_nodes():
            node_diff = self.get_old_props(node)
            if node_diff:
                self.diffs[node.node_id] = node_diff
                logger.debug(f"Found old version of: {node.project_id} '{node}'")
        return self.diffs


class ReleaseHelper:
    """Prepares previously stored index to be used in a next data release.

    Attributes:
        es: Elatcisearch client instance
        audit_index: destination index where to write audit events
        audit: create audit documents or not
    """

    def __init__(self, es: Elasticsearch, audit_index: str, audit: bool = True):
        """Initialize release helper.

        Usage:
            - initialize the helper
            - run .prepare_index_to_build()
        """
        self.es = es
        self.audit_index = audit_index
        self.audit = audit

    @classmethod
    def get_project_docs_query(
        cls, index_type: str, project_ids: Iterable[str] | None = None
    ) -> dict:
        """Create a query for documents of a given index_type and project_ids.

        Create a query that will return all documents from a given ``index_type``
        for a given subset of ``project_ids``. If no ``project_ids`` were passed,
        return all documents from the index

        Args:
            index_type: graph index type. must be one of ("annotation", "case",
                "file", "project")
            project_ids: optional list of project_ids
        """
        if not project_ids:
            return {"match_all": {}}

        project_ids = tuple(project_ids)
        project_q: dict = {"terms": {"project_id": project_ids}}
        case_or_annotation_q: dict = {"terms": {"project.project_id": project_ids}}
        file_q: dict = {
            "nested": {
                "path": "cases",
                "query": {"terms": {"cases.project.project_id": project_ids}},
            }
        }

        index_type_queries = {
            "annotation": case_or_annotation_q,
            "case": case_or_annotation_q,
            "file": file_q,
            "project": project_q,
        }

        if index_type not in index_type_queries:
            raise ValueError(f"Invalid index_type: '{index_type}'")

        return index_type_queries[index_type]

    def delete_docs_from_index(
        self, index_name: str, index_type: str, projects_to_delete: Iterable[str]
    ):
        """Remove ebsuild docs associated with selected projects from the index.

        Args:
            index_name: ES index to remove docs from
            index_type: query to use when removing docs from index
            projects_to_delete: list of project_ids
        """
        existing_indices = self.es.indices.get_alias()

        q = self.get_project_docs_query(index_type, projects_to_delete)

        if index_name not in existing_indices:
            return

        try:
            self.es.delete_by_query(index=index_name, body={"query": q})
        except Exception:
            logger.exception(
                "Unable to delete documents for projects: [{}] from: '{}'".format(
                    ", ".join(projects_to_delete), index_name
                )
            )

    def add_esbuild_log(self, index_prefix, action, project_ids, timestamp=None, **kwargs):
        if not self.audit:
            return

        # If audit index doesn't exist, create one
        if not self.es.indices.exists(index=self.audit_index):
            self.es.indices.create(index=self.audit_index)
            self.es.indices.refresh(index=self.audit_index)

        if timestamp is None:
            timestamp = datetime.now()

        commit_hash = kwargs.get("commit_hash", self.get_commit_hash())

        project_ids = project_ids or ["all"]

        metadata_id = self.get_build_metadata_id(
            index_prefix, action, project_ids, commit_hash
        )

        self.es.index(
            index=self.audit_index,
            document=dict(
                input_hash=metadata_id,
                index_prefix=index_prefix,
                action=action,
                projects=project_ids or ["all"],
                commit_hash=commit_hash,
                timestamp=timestamp,
                **kwargs,
            ),
        )

    @classmethod
    def get_build_metadata_id(cls, index_prefix, action, project_ids, commit_hash):
        if not isinstance(project_ids, list):
            project_ids = [str(project_ids)]

        project_ids_string = ",".join(sorted(project_ids))
        id_string = "-".join([index_prefix, action, project_ids_string, commit_hash])

        md5hash = md5(id_string.encode("utf-8"), usedforsecurity=False)

        return md5hash.hexdigest()

    def get_project_ids(self, index_prefix):
        """Return set of projects based on project documents in index."""
        query = {"query": {"match_all": {}}, "stored_fields": "_id"}

        project_index = index_prefix + "_project"

        res = self.es.search(index=project_index, size=10000, **query)

        hits = res["hits"]["hits"]
        if hits:
            projects = {project["_id"] for project in hits}
        else:
            # Existing index did not contain any project docs
            projects = set()
        return projects

    def wait_for_es(self, index_name, query=None, max_wait_sec=30):
        """Wait for query to return non empty result."""
        if query is None:
            query = {"match_all": {}}

        time_slept = 0
        while not self.es.search(index=index_name, body=query)["hits"]["hits"]:
            time.sleep(1)
            time_slept += 1
            if time_slept > max_wait_sec:
                break

    @staticmethod
    @lru_cache(1)
    def get_commit_hash():
        commit_hash = os.getenv("GIT_COMMIT_HASH")
        if commit_hash:
            return commit_hash

        repository_root = Path(__file__).resolve().parents[2]
        try:
            commit_hash = (
                subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository_root)
                .decode("utf-8")
                .strip()
            )
        except Exception as err:
            commit_hash = f"unable to parse commit hash: {repr(err)}"

        return commit_hash


def get_index_names(
    index_prefix: str,
    index_types: Iterable[str],
) -> dict[str, str]:
    """Return elasticsearch index names given an index_prefix.

    Since Elasticsearch7 does not support more than 1 doc_type per index, the
    index names will be in a format: <index_prefix>_<index_type>
    """
    return {index_type: f"{index_prefix}_{index_type}" for index_type in index_types}


def force_merge_indices(es, index_prefix=None, index_names=()) -> None:
    """Force-merging the graph indices down to a single segment.

    Args:
        es: Elasticsearch client
        index_prefix: index name prefix
        index_names: index names

    Returns:
        None

    Raises:
        Value Error for wrong input arguments.
    """
    if not index_prefix and not index_names:
        raise ValueError("index_prefix or index_name must be provided")

    if index_prefix and index_names:
        raise ValueError("index_prefix and index_name cannot be set at the same time")

    if index_prefix:
        index_mappings = get_index_names(
            index_prefix, ["file", "case", "project", "annotation"]
        )
        index_names = list(index_mappings.values())

    esutils.force_merge_elasticsearch_indices(es, index_names)


def get_all_gencode_versions(gencode_version: str) -> frozenset[str]:
    """Map specified gencode version to all allowed gencode versions."""
    gencode_versions = (
        builder.AVAILABLE_GENCODE_VERSIONS
        if gencode_version == "all"
        else frozenset(["neutral", gencode_version])
    )

    if not gencode_versions.issubset(builder.AVAILABLE_GENCODE_VERSIONS):
        raise NotImplementedError(
            f"{gencode_versions} is not a valid gencode_version requirement. "
            f"The available gencode_versions are {builder.AVAILABLE_GENCODE_VERSIONS}"
        )

    return gencode_versions
