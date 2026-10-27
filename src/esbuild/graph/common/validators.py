VISIBLE_NODES = frozenset({"submitted_genotyping_array", "submitted_expression_array"})


def is_index_file(node, indexd_metadata, index_file_extensions):
    """Keep legacy index detection, allowing explicit generic repository downloads."""
    if node._dictionary["category"] == "index_file":
        return True
    if node.label != "file":
        return False
    if indexd_metadata.get("repository_only") == "true":
        return False
    return any(node.file_name.endswith(extension) for extension in index_file_extensions)


def is_node_hidden(node):
    """Check whether node should be traversed but should not in any documents.

    Return True if the node should be traversed (and therefore must
    remain in the cache) but should not appear in any documents

    """
    if node.label in VISIBLE_NODES:
        return False

    # Hide all submitted_* node types from indices
    return node.label.startswith("submitted_") or node.label in [
        "archive",
        "raw_methylation_array",
    ]
