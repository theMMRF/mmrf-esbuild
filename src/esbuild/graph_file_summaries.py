"""Reconcile legacy graph-node totals with the complete GUID-deduplicated index.

Graph summaries count file nodes, while _upsert_file_into_dict merges nodes with
the same IndexD object_id. Prove membership using case.files and both directions
of the case/file relationships before replacing those legacy numeric totals.
"""

from collections import defaultdict


def reconcile_graph_file_summaries(cases, files, annotations, projects):
    def identifier(file):
        value = file.get("object_id") or file.get("file_id") or file.get("did")
        if not isinstance(value, str) or not value:
            raise ValueError("Graph file summary requires an IndexD file identifier")
        return value

    def same_members(scope, expected, actual):
        if expected != actual:
            missing, extra = sorted(expected - actual), sorted(actual - expected)
            raise ValueError(
                f"Incomplete graph file projection for {scope}: "
                f"expected {len(expected)} unique GUIDs, found {len(actual)}; "
                f"missing={missing[:5]!r}, unexpected={extra[:5]!r}"
            )

    file_rows = {}
    by_case, by_project = defaultdict(set), defaultdict(set)
    for file in files:
        guid = identifier(file)
        if guid in file_rows:
            raise ValueError(f"Duplicate file-index document for GUID {guid!r}")
        size = file.get("file_size") or 0
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError(f"Invalid file size for GUID {guid!r}")
        file_rows[guid] = file
        for case in file.get("cases") or []:
            if case.get("case_id"):
                by_case[case["case_id"]].add(guid)
            project_id = (case.get("project") or {}).get("project_id")
            if project_id:
                by_project[project_id].add(guid)

    scopes = {}
    expected_projects, project_cases = defaultdict(set), defaultdict(set)
    for case in cases:
        case_id = case.get("case_id")
        embedded = case.get("files")
        summary = case.get("summary")
        if not case_id or ("case", case_id) in scopes:
            raise ValueError("Graph case IDs must be present and unique")
        if (
            not isinstance(embedded, list)
            or not isinstance(summary, dict)
            or summary.get("file_count") != len(embedded)
        ):
            raise ValueError(
                f"Incomplete graph file list for case {case_id!r}: "
                "legacy file_count must match the embedded graph-file records"
            )
        expected = {identifier(file) for file in embedded}
        same_members(f"case {case_id!r}", expected, by_case[case_id])
        scopes["case", case_id] = expected
        project_id = (case.get("project") or {}).get("project_id")
        if project_id:
            expected_projects[project_id].update(expected)
            project_cases[project_id].add(case_id)

    for project in projects:
        project_id = project.get("project_id")
        if not project_id or ("project", project_id) in scopes:
            raise ValueError("Graph project IDs must be present and unique")
        expected_cases = (project.get("summary") or {}).get("case_count")
        if expected_cases != len(project_cases[project_id]):
            raise ValueError(
                f"Incomplete graph case projection for project {project_id!r}: "
                f"expected {expected_cases!r} cases, "
                f"found {len(project_cases[project_id])}"
            )
        expected = expected_projects[project_id]
        same_members(f"project {project_id!r}", expected, by_project[project_id])
        scopes["project", project_id] = expected

    # All membership checks finish before changing any summary. IndexD ownership
    # validation still runs afterward, before Elasticsearch destinations change.
    totals = {
        scope: {
            "file_count": len(guids),
            "file_size": sum(file_rows[guid].get("file_size") or 0 for guid in guids),
        }
        for scope, guids in scopes.items()
    }

    def reconcile(value):
        if isinstance(value, list):
            for child in value:
                reconcile(child)
        elif isinstance(value, dict):
            summary = value.get("summary")
            if isinstance(summary, dict):
                scope = (
                    ("case", value["case_id"])
                    if value.get("case_id")
                    else ("project", value.get("project_id"))
                )
                if scope in totals:
                    for name, total in totals[scope].items():
                        if name in summary:
                            summary[name] = total
            for name, child in value.items():
                if name != "summary":
                    reconcile(child)

    for documents in (cases, files, annotations, projects):
        reconcile(documents)
