import pytest
from gdcdatamodel2 import models

from esbuild.graph.common import validators


@pytest.mark.parametrize(
    "node, hidden",
    [
        (models.Case(), False),
        (models.Aliquot(), False),
        (models.Archive(), True),
        (models.MethylationBetaValue(), False),
        (models.SubmittedAlignedReads(), True),
        (models.SubmittedGenomicProfile(), True),
        (models.SubmittedGenotypingArray(), False),
        (models.SubmittedMethylationBetaValue(), True),
        (models.SubmittedTangentCopyNumber(), True),
        (models.SubmittedUnalignedReads(), True),
        (models.SubmittedUnalignedReads(project_id="MMRF-COMMPASS"), True),
        (models.SubmittedAlignedReads(project_id="MMRF-Precision-Prevention-Study"), False),
        (models.SubmittedUnalignedReads(project_id="MMRF-Impact-Study"), False),
        (models.Archive(project_id="MMRF-Precision-Prevention-Study"), True),
        (models.RawMethylationArray(), True),
    ],
)
def test_is_hidden_nodes(node, hidden):
    assert validators.is_node_hidden(node) is hidden
