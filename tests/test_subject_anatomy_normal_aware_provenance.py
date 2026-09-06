from __future__ import annotations

import pytest

from bodyrig.subject_anatomy_provenance import (
    METHOD_V2,
    SubjectAnatomyProvenanceError,
    validate_subject_anatomy_refit,
)


def _receipt() -> dict:
    return {
        "format": "bodyrig-subject-anatomy-refit",
        "version": 1,
        "targetModelFamily": "female",
        "method": METHOD_V2,
        "initialDonorToSourceP95": 0.043934,
        "initialDonorToSourceRms": 0.022300,
        "finalDonorToSourceP95": 0.035608,
        "finalDonorToSourceRms": 0.016780,
        "initialNormalAlignmentMean": 0.90,
        "initialNormalAlignmentP05": 0.65,
        "finalNormalAlignmentMean": 0.92,
        "finalNormalAlignmentP05": 0.69,
        "normalAwareNonRegression": True,
        "normalAlignmentAuthority": "nearest-source-vertex-area-weighted-v1",
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


def test_normal_aware_provenance_accepts_distance_and_normal_improvement() -> None:
    validated = validate_subject_anatomy_refit(_receipt())
    assert validated["method"] == METHOD_V2
    assert validated["normalAwareNonRegression"] is True
    assert validated["fitDidNotRegress"] is True


def test_normal_aware_provenance_rejects_distance_improvement_with_normal_regression() -> None:
    value = _receipt()
    value["finalNormalAlignmentMean"] = 0.88
    value["finalNormalAlignmentP05"] = 0.60
    value["normalAwareNonRegression"] = False
    value["fitDidNotRegress"] = False

    with pytest.raises(SubjectAnatomyProvenanceError, match="regressed subject anatomy candidate"):
        validate_subject_anatomy_refit(value, require_non_regression=True)

    forensic = validate_subject_anatomy_refit(value, require_non_regression=False)
    assert forensic["normalAwareNonRegression"] is False
    assert forensic["fitDidNotRegress"] is False


def test_normal_aware_provenance_rejects_false_normal_non_regression_claim() -> None:
    value = _receipt()
    value["finalNormalAlignmentP05"] = 0.60
    value["normalAwareNonRegression"] = True
    value["fitDidNotRegress"] = True

    with pytest.raises(SubjectAnatomyProvenanceError, match="normal non-regression claim is inconsistent"):
        validate_subject_anatomy_refit(value, require_non_regression=False)
