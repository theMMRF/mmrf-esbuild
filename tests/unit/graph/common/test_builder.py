from collections.abc import Collection
from typing import Any
from unittest import mock

import more_itertools
import psqlgraph
import pytest
import requests
from indexclient import client

from esbuild.graph.common import builder


class DummyIndexBuilder(builder.GraphIndexBuilder):
    def __init__(
        self,
        psqlgraph_driver: psqlgraph.PsqlGraphDriver,
        indexd_client: client.IndexClient,
        index_prefix: str = "",
        case_to_file_paths=(),
        file_labels=frozenset(()),
        cases: Collection[psqlgraph.Node] = (),
        projects: Collection[psqlgraph.Node] = (),
        annotations: Collection[psqlgraph.Node] = (),
        **kwargs: Any,
    ) -> None:
        self.file_labels = file_labels

        super().__init__(
            psqlgraph_driver, indexd_client, index_prefix, case_to_file_paths, **kwargs
        )

        self.cases = cases
        self.projects = projects
        self.annotations = annotations

    def _cache_all(self) -> None:
        return


def test__denormalize_annotations__no_annotations() -> None:
    graph = mock.MagicMock()
    annotations = ()
    index_builder = DummyIndexBuilder(graph, mock.MagicMock(), "", annotations=annotations)

    _, _, result, _ = index_builder.denormalize_all()

    assert result == []


def make_http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://indexd.example/index/dg.MMRF/test-object"
    return requests.HTTPError(f"HTTP {status_code}", response=response)


def test__get_indexd_record__retries_transient_http_error() -> None:
    indexd = mock.MagicMock()
    record = mock.Mock()
    indexd.get.side_effect = [make_http_error(502), record]
    index_builder = DummyIndexBuilder(mock.MagicMock(), indexd)

    with mock.patch.object(builder.time, "sleep") as sleep:
        result = index_builder._get_indexd_record("test-object")

    assert result is record
    assert indexd.get.call_args_list == [mock.call("test-object"), mock.call("test-object")]
    sleep.assert_called_once_with(builder.INDEXD_RETRY_BACKOFF_SECONDS)


def test__get_indexd_record__raises_non_retryable_http_error() -> None:
    indexd = mock.MagicMock()
    error = make_http_error(400)
    indexd.get.side_effect = error
    index_builder = DummyIndexBuilder(mock.MagicMock(), indexd)

    with (
        mock.patch.object(builder.time, "sleep") as sleep,
        pytest.raises(requests.HTTPError) as raised,
    ):
        index_builder._get_indexd_record("test-object")

    assert raised.value is error
    indexd.get.assert_called_once_with("test-object")
    sleep.assert_not_called()


def test__get_indexd_record__raises_after_retry_limit() -> None:
    indexd = mock.MagicMock()
    error = make_http_error(502)
    indexd.get.side_effect = error
    index_builder = DummyIndexBuilder(mock.MagicMock(), indexd)

    with (
        mock.patch.object(builder.time, "sleep") as sleep,
        pytest.raises(requests.HTTPError) as raised,
    ):
        index_builder._get_indexd_record("test-object")

    assert raised.value is error
    assert indexd.get.call_count == builder.INDEXD_REQUEST_MAX_ATTEMPTS
    assert sleep.call_args_list == [
        mock.call(builder.INDEXD_RETRY_BACKOFF_SECONDS * 2**attempt)
        for attempt in range(builder.INDEXD_REQUEST_MAX_ATTEMPTS - 1)
    ]


def test__remove_unavailable_files__matches_only_placeholder_suffix() -> None:
    index_builder = DummyIndexBuilder(mock.MagicMock(), mock.MagicMock())
    available = mock.Mock(file_name="MMRF_1462_4_BM_CD138pos_T2_TSMRU.txt")
    unavailable = mock.Mock(
        file_name="MMRF_1462_4_BM_CD138pos_T2_TSMRU.this_file_is_unavailable.txt"
    )
    suffix_not_at_end = mock.Mock(file_name="sample.this_file_is_unavailable.txt.checksum")
    missing_file_name = mock.Mock(spec=[])

    result = index_builder._remove_unavailable_files(
        {available, unavailable, suffix_not_at_end, missing_file_name}
    )

    assert result == {available, suffix_not_at_end, missing_file_name}


def test__get_case_files__excludes_unavailable_placeholders() -> None:
    index_builder = DummyIndexBuilder(mock.MagicMock(), mock.MagicMock())
    case = mock.Mock()
    available = mock.Mock(file_name="results.txt")
    unavailable = mock.Mock(file_name="input.this_file_is_unavailable.txt")
    index_builder._walk_paths = mock.Mock(return_value={available, unavailable})
    index_builder._add_file_metadata_from_indexd = mock.Mock(side_effect=lambda file_: file_)
    index_builder._remove_bam_index_files = mock.Mock(side_effect=set)
    index_builder._remove_hidden_nodes = mock.Mock(side_effect=set)

    result = index_builder._get_case_files(case)

    assert result == {available}


def test__denormalize_project__excludes_unavailable_files_from_summary() -> None:
    index_builder = DummyIndexBuilder(mock.MagicMock(), mock.MagicMock())
    project = mock.Mock()
    program = mock.Mock()
    case = mock.MagicMock()
    case.__getitem__.side_effect = {
        "disease_type": "Multiple Myeloma",
        "primary_site": "Bone Marrow",
    }.__getitem__
    available = mock.MagicMock(file_name="results.txt")
    available.__getitem__.side_effect = {"file_size": 100}.__getitem__
    unavailable = mock.MagicMock(file_name="input.this_file_is_unavailable.txt")
    unavailable.__getitem__.side_effect = {"file_size": 25}.__getitem__

    def get_neighbors(node, label):
        if node is project and label == "program":
            return iter((program,))
        if node is project and label == "case":
            return iter((case,))
        raise AssertionError(f"Unexpected neighbor lookup: {node}, {label}")

    index_builder._get_base_doc = mock.Mock(
        side_effect=lambda node: (
            {"project_id": "MMRF-PROJECT"} if node is project else {"name": "MMRF"}
        )
    )
    index_builder._neighbors_labeled = mock.Mock(side_effect=get_neighbors)
    index_builder._walk_paths = mock.Mock(return_value={available, unavailable})
    index_builder._remove_bam_index_files = mock.Mock(side_effect=set)
    index_builder._patch_project = mock.Mock()
    index_builder.experimental_strategies = {"RNA-Seq": {available, unavailable}}
    index_builder.data_categories = {"Transcriptome Profiling": {available, unavailable}}

    with mock.patch.object(builder.validators, "is_node_hidden", return_value=False):
        result = index_builder._denormalize_project(project)

    assert result["summary"] == {
        "case_count": 1,
        "file_count": 1,
        "file_size": 100,
        "experimental_strategies": [
            {
                "case_count": 1,
                "experimental_strategy": "RNA-Seq",
                "file_count": 1,
            }
        ],
        "data_categories": [
            {
                "case_count": 1,
                "data_category": "Transcriptome Profiling",
                "file_count": 1,
            }
        ],
    }


def test__denormalize_annotations__annotated_case_node() -> None:
    case = mock.MagicMock(node_id="c-0", label="case", submitter_id="s-c-0")
    annotation = mock.MagicMock(
        label="annotation",
        node_id="a-0",
        edges_out=(mock.MagicMock(dst=case),),
        _dictionary={"category": "non-analysis"},
        _props={},
    )
    annotation_edge = mock.MagicMock(label="annotates", src=annotation, dst=case)
    graph = mock.MagicMock()
    graph.edges.return_value = graph
    graph.filter.return_value = (annotation_edge,)
    index_builder = DummyIndexBuilder(graph, mock.MagicMock(), "", annotations=(annotation,))

    _, _, result, _ = index_builder.denormalize_all()

    assert len(result) == 1

    result_doc = more_itertools.one(result)
    key_diff = result_doc.keys() ^ frozenset(
        {
            "entity_id",
            "entity_type",
            "entity_submitter_id",
            "case_id",
            "case_submitter_id",
            "annotation_id",
            "project",
        }
    )

    assert not key_diff
    assert result_doc["entity_id"] == "c-0"
    assert result_doc["entity_type"] == "case"
    assert result_doc["entity_submitter_id"] == "s-c-0"
    assert result_doc["case_id"] == "c-0"
    assert result_doc["case_submitter_id"] == "s-c-0"
    assert result_doc["annotation_id"] == "a-0"
    assert result_doc["project"] is None


def test__denormalize_annotations__annotated_workflow_with_linked_case() -> None:
    case = mock.MagicMock(node_id="c-0", label="case", submitter_id="s-c-0")
    workflow = mock.MagicMock(
        node_id="w-0",
        label="workflow",
        submitter_id="s-w-0",
        edges_out=(mock.MagicMock(dst=case),),
    )
    annotation = mock.MagicMock(
        label="annotation",
        node_id="a-0",
        edges_out=(mock.MagicMock(dst=workflow),),
        _dictionary={"category": "non-analysis"},
        _props={},
    )
    annotation_edge = mock.MagicMock(label="annotates", src=annotation, dst=workflow)
    graph = mock.MagicMock()
    graph.edges.return_value = graph
    graph.filter.return_value = (annotation_edge,)
    index_builder = DummyIndexBuilder(graph, mock.MagicMock(), "", annotations=(annotation,))

    _, _, result, _ = index_builder.denormalize_all()
    result_doc = more_itertools.one(result)
    key_diff = result_doc.keys() ^ frozenset(
        {
            "entity_id",
            "entity_type",
            "entity_submitter_id",
            "case_id",
            "case_submitter_id",
            "annotation_id",
            "project",
        }
    )

    assert not key_diff
    assert result_doc["entity_id"] == "w-0"
    assert result_doc["entity_type"] == "workflow"
    assert result_doc["entity_submitter_id"] == "s-w-0"
    assert result_doc["case_id"] == "c-0"
    assert result_doc["case_submitter_id"] == "s-c-0"
    assert result_doc["annotation_id"] == "a-0"
    assert result_doc["project"] is None


def test__denormalize_annotations__annotated_workflow_without_linked_case() -> None:
    workflow = mock.MagicMock(
        node_id="w-0",
        label="workflow",
        submitter_id="s-w-0",
        edges_out=(),
    )
    annotation = mock.MagicMock(
        label="annotation",
        node_id="a-0",
        edges_out=(mock.MagicMock(dst=workflow),),
        _dictionary={"category": "non-analysis"},
        _props={},
    )
    annotation_edge = mock.MagicMock(label="annotates", src=annotation, dst=workflow)
    graph = mock.MagicMock()
    graph.edges.return_value = graph
    graph.filter.return_value = (annotation_edge,)
    index_builder = DummyIndexBuilder(graph, mock.MagicMock(), "", annotations=(annotation,))

    _, _, result, _ = index_builder.denormalize_all()
    result_doc = more_itertools.one(result)
    key_diff = result_doc.keys() ^ frozenset(
        {
            "entity_id",
            "entity_type",
            "entity_submitter_id",
            "case_id",
            "case_submitter_id",
            "annotation_id",
            "project",
        }
    )

    assert not key_diff
    assert result_doc["entity_id"] == "w-0"
    assert result_doc["entity_type"] == "workflow"
    assert result_doc["entity_submitter_id"] == "s-w-0"
    assert result_doc["case_id"] is None
    assert result_doc["case_submitter_id"] is None
    assert result_doc["annotation_id"] == "a-0"
    assert result_doc["project"] is None
