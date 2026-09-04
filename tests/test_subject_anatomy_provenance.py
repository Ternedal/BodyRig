from __future__ import annotations

import hashlib
import json

import pytest

from bodyrig.subject_anatomy_provenance import (
    SubjectAnatomyProvenanceError,
    load_subject_anatomy_refit,
    provenance_stage,
    validate_subject_anatomy_refit,
)


def _receipt() -> dict:
    return {
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


def test_subject_anatomy_provenance_accepts_non_regressed_comparison_candidate(tmp_path) -> None:
    path = tmp_path / "subject-anatomy-refit.json"
    path.write_text(json.dumps(_receipt()) + "\n", encoding="utf-8")

    validated = load_subject_anatomy_refit(path)
    stage = provenance_stage(path)

    assert validated["targetModelFamily"] == "female"
    assert validated["fitDidNotRegress"] is True
    assert validated["comparisonOnly"] is True
    assert validated["productionReady"] is False
    assert stage == {
        "stage": "subject-anatomy-refit",
        "adapter": "bodyrig.subject_anatomy_refit.female",
        "revision": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_subject_anatomy_provenance_rejects_regressed_package_candidate() -> None:
    value = _receipt()
    value["finalDonorToSourceP95"] = 0.081
    value["fitDidNotRegress"] = False

    with pytest.raises(SubjectAnatomyProvenanceError, match="regressed subject anatomy candidate"):
        validate_subject_anatomy_refit(value, require_non_regression=True)

    accepted_for_forensics = validate_subject_anatomy_refit(value, require_non_regression=False)
    assert accepted_for_forensics["fitDidNotRegress"] is False


def test_subject_anatomy_provenance_rejects_production_or_generative_claims() -> None:
    for field, value in (("productionReady", True), ("generativeGeometry", True), ("reconstructionRerun", True)):
        receipt = _receipt()
        receipt[field] = value
        with pytest.raises(SubjectAnatomyProvenanceError, match="authority boundary"):
            validate_subject_anatomy_refit(receipt)


def test_subject_anatomy_provenance_rejects_inconsistent_non_regression_claim() -> None:
    value = _receipt()
    value["finalDonorToSourceRms"] = 0.05
    value["fitDidNotRegress"] = True

    with pytest.raises(SubjectAnatomyProvenanceError, match="claim is inconsistent"):
        validate_subject_anatomy_refit(value)
