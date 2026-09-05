from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_eyes_promotion_eligibility as eligibility

PREVIEW_JOB = "hfpreview-" + "a" * 32
COMPONENT_REVISION = "1" * 40
RUNTIME_REVISION = "2" * 40
ELIGIBILITY_REVISION = "3" * 40
PACKAGE_SHA = "4" * 64
VRM_SHA = "5" * 64
IRIS_REVIEW_SHA = "6" * 64
IRIS_CANDIDATE_SHA = "7" * 64
EYE_APPEARANCE_SHA = "8" * 64
BAKE_SHA = "9" * 64


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authorities(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path, Path]:
    monkeypatch.setattr(eligibility, "ui_jobs_dir", lambda: tmp_path / "ui-jobs")
    component_path = tmp_path / "component-review.json"
    component_path.write_text('{"component":"review"}', encoding="utf-8")
    component = {
        "preview_job_id": PREVIEW_JOB,
        "person_id": "person-fixture",
        "body_revision": "body-r3",
        "canonical_body_id": "fixture-body",
        "bodyrig_revision": COMPONENT_REVISION,
        "target_family": "female",
        "candidate_package_sha256": PACKAGE_SHA,
        "review_vrm_sha256": VRM_SHA,
        "human_review_complete": True,
        "production_activation": False,
        "review_outcome": {
            "body_anatomy": "pass",
            "hair": "visual-pass-deformation-review-required",
            "eyes": "visual-pass-iris-authority-required",
        },
        "promotion_eligibility": {"body_anatomy": True, "hair": False, "eyes": False},
    }
    monkeypatch.setattr(eligibility, "read_component_review", lambda job_id: dict(component))
    monkeypatch.setattr(eligibility, "component_review_path", lambda *args, **kwargs: component_path)

    base_dir = tmp_path / "base-runtime"
    iris_dir = tmp_path / "iris"
    source_dir = tmp_path / "source-eye"
    reviewed_dir = tmp_path / "reviewed-runtime"
    for path in (base_dir, iris_dir, source_dir, reviewed_dir):
        path.mkdir()
    base_receipt_path = base_dir / eligibility.BASE_RUNTIME_RECEIPT
    base_receipt = {
        "bodyId": "fixture-body",
        "packageSha256": PACKAGE_SHA,
        "targetModelFamily": "female",
        "reviewVrmSha256": VRM_SHA,
    }
    base_receipt_path.write_text(json.dumps(base_receipt), encoding="utf-8")
    reviewed_receipt = reviewed_dir / "source-hair-eye-iris-reviewed-runtime.json"
    reviewed_receipt.write_text('{"reviewed":"runtime"}', encoding="utf-8")
    reviewed = {
        "reviewReceiptPath": str(reviewed_receipt.resolve()),
        "bodyrigRevision": RUNTIME_REVISION,
        "baseRuntimeReceiptSha256": _sha(base_receipt_path),
        "baseReviewVrmSha256": VRM_SHA,
        "reviewedVrmSha256": VRM_SHA,
        "irisCandidateSha256": IRIS_CANDIDATE_SHA,
        "irisReviewSha256": IRIS_REVIEW_SHA,
        "sourceEyeAppearanceReceiptSha256": EYE_APPEARANCE_SHA,
        "canonicalEyeBakeSha256": BAKE_SHA,
        "targetModelFamily": "female",
        "runtimeBytesUnchanged": True,
        "sourceEyePixelsUnchanged": True,
        "embeddedEyeRuntimeStillReviewPending": True,
        "irisReviewOverlayApplied": True,
        "irisIdentityIsolated": True,
        "irisAppearanceStatus": "source-isolated-review-pass",
        "eyeComponentAuthority": False,
        "eyesPromotionEligible": False,
        "productionActivation": False,
    }
    monkeypatch.setattr(eligibility, "read_reviewed_runtime", lambda **kwargs: dict(reviewed))
    return base_dir, iris_dir, source_dir, reviewed_dir


def test_exact_visual_plus_same_vrm_iris_review_makes_eyes_promotion_eligible_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, iris_dir, source_dir, reviewed_dir = _authorities(tmp_path, monkeypatch)
    result = eligibility.write_eligibility(
        PREVIEW_JOB,
        base_runtime_dir=base_dir,
        iris_candidate_dir=iris_dir,
        source_eye_appearance_dir=source_dir,
        reviewed_runtime_dir=reviewed_dir,
        bodyrig_revision=ELIGIBILITY_REVISION,
    )
    assert result["eyesPromotionEligible"] is True
    assert result["eyeComponentAuthority"] is False
    assert result["packageMutationPerformed"] is False
    assert result["eyesPromoted"] is False
    assert result["eyelashStatus"] == "missing"
    assert result["faceSecondaryUnaffected"] is True
    assert result["productionActivation"] is False
    assert result["candidatePackageSha256"] == PACKAGE_SHA
    assert result["reviewVrmSha256"] == VRM_SHA
    assert result["irisReviewSha256"] == IRIS_REVIEW_SHA


def test_eligibility_rejects_iris_review_bound_to_different_visual_review_vrm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, iris_dir, source_dir, reviewed_dir = _authorities(tmp_path, monkeypatch)
    original = eligibility.read_reviewed_runtime

    def different(**kwargs):
        value = original(**kwargs)
        value["baseReviewVrmSha256"] = "a" * 64
        value["reviewedVrmSha256"] = "a" * 64
        return value

    monkeypatch.setattr(eligibility, "read_reviewed_runtime", different)
    with pytest.raises(eligibility.HighFidelityEyesPromotionEligibilityError, match="exact VRM bytes"):
        eligibility.write_eligibility(
            PREVIEW_JOB,
            base_runtime_dir=base_dir,
            iris_candidate_dir=iris_dir,
            source_eye_appearance_dir=source_dir,
            reviewed_runtime_dir=reviewed_dir,
            bodyrig_revision=ELIGIBILITY_REVISION,
        )


def test_eligibility_rejects_base_runtime_from_different_candidate_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, iris_dir, source_dir, reviewed_dir = _authorities(tmp_path, monkeypatch)
    path = base_dir / eligibility.BASE_RUNTIME_RECEIPT
    value = json.loads(path.read_text(encoding="utf-8"))
    value["packageSha256"] = "b" * 64
    path.write_text(json.dumps(value), encoding="utf-8")
    reviewed_receipt_sha = _sha(path)
    original = eligibility.read_reviewed_runtime

    def rebound(**kwargs):
        result = original(**kwargs)
        result["baseRuntimeReceiptSha256"] = reviewed_receipt_sha
        return result

    monkeypatch.setattr(eligibility, "read_reviewed_runtime", rebound)
    with pytest.raises(eligibility.HighFidelityEyesPromotionEligibilityError, match="package differs"):
        eligibility.write_eligibility(
            PREVIEW_JOB,
            base_runtime_dir=base_dir,
            iris_candidate_dir=iris_dir,
            source_eye_appearance_dir=source_dir,
            reviewed_runtime_dir=reviewed_dir,
            bodyrig_revision=ELIGIBILITY_REVISION,
        )


def test_eligibility_requires_component_review_to_name_iris_as_remaining_eye_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, iris_dir, source_dir, reviewed_dir = _authorities(tmp_path, monkeypatch)
    original = eligibility.read_component_review

    def different(job_id):
        value = original(job_id)
        value["review_outcome"]["eyes"] = "pass"
        return value

    monkeypatch.setattr(eligibility, "read_component_review", different)
    with pytest.raises(eligibility.HighFidelityEyesPromotionEligibilityError, match="iris authority as the remaining eyes gate"):
        eligibility.write_eligibility(
            PREVIEW_JOB,
            base_runtime_dir=base_dir,
            iris_candidate_dir=iris_dir,
            source_eye_appearance_dir=source_dir,
            reviewed_runtime_dir=reviewed_dir,
            bodyrig_revision=ELIGIBILITY_REVISION,
        )


def test_failed_post_write_revalidation_removes_only_new_eligibility_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, iris_dir, source_dir, reviewed_dir = _authorities(tmp_path, monkeypatch)
    expected_path = eligibility.eligibility_path(PREVIEW_JOB, review_vrm_sha256=VRM_SHA, iris_review_sha256=IRIS_REVIEW_SHA)
    monkeypatch.setattr(
        eligibility,
        "read_eligibility",
        lambda *args, **kwargs: (_ for _ in ()).throw(eligibility.HighFidelityEyesPromotionEligibilityError("post-write fixture")),
    )
    with pytest.raises(eligibility.HighFidelityEyesPromotionEligibilityError, match="post-write fixture"):
        eligibility.write_eligibility(
            PREVIEW_JOB,
            base_runtime_dir=base_dir,
            iris_candidate_dir=iris_dir,
            source_eye_appearance_dir=source_dir,
            reviewed_runtime_dir=reviewed_dir,
            bodyrig_revision=ELIGIBILITY_REVISION,
        )
    assert not expected_path.exists()
    assert (base_dir / eligibility.BASE_RUNTIME_RECEIPT).is_file()
