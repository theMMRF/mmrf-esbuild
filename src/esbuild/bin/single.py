import argparse
import logging
import time
from datetime import timedelta

import elasticsearch
import psqlgraph
from indexclient import client

from esbuild import gdc_elasticsearch, utils
from esbuild.graph.active import builder

"""ENVIRONMENT VARS REQUIRED:
# Postgres connection
PG_USER
PG_HOST
PG_PASS
PG_NAME

# Elasticsearch
ES_HOST
ES_PORT
ES_USE_SSL (true/false)
ES_VERIFY_CERTS (true/false)
ES_USER
ES_PASSWORD
CA_CERT_PATH
ES_REQUEST_TIMEOUT

#Indexd
INDEXD_HOST

"""

# class DebugFilter(logging.Filter):
#     def filter(self, record):
#         print(f"{record.pathname=}")
#         print(f"{record.module=}")
#         print(f"{record.funcName=}")
#         return True

# logging.getLogger().addFilter(DebugFilter())


class SuppressPackageFilter(logging.Filter):
    def filter(self, record):
        return not record.pathname.endswith("indexclient/client.py")


logging.getLogger().addFilter(SuppressPackageFilter())

logger = logging.getLogger(__name__)
parser = argparse.ArgumentParser()

parser.add_argument(
    "index", type=str, help="The prefix of the indices to build; e.g. dr45_active_v3"
)


def get_gdc_elasticsearch(
    indexd_client: client.IndexClient,
    pg_driver: psqlgraph.PsqlGraphDriver,
    es_client: elasticsearch.Elasticsearch,
    args: argparse.Namespace,
) -> gdc_elasticsearch.GDCElasticsearch:
    """Parse and validate payload and return GDCElasticsearch instance.

    Args:
        indexd_client: Indexd Client
        pg_driver: psql graph driver
        es_client: elasticsearch client
        args: Parsed command-line arguments
        save_doc_path: Where to save docs (if necessary)
        skip_es: Skips writing to es

    Returns:
        GDCElasticsearch

    Raises:
        ValueError when build type is not active
    """
    # TODO: This will need to be what ever your project code is.
    build_projects = [
        "MMRF-COMMPASS-IA24",
        "MMRF-IA11",
        "MMRF-IA12",
        "MMRF-IA13",
        "MMRF-IA14",
        "MMRF-IA15",
        "MMRF-IA16",
        "MMRF-IA17",
        "MMRF-IA18",
        "MMRF-IA19",
        "MMRF-IA20",
        "MMRF-IA21",
        "MMRF-IA22",
    ]
    alias = "graph"

    gdc_es = gdc_elasticsearch.GDCElasticsearch(
        converter_class=builder.ActiveGraphIndexBuilder,
        indexd_client=indexd_client,
        pg_driver=pg_driver,
        es=es_client,
        index_prefix=args.index,
        build_projects=build_projects,
        build_awg=False,
        index_alias_prefix=alias,
        selective_caching=True,
        cache_versioned=False,
        save_doc_path=None,
        skip_es=False,
        gencode_version="v36",
    )

    return gdc_es


def main() -> None:
    try:
        start_time = time.monotonic()
        pg_driver = utils.get_default_pg_driver()
        indexd_client = utils.get_default_index_client()
        es_client = elasticsearch.Elasticsearch(**utils.ES_CONFIG)
        args = parser.parse_args()

        gdc_es = get_gdc_elasticsearch(
            indexd_client,
            pg_driver,
            es_client,
            args,
        )

        gdc_es.go(
            roll_alias=False,
            send_events=False,
        )
        end_time = time.monotonic()
        print("Runtime: ", timedelta(seconds=end_time - start_time))
    except Exception:
        logger.critical("Minion failed.", exc_info=True)
        raise


if __name__ == "__main__":
    main()
