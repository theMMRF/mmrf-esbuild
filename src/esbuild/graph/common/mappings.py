"""esbuild.graph.common.mappings.

Common definitions for building GDC Elasticsearch mappings

"""

# These values specify the multiplicity of the relationship from
# parent to child.
import functools
from collections.abc import Mapping
from typing import Any

import gdcmodels
from gdcmodels import esmodels

ONE_TO_ONE = "__one_to_one__"
ONE_TO_MANY = "__one_to_many__"

HIDDEN_PROJECT_KEYS = frozenset(
    (
        "release_requested",
        "awg_review",
        "is_legacy",
        "in_review",
        "submission_enabled",
        "request_submission",
    )
)
TOP_LEVEL_IDS = frozenset(
    (
        "sample",
        "portion",
        "analyte",
        "aliquot",
        "slide",
        "diagnosis",
    )
)

FILE_TREE = {
    "file": {
        "corr": (ONE_TO_MANY, "files"),
        "annotation": {"corr": (ONE_TO_MANY, "annotations")},
        "archive": {"corr": (ONE_TO_ONE, "archive")},
        "center": {"corr": (ONE_TO_ONE, "center")},
        "data_format": {"corr": (ONE_TO_ONE, "data_format")},
        "data_subtype": {
            "corr": (ONE_TO_ONE, "data_type"),
            "data_type": {"corr": (ONE_TO_ONE, "data_category")},
        },
        "experimental_strategy": {"corr": (ONE_TO_ONE, "experimental_strategy")},
        "case": {"corr": (ONE_TO_MANY, "cases")},
        "platform": {"corr": (ONE_TO_ONE, "platform")},
        "tag": {"corr": (ONE_TO_MANY, "tags")},
        "file": {"corr": (ONE_TO_MANY, "metadata_files")},
    }
}
CASE_TREE = {
    "case": {
        "corr": (ONE_TO_MANY, "cases"),
        "bone_assessment": {"corr": (ONE_TO_MANY, "bone_assessments")},
        "administered_regimen_line": {"corr": (ONE_TO_MANY, "administered_regimen_lines")},
        "outcomes":  {"corr": (ONE_TO_MANY, "outcomes")},
        "annotation": {"corr": (ONE_TO_MANY, "annotations")},
        "project": {
            "corr": (ONE_TO_ONE, "project"),
            "program": {"corr": (ONE_TO_ONE, "program")},
        },
        "file": {"corr": (ONE_TO_MANY, "files")},
        "tissue_source_site": {"corr": (ONE_TO_ONE, "tissue_source_site")},
        "sample": {
            "corr": (ONE_TO_MANY, "samples"),
            "analyte": {
                "corr": (ONE_TO_MANY, "analytes"),
                "aliquot": {"corr": (ONE_TO_MANY, "aliquots")},
            },
            "annotation": {"corr": (ONE_TO_MANY, "annotations")},
            "aliquot": {"corr": (ONE_TO_MANY, "aliquots")},
            "portion": {
                "corr": (ONE_TO_MANY, "portions"),
                "analyte": {
                    "corr": (ONE_TO_MANY, "analytes"),
                    "annotation": {"corr": (ONE_TO_MANY, "annotations")},
                    "aliquot": {
                        "corr": (ONE_TO_MANY, "aliquots"),
                        "annotation": {"corr": (ONE_TO_MANY, "annotations")},
                        "center": {"corr": (ONE_TO_ONE, "center")},
                    },
                },
                "annotation": {"corr": (ONE_TO_MANY, "annotations")},
                "center": {"corr": (ONE_TO_ONE, "center")},
                "slide": {
                    "corr": (ONE_TO_MANY, "slides"),
                    "annotation": {"corr": (ONE_TO_MANY, "annotations")},
                },
            },
            "slide": {
                "corr": (ONE_TO_MANY, "slides"),
                "annotation": {"corr": (ONE_TO_MANY, "annotations")},
            },
        },
        "demographic": {"corr": (ONE_TO_ONE, "demographic")},
        "exposure": {"corr": (ONE_TO_MANY, "exposures")},
        "diagnosis": {
            "corr": (ONE_TO_MANY, "diagnoses"),
            "annotation": {"corr": (ONE_TO_MANY, "annotations")},
            "pathology_detail": {"corr": (ONE_TO_MANY, "pathology_details")},
            "treatment": {"corr": (ONE_TO_MANY, "treatments")},
            "molecular_test": {"corr": (ONE_TO_MANY, "molecular_tests")},
        },
        "follow_up": {
            "corr": (ONE_TO_MANY, "follow_ups"),
            "molecular_test": {"corr": (ONE_TO_MANY, "molecular_tests")},
            "other_clinical_attribute": {"corr": (ONE_TO_MANY, "other_clinical_attributes")},
        },
        "family_history": {"corr": (ONE_TO_MANY, "family_histories")},
        "other_clinical_attribute": {"corr": (ONE_TO_MANY, "other_clinical_attributes")},
    }
}


@functools.cache
def _load_models() -> Mapping[str, gdcmodels.ModelMapper]:
    return gdcmodels.get_es_models(vestigial_included=False)["gdc_from_graph"]


def get_annotation_mapping() -> esmodels.ESMapping:
    return _load_models()["annotation"].mappings


def get_case_mapping() -> esmodels.ESMapping:
    return _load_models()["case"].mappings


def get_file_mapping() -> esmodels.ESMapping:
    return _load_models()["file"].mappings


def get_project_mapping() -> esmodels.ESMapping:
    return _load_models()["project"].mappings


def get_settings() -> Mapping[str, Any]:
    return _load_models()["annotation"].settings
