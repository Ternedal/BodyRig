from __future__ import annotations

import copy

import pytest

from bodyrig.subject_anatomy_provenance import (
    SubjectAnatomyProvenanceError,
    _finite_alignment,
    _finite_nonnegative,
    _finite_vector,
    validate_subject_anatomy_refit,
)


RECEIPT = {
    "format": "bodyrig-subject-anatomy-refit",
    "version": 1,
    "targetModelFamily": "female",
    "method": "explicit-family-smplx-betas-icp-to-retained-sith-source-v1",
    "initialDonorToSourceP95": 0.08,
    "initialDonorToSourceRms": 0.04,
    "finalDonorToSourceP95": 0.05,
    "finalDonorToSourceRms": 0.025,
    "iterations": 120,
    "fitDidNotRegress": True,
    "poseAuthority": "retained-sith-fit",
    "shapeAuthority": "derived-target-family-fit-to-retained-source",
    "retainedReconstructionModified": False,
    "reconstructionRerun": False,
    "generativeGeometry": False,
    "comparisonOnly": True,
    "humanReviewRequired": True,
    "productionReady": False,
    "reconstructionSha256": "1" * 64,
    "retainedSmplxObjSha256": "2" * 64,
    "retainedFitParamsSha256": "3" * 64,
    "retainedSourceMeshSha256": "4" * 64,
    "derivedSmplxObjSha256": "5" * 64,
    "derivedFitParamsSha256": "6" * 64,
    "derivedScale": 1.02,
    "derivedBetas": [0.1] * 10,
    "derivedTransl": [0.01, -0.02, 0.03],
}


def test_numeric_helpers_normalize_huge_integer_overflow() -> None:
    with pytest.raises(SubjectAnatomyProvenanceError, match="distance"):
        _finite_nonnegative(10**400, label="distance")
    with pytest.raises(SubjectAnatomyProvenanceError, match="alignment"):
        _finite_alignment(10**400, label="alignment")
    with pytest.raises(SubjectAnatomyProvenanceError, match="vector"):
        _finite_vector([0.0, 10**400], label="vector", length=2)


def test_persisted_scalar_and_vector_overflow_fail_with_domain_error() -> None:
    scalar = copy.deepcopy(RECEIPT)
    scalar["initialDonorToSourceP95"] = 10**400
    with pytest.raises(SubjectAnatomyProvenanceError, match="initial anatomy p95"):
        validate_subject_anatomy_refit(scalar)

    vector = copy.deepcopy(RECEIPT)
    vector["derivedBetas"][3] = 10**400
    with pytest.raises(SubjectAnatomyProvenanceError, match="derived anatomy betas"):
        validate_subject_anatomy_refit(vector)


def test_boolean_version_is_rejected_but_numeric_v1_equality_is_preserved() -> None:
    boolean_version = copy.deepcopy(RECEIPT)
    boolean_version["version"] = True
    with pytest.raises(SubjectAnatomyProvenanceError, match="format"):
        validate_subject_anatomy_refit(boolean_version)

    numeric_version = copy.deepcopy(RECEIPT)
    numeric_version["version"] = 1.0
    assert validate_subject_anatomy_refit(numeric_version)["version"] == 1


def test_ordinary_numeric_receipt_remains_valid() -> None:
    validated = validate_subject_anatomy_refit(copy.deepcopy(RECEIPT))
    assert validated["initialDonorToSourceP95"] == 0.08
    assert validated["derivedBetas"] == [0.1] * 10
