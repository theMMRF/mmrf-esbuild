import unittest
from esbuild.project_file_visibility import (
    indexd_read_auth,
    prepare_build,
    merge_ownership_mapping,
    annotate,
    manifest_records,
    prepare_sources,
    ownership_mapping,
    AUTHZ,
    VERSION,
    SUMMARY,
)

A = "/programs/MMRF/projects/public"
B = "/programs/MMRF/projects/methylation"
MANIFEST = [{"did": "rna", "authz": [A]}, {"did": "meth", "authz": [B]}]
FILES = [
    {
        "file_id": "rna",
        "file_name": "rna.txt",
        "file_size": 9,
        "data_category": "RNA",
        "cases": [{"case_id": "c1", "project": {"project_id": "MMRF-public"}}],
    },
    {
        "file_id": "meth",
        "file_name": "methylation.txt",
        "file_size": 100,
        "data_category": "methylation",
        "cases": [{"case_id": "c1", "project": {"project_id": "MMRF-public"}}],
    },
]


class ProjectVisibilityTests(unittest.TestCase):
    def test_opt_in_requires_trusted_indexd_credentials(self):
        self.assertEqual(indexd_read_auth(False, None, None), (None, None))
        self.assertEqual(
            indexd_read_auth(True, "service", "test-password"),
            ("service", "test-password"),
        )
        for username, password in ((None, None), ("service", ""), ("", "password")):
            with self.assertRaises(ValueError):
                indexd_read_auth(True, username, password)

    def test_shared_case_is_not_hidden_as_a_whole(self):
        case = {
            "case_id": "c1",
            "diagnosis": "myeloma",
            "files": FILES,
            "summary": {"file_count": 2, "file_size": 109},
        }
        prepared = prepare_sources([case], MANIFEST, FILES)[0]
        self.assertNotIn(AUTHZ, prepared)
        self.assertEqual(prepared[VERSION], 1)
        self.assertEqual([file[AUTHZ] for file in prepared["files"]], [[A], [B]])
        self.assertEqual(sum(row["file_count"] for row in prepared[SUMMARY]), 2)
        self.assertEqual(sum(row["file_size"] for row in prepared[SUMMARY]), 109)
        self.assertNotIn("visibility", prepared)

    def test_ownership_is_preserved_when_case_project_is_different(self):
        prepared = prepare_sources(FILES, MANIFEST, FILES)
        self.assertEqual(prepared[1][AUTHZ], [B])
        self.assertEqual(
            prepared[1]["cases"][0]["project"]["project_id"], "MMRF-public"
        )

    def test_embedded_case_summaries_are_reconstructed(self):
        file = {**FILES[0], "cases": [{"case_id": "c1", "summary": {"file_count": 2}}]}
        prepared = prepare_sources([file], MANIFEST, FILES)[0]
        self.assertEqual(len(prepared["cases"][0][SUMMARY]), 2)
        self.assertEqual(prepared[AUTHZ], [A])

    def test_builder_uses_object_id_ownership_for_graph_file_id(self):
        cases, files, _, _ = prepare_build(
            [
                {
                    "case_id": "c1",
                    "files": [
                        {
                            "file_id": "graph",
                            "object_id": "indexd",
                            "file_name": "secret.txt",
                        }
                    ],
                    "summary": {"file_count": 1},
                }
            ],
            [
                {
                    "file_id": "graph",
                    "object_id": "indexd",
                    "file_name": "secret.txt",
                    "cases": [{"case_id": "c1"}],
                }
            ],
            [],
            [],
            {"graph": {"did": "indexd", "authz": [B]}},
        )
        self.assertNotIn(AUTHZ, cases[0])
        self.assertEqual(files[0][AUTHZ], [B])

    def test_fresh_mapping_preserves_types_and_removes_parent_copies(self):
        mapping = {
            "properties": {
                "files": {
                    "type": "object",
                    "properties": {
                        "file_name": {"type": "keyword", "copy_to": "all_text"}
                    },
                }
            }
        }
        prepared = prepare_sources([{"case_id": "c1", "files": FILES}], MANIFEST, FILES)
        result = merge_ownership_mapping(mapping, prepared)
        self.assertEqual(result["properties"]["files"]["type"], "nested")
        self.assertEqual(
            result["properties"]["files"]["properties"]["file_name"],
            {"type": "keyword"},
        )
        self.assertEqual(mapping["properties"]["files"]["type"], "object")

    def test_unknown_mutation_source_file_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare_sources([{"src_file_id": "missing"}], {"records": []}, [])

    def test_null_cases_and_project_are_optional_without_losing_ownership(self):
        file = dict(FILES[0], cases=None)
        prepared = prepare_sources([file], MANIFEST, [file])[0]
        self.assertEqual(prepared[AUTHZ], [A])
        file["cases"] = [{"case_id": "c1", "project": None}]
        prepared = prepare_sources(
            [{"case_id": "c1", "summary": {"file_count": 1}}], MANIFEST, [file]
        )[0]
        self.assertEqual(prepared[SUMMARY][0]["file_count"], 1)

    def test_missing_manifest_ownership_fails(self):
        for manifest in ([{"did": "rna", "authz": []}], [{"did": "rna", "authz": [A]}]):
            with self.assertRaises(ValueError):
                prepare_sources(FILES, manifest, FILES)

    def test_incomplete_file_export_fails_instead_of_trusting_global_counts(self):
        with self.assertRaises(ValueError):
            prepare_sources(
                [{"case_id": "c1", "summary": {"file_count": 2}}], MANIFEST, FILES[:1]
            )

    def test_related_private_inputs_require_all_scopes(self):
        file = {**FILES[0], "analysis": {"input_files": [FILES[1]]}}
        self.assertEqual(annotate(file, manifest_records(MANIFEST))[AUTHZ], [B, A])

    def test_bare_guid_arrays_are_not_unprotected(self):
        self.assertEqual(
            annotate(
                {"case_id": "c1", "file_guids": ["meth"]}, manifest_records(MANIFEST)
            )[AUTHZ],
            [B],
        )

    def test_project_existence_uses_the_project_scope(self):
        project = {
            "project_id": "MMRF-methylation",
            "code": "methylation",
            "program": {"name": "MMRF"},
        }
        self.assertEqual(annotate(project, manifest_records(MANIFEST))[AUTHZ], [B])

    def test_unknown_file_summaries_are_removed(self):
        prepared = prepare_sources(
            [{"gene_id": "g1", "summary": {"file_count": 2, "clinical_count": 5}}],
            MANIFEST,
            FILES,
        )[0]
        self.assertEqual(prepared["summary"], {"clinical_count": 5})

    def test_mapping_only_adds_policy_fields_and_required_containers(self):
        prepared = prepare_sources(
            [
                {
                    "case_id": "c1",
                    "files": FILES,
                    "labels": ["clinical"],
                    "summary": {"file_count": 2},
                }
            ],
            MANIFEST,
            FILES,
        )
        properties = ownership_mapping(prepared)["properties"]
        self.assertEqual(properties["files"]["type"], "nested")
        self.assertEqual(properties["files"]["properties"][AUTHZ], {"type": "keyword"})
        self.assertNotIn("labels", properties)
        self.assertFalse(properties[SUMMARY]["enabled"])


class BuilderIntegrationTests(unittest.TestCase):
    """Exercise real builder entry points while replacing graph/ES dependencies."""

    @staticmethod
    def builder_class():
        import importlib.util
        from pathlib import Path
        import sys
        import types
        from unittest.mock import MagicMock, patch
        from esbuild import project_file_visibility

        source = Path(__file__).resolve().parents[1] / "src/esbuild"
        package = types.ModuleType("esbuild")
        package.__path__ = [str(source)]
        graph = types.ModuleType("esbuild.graph")
        graph.__path__ = []
        common = types.ModuleType("esbuild.graph.common")
        common.__path__ = []
        builder = types.ModuleType("esbuild.graph.common.builder")
        builder.GraphIndexBuilder = type("GraphIndexBuilder", (), {})
        mappings = types.ModuleType("esbuild.graph.common.mappings")
        for kind in ("case", "file", "annotation", "project"):
            setattr(mappings, "get_" + kind + "_mapping", lambda: {"properties": {}})
        mappings.get_settings = lambda: {}
        utils = types.ModuleType("esbuild.utils")
        utils.get_all_gencode_versions = lambda _: []
        utils.get_index_names = lambda prefix, kinds: {
            kind: prefix + "-" + kind for kind in kinds
        }
        utils.ReleaseHelper = MagicMock()
        es = types.ModuleType("elasticsearch")
        es.Elasticsearch = type("Elasticsearch", (), {})
        es.helpers = MagicMock()
        pg = types.ModuleType("psqlgraph")
        pg.PsqlGraphDriver = type("PsqlGraphDriver", (), {})
        index = types.ModuleType("indexclient")
        index.client = types.ModuleType("indexclient.client")
        index.client.IndexClient = type("IndexClient", (), {})
        modules = {
            "esbuild": package,
            "esbuild.graph": graph,
            "esbuild.graph.common": common,
            "esbuild.graph.common.builder": builder,
            "esbuild.graph.common.mappings": mappings,
            "esbuild.project_file_visibility": project_file_visibility,
            "esbuild.utils": utils,
            "elasticsearch": es,
            "psqlgraph": pg,
            "indexclient": index,
            "datadog": types.ModuleType("datadog"),
        }
        spec = importlib.util.spec_from_file_location(
            "esbuild.gdc_elasticsearch", source / "gdc_elasticsearch.py"
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(module)
        return module.GDCElasticsearch

    def test_opt_out_keeps_original_projection_and_opt_in_prepares_it(self):
        import tempfile
        from unittest.mock import MagicMock, patch

        klass = self.builder_class()
        case = {"case_id": "c1", "files": FILES, "summary": {"file_count": 2}}
        converter = MagicMock()
        converter.denormalize_all.return_value = ([case], FILES, [], [])
        converter.file_metadata = {row["did"]: row for row in MANIFEST}
        with tempfile.TemporaryDirectory() as directory:
            for flag in ("false", "true"):
                with patch.dict("os.environ", {"PROJECT_VISIBILITY_ENABLED": flag}):
                    build = klass(
                        MagicMock(),
                        MagicMock(),
                        es=MagicMock(),
                        pg_driver=MagicMock(),
                        index_prefix="new",
                        save_doc_path=directory,
                    )
                cases, files, _, _ = build._cache_database(converter)
                if flag == "false":
                    self.assertIs(cases[0], case)
                    self.assertNotIn(AUTHZ, files[0])
                else:
                    self.assertNotIn(AUTHZ, cases[0])
                    self.assertEqual(files[1][AUTHZ], [B])
                    self.assertEqual(cases[0][VERSION], 1)

    def test_existing_destinations_fail_before_cleanup_or_deploy(self):
        import tempfile
        from unittest.mock import MagicMock, patch

        klass = self.builder_class()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"PROJECT_VISIBILITY_ENABLED": "true"}),
        ):
            build = klass(
                MagicMock(),
                MagicMock(),
                es=MagicMock(),
                pg_driver=MagicMock(),
                index_prefix="existing",
                save_doc_path=directory,
            )
            build._cache_versioned_files = lambda: {}
            build._cache_database = MagicMock(return_value=([], [], [], []))
            build.log_skipped_nodes = MagicMock()
            build._prepare_indices = MagicMock()
            build.deploy = MagicMock()
            build.es.indices.exists.return_value = True
            with self.assertRaisesRegex(ValueError, "fresh index"):
                build.go(roll_alias=False, send_events=False)
            build._cache_database.assert_not_called()
            build._prepare_indices.assert_not_called()
            build.deploy.assert_not_called()

    def test_late_destination_conflict_never_cleans_or_reuses_another_build(self):
        import tempfile
        from unittest.mock import MagicMock, patch

        klass = self.builder_class()
        with tempfile.TemporaryDirectory() as directory:
            for flag in ("false", "true"):
                with (
                    self.subTest(flag=flag),
                    patch.dict("os.environ", {"PROJECT_VISIBILITY_ENABLED": flag}),
                ):
                    instance = klass(
                        MagicMock(),
                        MagicMock(),
                        es=MagicMock(),
                        pg_driver=MagicMock(),
                        index_prefix="race",
                        save_doc_path=directory,
                    )
                    instance.es.indices.exists.return_value = True
                    instance.release_helper = MagicMock()
                    instance._prepare_indices()
                    if flag == "true":
                        instance.release_helper.delete_docs_from_index.assert_not_called()
                        instance.es.indices.create.side_effect = RuntimeError(
                            "already exists"
                        )
                        with self.assertRaisesRegex(RuntimeError, "already exists"):
                            instance._create_index("race_case", {}, {})
                        instance.es.indices.create.assert_called_once()
                        instance.es.indices.refresh.assert_not_called()
                    else:
                        instance.release_helper.delete_docs_from_index.assert_called()
                        instance._create_index("race_case", {}, {})
                        instance.es.indices.create.assert_not_called()


class SingleRunnerTests(unittest.TestCase):
    def test_normal_runner_uses_complete_build_only_when_opted_in(self):
        import ast
        import __future__
        import os
        from pathlib import Path
        import types
        from unittest.mock import MagicMock, patch

        filename = Path(__file__).resolve().parents[1] / "src/esbuild/bin/single.py"
        tree = ast.parse(filename.read_text())
        fn = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "get_gdc_elasticsearch"
        )
        constructor = MagicMock()
        namespace = {
            "os": os,
            "gdc_elasticsearch": types.SimpleNamespace(GDCElasticsearch=constructor),
            "builder": types.SimpleNamespace(ActiveGraphIndexBuilder=object),
        }
        exec(
            compile(
                ast.Module(body=[fn], type_ignores=[]),
                str(filename),
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            namespace,
        )
        for flag in ("false", "true"):
            with (
                self.subTest(flag=flag),
                patch.dict(os.environ, {"PROJECT_VISIBILITY_ENABLED": flag}),
            ):
                namespace["get_gdc_elasticsearch"](
                    object(), object(), object(), types.SimpleNamespace(index="fresh")
                )
                kwargs = constructor.call_args.kwargs
                if flag == "true":
                    self.assertIsNone(kwargs["build_projects"])
                else:
                    self.assertIn("MMRF-COMMPASS-IA24", kwargs["build_projects"])
                self.assertFalse(kwargs["cache_versioned"])
                self.assertEqual(kwargs["index_prefix"], "fresh")


if __name__ == "__main__":
    unittest.main()
