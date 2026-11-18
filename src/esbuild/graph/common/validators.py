VISIBLE_NODES = frozenset({"submitted_genotyping_array", "submitted_expression_array"})
# Repository projects hold files as their provider submitted them (no harmonized
# copies), so their submitted reads files are what users browse and download.
REPOSITORY_PROJECTS = frozenset({"MMRF-Precision-Prevention-Study", "MMRF-Impact-Study"})


def is_node_hidden(node):
    """Check whether node should be traversed but should not in any documents.

    Return True if the node should be traversed (and therefore must
    remain in the cache) but should not appear in any documents

    """
    if node.label in VISIBLE_NODES:
        return False

    if node.label.startswith("submitted_") and node.project_id in REPOSITORY_PROJECTS:
        return False

    # Hide all submitted_* node types from indices
    return node.label.startswith("submitted_") or node.label in [
        "archive",
        "raw_methylation_array",
    ]
