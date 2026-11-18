"""Export private mutation inputs for the complete selected search projection."""

import argparse
import json
import os
from pathlib import Path
import tempfile
import uuid

from esbuild.project_file_visibility import (
    AUTHZ,
    GUID_FIELDS,
    VERSION,
    iter_prepare_sources,
    manifest_records,
    resources,
)

KINDS = ("file", "case", "project", "annotation")
VIZ = (
    "case_centric",
    "cnv_centric",
    "cnv_occurrence_centric",
    "gene_centric",
    "segment_cnv_centric",
    "segment_cnv_occurrence_centric",
    "ssm_centric",
    "ssm_occurrence_centric",
)


def references(value, strings, required):
    if isinstance(value, str):
        strings.add(value)
    elif isinstance(value, list):
        for item in value:
            references(item, strings, required)
    elif isinstance(value, dict):
        for name, item in value.items():
            if name.startswith("_gen3_file_") or name.startswith("_gen3_visibility"):
                continue
            if name in GUID_FIELDS and isinstance(item, str):
                required.add(item)
            references(item, strings, required)


def select_manifest(rows, strings, required, progress=None):
    """Ignore only unreferenced records; never invent ownership for a dependency."""
    selected = []
    scanned = 0
    referenced = strings | required
    for row in rows:
        scanned += 1
        did = row.get("did")
        aliases = {did} if isinstance(did, str) and did else set()
        if aliases:
            try:
                aliases.add(str(uuid.UUID(did.rsplit("/", 1)[-1])))
            except ValueError:
                pass
        if aliases.intersection(referenced):
            try:
                policy = resources(row.get("authz"))
            except ValueError as exc:
                raise ValueError(
                    f"Referenced IndexD GUID {did!r} has missing/noncanonical authz; "
                    "repair its authoritative ownership before exporting"
                ) from exc
            selected.append({"did": did, "authz": policy})
        if progress and scanned % 10000 == 0:
            progress(scanned, len(selected))
    manifest = {"records": selected}
    policies = manifest_records(manifest)
    missing = required - policies.keys()
    if missing:
        raise ValueError(
            f"Referenced GUIDs missing from IndexD: {sorted(missing)[:10]!r}"
        )
    if progress:
        progress(scanned, len(selected))
    return manifest


def _identifier(file):
    return file.get("object_id") or file.get("file_id") or file.get("did")


def validate_memberships(sources):
    from collections import defaultdict

    by_case, by_project = defaultdict(set), defaultdict(set)
    seen_files = set()
    for file in sources["file"]:
        guid = _identifier(file)
        if not isinstance(guid, str) or not guid or guid in seen_files:
            raise ValueError("File sources require unique canonical GUIDs")
        seen_files.add(guid)
        for case in file.get("cases") or []:
            if case.get("case_id"):
                by_case[case["case_id"]].add(guid)
            project = (case.get("project") or {}).get("project_id")
            if project:
                by_project[project].add(guid)
    case_ids, projects, project_files = set(), defaultdict(set), defaultdict(set)
    for case in sources["case"]:
        case_id = case.get("case_id")
        if (
            not case_id
            or case_id in case_ids
            or not isinstance(case.get("files"), list)
        ):
            raise ValueError(
                "Case sources require unique IDs and complete embedded files"
            )
        case_ids.add(case_id)
        guids = {_identifier(file) for file in case["files"]}
        if guids != by_case[case_id]:
            raise ValueError(f"Case/file membership mismatch for case {case_id!r}")
        project = (case.get("project") or {}).get("project_id")
        if project:
            projects[project].add(case_id)
            project_files[project].update(guids)
    if by_case.keys() - case_ids:
        raise ValueError(
            "File sources reference cases missing from the case projection"
        )
    seen_projects = set()
    for project in sources["project"]:
        identifier = project.get("project_id")
        if not identifier or identifier in seen_projects:
            raise ValueError("Project IDs must be present and unique")
        seen_projects.add(identifier)
        if (project.get("summary") or {}).get("case_count") != len(
            projects[identifier]
        ):
            raise ValueError(f"Incomplete case coverage for project {identifier!r}")
        if project_files[identifier] != by_project[identifier]:
            raise ValueError(f"Project/file membership mismatch for {identifier!r}")
    if projects.keys() - seen_projects:
        raise ValueError("Case sources reference projects missing from the projection")


def _same_ownership(original, prepared):
    if isinstance(original, dict):
        current = prepared if isinstance(prepared, dict) else {}
        if original.get(AUTHZ) != current.get(AUTHZ):
            raise ValueError(
                "Stored ownership differs from current IndexD; rebuild the affected projection"
            )
        for key, value in original.items():
            if not key.startswith("_gen3_file_") and not key.startswith(
                "_gen3_visibility"
            ):
                _same_ownership(value, current.get(key))
    elif isinstance(original, list):
        current = prepared if isinstance(prepared, list) else []
        for index, before in enumerate(original):
            _same_ownership(before, current[index] if index < len(current) else None)


def prepare_inputs(sources, rows, progress=None):
    if not sources["file"]:
        raise ValueError("File projection is empty")
    strings, required = set(), set()
    for kind in KINDS:
        for source in sources[kind]:
            if source.get(VERSION) != 1:
                raise ValueError(f"Unprepared {kind} document")
            references(source, strings, required)
    validate_memberships(sources)
    manifest = select_manifest(rows, strings, required, progress)
    for kind in KINDS:
        if not sources[kind]:
            continue
        print(f"Validating {len(sources[kind])} {kind} sources", flush=True)
        checked = iter_prepare_sources(sources[kind], manifest, sources["file"])
        for source, prepared in zip(sources[kind], checked, strict=True):
            try:
                _same_ownership(source, prepared)
            except ValueError as exc:
                identifier = (
                    source.get("case_id")
                    or source.get("file_id")
                    or source.get("project_id")
                )
                raise ValueError(f"{kind} {identifier!r}: {exc}") from exc
    return manifest


def configuration(prefix, stage, repo, username, password):
    q = json.dumps
    lines = ["[build]", f"build_version = {q(prefix)}"]
    for name, path in {
        "driver": repo / "bin/driver.py",
        "pex_file": repo / "driver-all",
        "output_log": stage / "mutation-spark.stdout.log",
        "error_log": stage / "mutation-spark.stderr.log",
        "manifest_dir": stage / "mutation-manifests",
    }.items():
        lines.append(f"{name} = {q(str(path))}")
    lines.extend(
        [
            "[indexd]",
            f"user = {q(username)}",
            f"password = {q(password)}",
            "[elasticsearch.read]",
            f"case_index = {q(prefix + '_case')}",
            f"file_index = {q(prefix + '_file')}",
            "[elasticsearch.write.indices]",
        ]
    )
    lines.extend(f"{name.upper()} = {q(prefix + '_' + name)}" for name in VIZ)
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix")
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--mutation-repo", type=Path, required=True)
    parser.add_argument("--indexd-base-url", required=True)
    args = parser.parse_args()
    if os.getenv("PROJECT_VISIBILITY_ENABLED") != "true":
        parser.error("Set PROJECT_VISIBILITY_ENABLED=true")
    os.environ["INDEXD_HOST"] = args.indexd_base_url
    from elasticsearch import Elasticsearch, helpers
    from esbuild.utils import ES_CONFIG, get_default_index_client

    stage, repo = args.stage.resolve(), args.mutation_repo.resolve()
    names = ("indexd-manifest.json", "files.ndjson", "config-visibility.toml")
    for name in names:
        if (stage / name).exists():
            raise SystemExit(f"Already exists; refusing to overwrite: {stage / name}")
    if (stage / "mutation.started").exists():
        raise SystemExit("Mutation run already started for this stage")
    for name in (
        "driver-all",
        "bin/driver.py",
        "run/conf/config.toml",
        "run/conf/config-viz.toml",
    ):
        if not (repo / name).is_file():
            raise SystemExit(f"Required mutation file missing: {repo / name}")
    client = get_default_index_client()
    es = Elasticsearch(**ES_CONFIG)
    es.indices.refresh(index=",".join(f"{args.prefix}_{kind}" for kind in KINDS))
    sources = {}
    for kind in KINDS:
        print(f"Reading local {args.prefix}_{kind}", flush=True)
        sources[kind] = []
        for hit in helpers.scan(
            es, index=f"{args.prefix}_{kind}", query={"query": {"match_all": {}}}
        ):
            sources[kind].append(hit["_source"])
            if len(sources[kind]) % 10000 == 0:
                print(f"Read {len(sources[kind])} {kind} sources", flush=True)
        print(f"Read {len(sources[kind])} {kind} sources", flush=True)
    rows = (
        {"did": doc.did, "authz": doc.to_json().get("authz")}
        for doc in client.list(page_size=1000)
    )
    manifest = prepare_inputs(
        sources,
        rows,
        lambda total, used: print(
            f"Scanned {total} IndexD records; selected {used} referenced records",
            flush=True,
        ),
    )
    text = configuration(
        args.prefix,
        stage,
        repo,
        os.environ["INDEXD_USERNAME"],
        os.environ["INDEXD_PASSWORD"],
    )
    # Validate first, then atomically publish each file without overwriting an
    # existing snapshot. Temporary and final files stay owner-readable only.
    published = []
    with tempfile.TemporaryDirectory(
        prefix=".visibility-export-", dir=stage
    ) as temporary:
        temporary = Path(temporary)
        for name in names:
            fd = os.open(temporary / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as out:
                if name == "indexd-manifest.json":
                    json.dump(manifest, out)
                elif name == "files.ndjson":
                    for source in sources["file"]:
                        out.write(json.dumps(source) + "\n")
                else:
                    out.write(text)
        try:
            for name in names:
                os.link(temporary / name, stage / name)
                published.append(stage / name)
        except Exception:
            for path in published:
                path.unlink()
            raise
    print(
        f"Prepared {len(manifest['records'])} referenced IndexD records and "
        f"{len(sources['file'])} file sources in {stage}",
        flush=True,
    )


if __name__ == "__main__":
    main()
