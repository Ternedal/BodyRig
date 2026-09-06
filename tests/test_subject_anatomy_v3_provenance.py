from __future__ import annotations

import pytest

from bodyrig.subject_anatomy_provenance import (
    METHOD_V3,
    NORMAL_ALIGNMENT_AUTHORITY_V3,
    NORMAL_SAMPLE_METHOD_V3,
    SubjectAnatomyProvenanceError,
    validate_subject_anatomy_refit,
)


def _receipt() -> dict:
    return {
        "format": "bodyrig-subject-anatomy-refit",
        "version": 1,
        "targetModelFamily": "female",
        "method": METHOD_V3,
        "initialDonorToSourceP95": 0.043934,
        "initialDonorToSourceRms": 0.022300,
        "finalDonorToSourceP95": 0.035700,
        "finalDonorToSourceRms": 0.016900,
        "initialNormalAlignmentMean": 0.90,
        "initialNormalAlignmentP05": 0.64,
        "finalNormalAlignmentMean": 0.91,
        "finalNormalAlignmentP05": 0.66,
        "normalAwareNonRegression": True,
        "normalAlignmentAuthority": NORMAL_ALIGNMENT_AUTHORITY_V3,
        "normalSampleMethod": NORMAL_SAMPLE_METHOD_V3,
        "normalSampleCount": 4096,
        "normalLossWeight": 0.04,
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


def test_v3_provenance_accepts_bake_aligned_normal_authority() -> None:
    validated = validate_subject_anatomy_refit(_receipt())

    assert validated["method"] == METHOD_V3
    assert validated["normalAlignmentAuthority"] == NORMAL_ALIGNMENT_AUTHORITY_V3
    assert validated["normalSampleMethod"] == NORMAL_SAMPLE_METHOD_V3
    assert validated["normalSampleCount"] == 4096
    assert validated["fitDidNotRegress"] is True


def test_v3_provenance_rejects_v2_vertex_normal_authority() -> None:
    receipt = _receipt()
    receipt["normalAlignmentAuthority"] = "nearest-source-vertex-area-weighted-v1"

    with pytest.raises(SubjectAnatomyProvenanceError, match="normal alignment authority"):
        validate_subject_anatomy_refit(receipt)


def test_v3_provenance_rejects_distance_only_win_when_normals_regress() -> None:
    receipt = _receipt()
    receipt["finalNormalAlignmentMean"] = 0.89
    receipt["finalNormalAlignmentP05"] = 0.61
    receipt["normalAwareNonRegression"] = False
    receipt["fitDidNotRegress"] = False

    with pytest.raises(SubjectAnatomyProvenanceError, match="regressed subject anatomy candidate"):
        validate_subject_anatomy_refit(receipt, require_non_regression=True)

    forensic = validate_subject_anatomy_refit(receipt, require_non_regression=False)
    assert forensic["fitDidNotRegress"] is False
