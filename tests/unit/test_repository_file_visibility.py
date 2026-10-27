"""The repository override must be explicit and limited to generic files."""
from types import SimpleNamespace
import unittest

from esbuild.graph.common.validators import is_index_file


def node(label="file", name="reads.bai", category="data_file"):
    return SimpleNamespace(label=label, file_name=name, _dictionary={"category": category})


class RepositoryFileTests(unittest.TestCase):
    def test_marked_generic_downloads(self):
        for name in ("reads.bai", "reads.bam.bai", "reads.bam", "counts.h5"):
            self.assertFalse(is_index_file(node(name=name), {"repository_only": "true"}, [".bai"]))

    def test_unmarked_legacy_files_keep_extension_filter(self):
        for metadata in ({}, {"repository_only": "false"}, {"repository_only": True}):
            with self.subTest(metadata=metadata):
                self.assertTrue(is_index_file(node(), metadata, [".bai"]))
                self.assertFalse(is_index_file(node(name="reads.bam"), metadata, [".bai"]))

    def test_marker_does_not_override_dedicated_index_or_analysis_nodes(self):
        self.assertTrue(is_index_file(node(label="aligned_reads_index", category="index_file"), {"repository_only": "true"}, [".bai"]))
        for label in ("gene_expression", "aligned_reads", "case"):
            with self.subTest(label=label):
                self.assertFalse(is_index_file(node(label=label), {"repository_only": "true"}, [".bai"]))


if __name__ == "__main__": unittest.main()
