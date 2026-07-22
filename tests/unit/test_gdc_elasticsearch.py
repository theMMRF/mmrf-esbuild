from unittest import mock

import pytest

from esbuild import gdc_elasticsearch


def test_go_preserves_deploy_error_when_fallback_save_fails() -> None:
    deployment_error = RuntimeError("deployment failed")
    gdc_es = gdc_elasticsearch.GDCElasticsearch.__new__(gdc_elasticsearch.GDCElasticsearch)
    gdc_es.index_prefix = "test-index"
    gdc_es.index_aliases = {}
    gdc_es.build_projects = []
    gdc_es.build_awg = False
    gdc_es.selective_caching = False
    gdc_es.versioned_files = {}
    gdc_es.allowed_gencode_versions = frozenset()
    gdc_es.graph = mock.Mock()
    gdc_es.indexd_client = mock.Mock()
    gdc_es.converter_class = mock.Mock(return_value=mock.Mock(skipped_nodes={}))
    gdc_es.es = mock.Mock()
    gdc_es.skip_es = False
    gdc_es.doc_output_dir = "/unwritable"
    gdc_es.event_logger = mock.Mock()
    gdc_es._cache_versioned_files = mock.Mock(return_value={})
    gdc_es._cache_database = mock.Mock(return_value=([], [], [], []))
    gdc_es.log_skipped_nodes = mock.Mock()
    gdc_es._prepare_indices = mock.Mock()
    gdc_es.deploy = mock.Mock(side_effect=deployment_error)
    gdc_es.save_docs = mock.Mock(side_effect=OSError("save failed"))

    with pytest.raises(RuntimeError) as raised:
        gdc_es.go(roll_alias=False, send_events=False)

    assert raised.value is deployment_error
    gdc_es.save_docs.assert_called_once_with([], [], [], [])
