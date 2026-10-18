import unittest
from copy import deepcopy
from esbuild.graph_file_summaries import reconcile_graph_file_summaries
from esbuild.visibility_inputs import prepare_inputs, select_manifest, configuration
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


class VisibilityExportTests(unittest.TestCase):
    def sources(self, extra_manifest=(), extra_case=None):
        case = {"case_id": "c1", "files": FILES, "summary": {"file_count": 2}}
        case.update(extra_case or {})
        manifest = MANIFEST + list(extra_manifest)
        return {
            "case": prepare_sources([case], manifest, FILES),
            "file": prepare_sources(FILES, manifest, FILES),
            "project": [],
            "annotation": [],
        }

    def test_unreferenced_unowned_records_do_not_block_a_complete_projection(self):
        manifest = prepare_inputs(
            self.sources(), MANIFEST + [{"did": "old-unused", "authz": []}]
        )
        self.assertEqual({row["did"] for row in manifest["records"]}, {"rna", "meth"})

    def test_referenced_unowned_record_is_identified_and_never_made_public(self):
        rows = [MANIFEST[0], {"did": "meth", "authz": None}]
        with self.assertRaisesRegex(ValueError, "Referenced IndexD GUID 'meth'.*authz"):
            prepare_inputs(self.sources(), rows)

    def test_missing_required_record_still_fails(self):
        with self.assertRaisesRegex(ValueError, "missing from IndexD.*meth"):
            prepare_inputs(self.sources(), MANIFEST[:1])

    def test_references_in_nonstandard_fields_and_case_responses_are_in_scope(self):
        extra = [{"did": "external", "authz": [B]}]
        sources = self.sources(extra, {"related_guids": ["external"]})
        manifest = prepare_inputs(sources, MANIFEST + extra)
        self.assertIn("external", {row["did"] for row in manifest["records"]})
        with self.assertRaisesRegex(ValueError, "Referenced IndexD GUID 'external'"):
            prepare_inputs(sources, MANIFEST + [{"did": "external", "authz": []}])

    def test_prefixed_guid_alias_selects_its_authoritative_record(self):
        guid = "12345678-1234-1234-1234-123456789abc"
        rows = [
            {"did": "dg.test/" + guid, "authz": [B]},
            {"did": "unused", "authz": []},
        ]
        manifest = select_manifest(rows, {guid}, {guid})
        self.assertEqual(manifest["records"], rows[:1])

    def test_same_counts_with_wrong_memberships_still_fail(self):
        sources = self.sources()
        sources["file"][1]["file_id"] = "different"
        with self.assertRaisesRegex(ValueError, "membership mismatch.*c1"):
            prepare_inputs(sources, MANIFEST)

    def test_ownership_drift_requires_rebuild(self):
        with self.assertRaisesRegex(ValueError, "Stored ownership differs"):
            prepare_inputs(self.sources(), [MANIFEST[0], {"did": "meth", "authz": [A]}])

    def test_override_uses_rebuilt_driver_and_private_credential_quoting(self):
        import tomllib
        from pathlib import Path

        stage, repo = Path("/stage"), Path("/repo")
        password = 'special \\ " $ !\n'
        config = tomllib.loads(
            configuration("vis-test", stage, repo, "service", password)
        )
        self.assertEqual(config["indexd"]["password"], password)
        self.assertEqual(config["build"]["pex_file"], "/repo/driver-all")
        self.assertEqual(config["build"]["driver"], "/repo/bin/driver.py")
        self.assertEqual(len(config["elasticsearch"]["write"]["indices"]), 8)

    def test_project_case_coverage_is_required_even_when_file_counts_match(self):
        project = {
            "project_id": "MMRF-public",
            "code": "public",
            "program": {"name": "MMRF"},
            "summary": {"case_count": 1, "file_count": 2},
        }
        sources = self.sources(extra_case={"project": {"project_id": "MMRF-public"}})
        sources["project"] = prepare_sources([project], MANIFEST, FILES)
        self.assertEqual(len(prepare_inputs(sources, MANIFEST)["records"]), 2)
        sources["project"][0]["summary"]["case_count"] = 2
        with self.assertRaisesRegex(ValueError, "Incomplete case coverage"):
            prepare_inputs(sources, MANIFEST)

    def test_export_publication_is_private_and_does_not_overwrite_existing_inputs(self):
        import os
        from pathlib import Path
        import stat
        import sys
        import tempfile
        import types
        from unittest.mock import MagicMock, patch
        from esbuild import visibility_inputs

        sources = self.sources()
        es = MagicMock()
        client = MagicMock()
        documents = [
            types.SimpleNamespace(did=row["did"], to_json=lambda row=row: row)
            for row in MANIFEST
        ]
        documents.append(
            types.SimpleNamespace(did="unused", to_json=lambda: {"authz": []})
        )
        client.list.return_value = documents
        modules = {
            "elasticsearch": types.SimpleNamespace(
                Elasticsearch=lambda **kwargs: es,
                helpers=types.SimpleNamespace(
                    scan=lambda es, index, query: (
                        {"_source": row} for row in sources[index.rsplit("_", 1)[1]]
                    )
                ),
            ),
            "esbuild.utils": types.SimpleNamespace(
                ES_CONFIG={}, get_default_index_client=lambda: client
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, repo = root / "stage", root / "repo"
            stage.mkdir()
            for name in (
                "driver-all",
                "bin/driver.py",
                "run/conf/config.toml",
                "run/conf/config-viz.toml",
            ):
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            argv = [
                "export",
                "vis-test",
                "--stage",
                str(stage),
                "--mutation-repo",
                str(repo),
                "--indexd-base-url",
                "https://example.test/index",
            ]
            with (
                patch.dict(
                    os.environ,
                    {
                        "PROJECT_VISIBILITY_ENABLED": "true",
                        "INDEXD_USERNAME": "service",
                        "INDEXD_PASSWORD": "test-only",
                    },
                ),
                patch.dict(sys.modules, modules),
                patch.object(sys, "argv", argv),
            ):
                visibility_inputs.main()
                saved = (stage / "indexd-manifest.json").read_bytes()
                for name in (
                    "indexd-manifest.json",
                    "files.ndjson",
                    "config-visibility.toml",
                ):
                    self.assertEqual(stat.S_IMODE((stage / name).stat().st_mode), 0o600)
                with self.assertRaisesRegex(SystemExit, "refusing to overwrite"):
                    visibility_inputs.main()
                self.assertEqual(saved, (stage / "indexd-manifest.json").read_bytes())
                es.indices.create.assert_not_called()
                es.indices.delete.assert_not_called()


class GraphSummaryTests(unittest.TestCase):
    def fixture(self):
        import ast
        import __future__
        from pathlib import Path

        # Use the actual legacy merge routine: two graph nodes become one GUID
        # document, but the original case/project summaries counted both nodes.
        source = (
            Path(__file__).resolve().parents[1] / "src/esbuild/graph/common/builder.py"
        )
        tree = ast.parse(source.read_text())
        cls = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "GraphIndexBuilder"
        )
        method = next(
            node
            for node in cls.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_upsert_file_into_dict"
        )
        namespace = {}
        exec(
            compile(
                ast.Module(body=[method], type_ignores=[]),
                str(source),
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            namespace,
        )
        files = deepcopy(FILES)
        for file in files:
            file["object_id"] = file["file_id"]
        duplicate = deepcopy(files[1])
        files[1]["file_id"] = "graph-meth-1"
        duplicate["file_id"] = "graph-meth-2"
        embedded = [files[0], files[1], duplicate]
        case = {
            "case_id": "c1",
            "project": {"project_id": "MMRF-public"},
            "files": deepcopy(embedded),
            "summary": {"file_count": 3, "file_size": 209},
        }
        project = {
            "project_id": "MMRF-public",
            "summary": {"case_count": 1, "file_count": 3, "file_size": 209},
        }
        merged = {}
        for file in embedded:
            namespace["_upsert_file_into_dict"](None, merged, file)
        return [case], list(merged.values()), [], [project]

    def test_real_graph_merge_reconciles_counts_without_hiding_missing_files(self):
        cases, files, annotations, projects = self.fixture()
        self.assertEqual(len(files), 2)
        cached = {row["did"]: row for row in MANIFEST}
        cached.update({"graph-meth-1": MANIFEST[1], "graph-meth-2": MANIFEST[1]})
        with self.assertRaisesRegex(ValueError, "file total"):
            prepare_build(cases, files, annotations, projects, cached)
        reconcile_graph_file_summaries(cases, files, annotations, projects)
        cases, files, _, projects = prepare_build(
            cases, files, annotations, projects, cached
        )
        self.assertEqual(cases[0]["summary"]["file_count"], 2)
        self.assertEqual(cases[0]["summary"]["file_size"], 109)
        self.assertEqual(
            projects[0]["summary"], {"case_count": 1, "file_count": 2, "file_size": 109}
        )
        self.assertNotIn(AUTHZ, cases[0])
        self.assertEqual(cases[0]["files"][1][AUTHZ], [B])
        self.assertEqual(sum(row["file_count"] for row in cases[0][SUMMARY]), 2)

    def test_missing_file_export_is_rejected_with_case_and_guid(self):
        cases, files, annotations, projects = self.fixture()
        with self.assertRaisesRegex(ValueError, "case 'c1'.*missing=.*meth"):
            reconcile_graph_file_summaries(cases, files[:1], annotations, projects)
        self.assertEqual(cases[0]["summary"]["file_count"], 3)

    def test_equal_counts_do_not_hide_wrong_file_membership(self):
        cases, files, annotations, projects = self.fixture()
        files[1]["object_id"] = files[1]["file_id"] = "unexpected"
        with self.assertRaisesRegex(ValueError, "case 'c1'.*unexpected"):
            reconcile_graph_file_summaries(cases, files, annotations, projects)

    def test_missing_embedded_graph_record_still_fails(self):
        cases, files, annotations, projects = self.fixture()
        cases[0]["files"].pop()
        with self.assertRaisesRegex(ValueError, "case 'c1'.*legacy file_count"):
            reconcile_graph_file_summaries(cases, files, annotations, projects)

    def test_incomplete_project_case_export_still_fails(self):
        cases, files, annotations, projects = self.fixture()
        projects[0]["summary"]["case_count"] = 2
        with self.assertRaisesRegex(
            ValueError, "project 'MMRF-public'.*expected 2 cases"
        ):
            reconcile_graph_file_summaries(cases, files, annotations, projects)

    def test_wrong_file_project_association_is_rejected(self):
        cases, files, annotations, projects = self.fixture()
        files[1]["cases"][0]["project"]["project_id"] = "MMRF-other"
        with self.assertRaisesRegex(
            ValueError, "project 'MMRF-public'.*missing=.*meth"
        ):
            reconcile_graph_file_summaries(cases, files, annotations, projects)

    def test_nested_summaries_use_the_verified_complete_case_scope(self):
        cases, files, annotations, projects = self.fixture()
        files[0]["cases"][0]["summary"] = {"file_count": 3, "file_size": 209}
        reconcile_graph_file_summaries(cases, files, annotations, projects)
        self.assertEqual(
            files[0]["cases"][0]["summary"], {"file_count": 2, "file_size": 109}
        )


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

    def test_selected_project_snapshot_keeps_scope_and_prepares_cross_project_files(
        self,
    ):
        import tempfile
        from unittest.mock import MagicMock, patch

        klass = self.builder_class()
        case = {"case_id": "c1", "files": FILES, "summary": {"file_count": 2}}
        converter = MagicMock()
        converter.denormalize_all.return_value = ([case], FILES, [], [])
        converter.file_metadata = {row["did"]: row for row in MANIFEST}
        factory = MagicMock(return_value=converter)
        converter.skipped_nodes = {}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"PROJECT_VISIBILITY_ENABLED": "true"}),
        ):
            build = klass(
                factory,
                MagicMock(),
                es=MagicMock(),
                pg_driver=MagicMock(),
                index_prefix="fresh",
                build_projects=["MMRF-public"],
                selective_caching=True,
                save_doc_path=directory,
            )
            build.es.indices.exists.return_value = False
            build.deploy = MagicMock()
            build.go(roll_alias=False, send_events=False)
            self.assertEqual(
                factory.call_args.kwargs["build_projects"], ["MMRF-public"]
            )
            self.assertTrue(factory.call_args.kwargs["selective_caching"])
            cases, files, _, _ = build.deploy.call_args.args
            self.assertNotIn(AUTHZ, cases[0])
            self.assertEqual([file[AUTHZ] for file in files], [[A], [B]])
            self.assertEqual(cases[0][SUMMARY][1]["file_count"], 1)
            self.assertEqual(cases[0][VERSION], 1)
            build.release_helper.delete_docs_from_index.assert_not_called()
            with self.assertRaisesRegex(ValueError, "unversioned snapshot"):
                klass(factory, MagicMock(), cache_versioned=True)

    def test_upload_boundary_reconciles_real_graph_merge_before_ownership(self):
        import tempfile
        from unittest.mock import MagicMock, patch

        klass = self.builder_class()
        raw = GraphSummaryTests().fixture()
        converter = MagicMock()
        converter.denormalize_all.return_value = raw
        converter.file_metadata = {row["did"]: row for row in MANIFEST}
        converter.file_metadata.update(
            {"graph-meth-1": MANIFEST[1], "graph-meth-2": MANIFEST[1]}
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"PROJECT_VISIBILITY_ENABLED": "true"}),
        ):
            build = klass(
                MagicMock(),
                MagicMock(),
                pg_driver=MagicMock(),
                es=MagicMock(),
                save_doc_path=directory,
            )
            cases, files, _, projects = build._cache_database(converter)
            self.assertEqual(cases[0]["summary"]["file_count"], 2)
            self.assertEqual(projects[0]["summary"]["file_count"], 2)
            self.assertEqual(files[1][AUTHZ], [B])
            build.es.indices.create.assert_not_called()

    def test_upload_boundary_still_rejects_missing_file_before_index_creation(self):
        import tempfile
        from unittest.mock import MagicMock, patch

        klass = self.builder_class()
        converter = MagicMock()
        converter.denormalize_all.return_value = (
            [{"case_id": "c1", "files": FILES, "summary": {"file_count": 2}}],
            FILES[:1],
            [],
            [],
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"PROJECT_VISIBILITY_ENABLED": "true"}),
        ):
            build = klass(
                MagicMock(),
                MagicMock(),
                pg_driver=MagicMock(),
                es=MagicMock(),
                save_doc_path=directory,
            )
            with self.assertRaisesRegex(ValueError, "case 'c1'.*missing=.*meth"):
                build._cache_database(converter)
            build.es.indices.create.assert_not_called()
            build.release_helper.delete_docs_from_index.assert_not_called()

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
    def test_normal_runner_preserves_served_project_scope_when_opted_in(self):
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
                self.assertEqual(
                    kwargs["build_projects"],
                    ["MMRF-COMMPASS-IA24"]
                    + [f"MMRF-IA{release}" for release in range(11, 23)],
                )
                self.assertTrue(kwargs["selective_caching"])
                self.assertFalse(kwargs["cache_versioned"])
                self.assertEqual(kwargs["index_prefix"], "fresh")


if __name__ == "__main__":
    unittest.main()
