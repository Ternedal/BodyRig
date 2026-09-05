from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.source_iris_review_runtime as runtime

REVIEW_REVISION = "1" * 40
BASE_REVISION = "2" * 40
EYE_APPEARANCE_SHA = "a" * 64
CANONICAL_BAKE_SHA = "b" * 64


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _base_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, bytes]:
    root = tmp_path / "base-runtime"
    root.mkdir()
    vrm = root / runtime.BASE_VRM_NAME
    raw = b"exact-combined-review-vrm-fixture"
    vrm.write_bytes(raw)
    receipt = {
        "format": "bodyrig-source-hair-eye-review-runtime",
        "version": 1,
        "bodyrigRevision": BASE_REVISION,
        "bridgeScriptSha256": "3" * 64,
        "bodyId": "fixture-body",
        "packageSha256": "4" * 64,
        "baseAvatarVrmSha256": "5" * 64,
        "sourceHairBodyBindingSha256": "6" * 64,
        "hairCandidateReceiptSha256": "7" * 64,
        "eyeComponentReceiptSha256": "8" * 64,
        "eyeAppearanceReceiptSha256": EYE_APPEARANCE_SHA,
        "reviewVrmSha256": _sha(raw),
        "bridgeResultSha256": "9" * 64,
        "targetModelFamily": "female",
        "hairMeshIndex": 1,
        "eyeMeshIndex": 2,
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 12,
        "sourceHairRuntimeApplied": True,
        "sourceEyeSurfaceApplied": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "runtime-applied",
        "eyelashStatus": "missing",
        "runtimeIntegrationStatus": "hair-and-eyes-review-artifact-ready",
        "physicalSilhouetteReviewRequired": True,
        "physicalFaceCloseupReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "eyeComponentAuthority": False,
        "productionActivation": False,
    }
    (root / runtime.BASE_RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
    eye_metadata = {
        "format": "bodyrig-source-eye-review-runtime-metadata",
        "version": 1,
        "eyeComponentReceiptSha256": "8" * 64,
        "eyeAppearanceReceiptSha256": EYE_APPEARANCE_SHA,
        "canonicalEyeBakeSha256": CANONICAL_BAKE_SHA,
        "targetModelFamily": "female",
        "leftEyeJointIndex": 23,
        "rightEyeJointIndex": 24,
        "sourceEyeSurfaceApplied": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "runtime-applied",
        "eyelashStatus": "missing",
        "skinIndex": 0,
        "physicalFaceCloseupReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "eyeComponentAuthority": False,
        "productionActivation": False,
    }
    monkeypatch.setattr(
        runtime,
        "validate_vrm1",
        lambda value: {"extras": {"bodyrig": {"eyeReviewRuntime": dict(eye_metadata)}}},
    )
    return root, raw


def _iris_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    candidate_dir = tmp_path / "iris-candidate"
    source_dir = tmp_path / "eye-appearance"
    candidate_dir.mkdir()
    source_dir.mkdir()
    candidate_path = candidate_dir / "iris-isolation-candidate.json"
    review_path = candidate_dir / "iris-isolation-review.fixture.json"
    candidate_path.write_text('{"candidate":"fixture"}', encoding="utf-8")
    review_path.write_text('{"review":"fixture"}', encoding="utf-8")
    candidate = {
        "bodyrigRevision": REVIEW_REVISION,
        "candidatePath": str(candidate_path.resolve()),
        "sourceEyeAppearanceReceiptSha256": EYE_APPEARANCE_SHA,
        "sourceCanonicalEyeBakeSha256": CANONICAL_BAKE_SHA,
        "sourceLeftEyeAppearanceSha256": "c" * 64,
        "sourceRightEyeAppearanceSha256": "d" * 64,
        "targetModelFamily": "female",
    }
    review = {
        "bodyrigRevision": REVIEW_REVISION,
        "reviewPath": str(review_path.resolve()),
        "irisIdentityIsolated": True,
        "irisAppearanceStatus": "source-isolated-review-pass",
        "eyeComponentAuthority": False,
        "eyesPromotionEligible": False,
        "productionActivation": False,
    }
    monkeypatch.setattr(runtime, "read_candidate", lambda *args, **kwargs: dict(candidate))
    monkeypatch.setattr(runtime, "read_review", lambda *args, **kwargs: dict(review))
    return candidate_dir, source_dir


def test_reviewed_runtime_preserves_whole_vrm_bytes_and_grants_only_iris_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, base_bytes = _base_runtime(tmp_path, monkeypatch)
    candidate_dir, source_dir = _iris_authority(tmp_path, monkeypatch)
    output = tmp_path / "reviewed"

    result = runtime.build_reviewed_runtime(
        base_runtime_dir=base_dir,
        iris_candidate_dir=candidate_dir,
        source_eye_appearance_dir=source_dir,
        bodyrig_revision=REVIEW_REVISION,
        output_dir=output,
    )

    reviewed = output / runtime.OUTPUT_VRM_NAME
    assert reviewed.read_bytes() == base_bytes
    assert result["baseReviewVrmSha256"] == result["reviewedVrmSha256"] == _sha(base_bytes)
    assert result["runtimeBytesUnchanged"] is True
    assert result["sourceEyePixelsUnchanged"] is True
    assert result["embeddedEyeRuntimeStillReviewPending"] is True
    assert result["irisReviewOverlayApplied"] is True
    assert result["irisIdentityIsolated"] is True
    assert result["irisAppearanceStatus"] == "source-isolated-review-pass"
    assert result["eyelashStatus"] == "missing"
    assert result["eyeComponentAuthority"] is False
    assert result["eyesPromotionEligible"] is False
    assert result["productionActivation"] is False


def test_reviewed_runtime_fails_if_output_vrm_changes_after_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, _ = _base_runtime(tmp_path, monkeypatch)
    candidate_dir, source_dir = _iris_authority(tmp_path, monkeypatch)
    output = tmp_path / "reviewed"
    runtime.build_reviewed_runtime(
        base_runtime_dir=base_dir,
        iris_candidate_dir=candidate_dir,
        source_eye_appearance_dir=source_dir,
        bodyrig_revision=REVIEW_REVISION,
        output_dir=output,
    )
    (output / runtime.OUTPUT_VRM_NAME).write_bytes((output / runtime.OUTPUT_VRM_NAME).read_bytes() + b"tamper")
    with pytest.raises(runtime.SourceIrisReviewRuntimeError, match="exact authority: reviewedVrmSha256|VRM bytes differ"):
        runtime.read_reviewed_runtime(
            base_runtime_dir=base_dir,
            iris_candidate_dir=candidate_dir,
            source_eye_appearance_dir=source_dir,
            reviewed_runtime_dir=output,
        )


def test_reviewed_runtime_rejects_iris_from_different_eye_appearance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, _ = _base_runtime(tmp_path, monkeypatch)
    candidate_dir, source_dir = _iris_authority(tmp_path, monkeypatch)
    original = runtime.read_candidate

    def different(*args, **kwargs):
        value = original(*args, **kwargs)
        value["sourceEyeAppearanceReceiptSha256"] = "e" * 64
        return value

    monkeypatch.setattr(runtime, "read_candidate", different)
    with pytest.raises(runtime.SourceIrisReviewRuntimeError, match="different eye appearance authority"):
        runtime.build_reviewed_runtime(
            base_runtime_dir=base_dir,
            iris_candidate_dir=candidate_dir,
            source_eye_appearance_dir=source_dir,
            bodyrig_revision=REVIEW_REVISION,
            output_dir=tmp_path / "reviewed",
        )


def test_reviewed_runtime_rejects_canonical_bake_not_rendered_by_base_vrm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, _ = _base_runtime(tmp_path, monkeypatch)
    candidate_dir, source_dir = _iris_authority(tmp_path, monkeypatch)
    original = runtime.read_candidate

    def different(*args, **kwargs):
        value = original(*args, **kwargs)
        value["sourceCanonicalEyeBakeSha256"] = "f" * 64
        return value

    monkeypatch.setattr(runtime, "read_candidate", different)
    with pytest.raises(runtime.SourceIrisReviewRuntimeError, match="source bake differs"):
        runtime.build_reviewed_runtime(
            base_runtime_dir=base_dir,
            iris_candidate_dir=candidate_dir,
            source_eye_appearance_dir=source_dir,
            bodyrig_revision=REVIEW_REVISION,
            output_dir=tmp_path / "reviewed",
        )


def test_reviewed_runtime_rejects_review_that_claims_eye_component_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir, _ = _base_runtime(tmp_path, monkeypatch)
    candidate_dir, source_dir = _iris_authority(tmp_path, monkeypatch)
    original = runtime.read_review

    def elevated(*args, **kwargs):
        value = original(*args, **kwargs)
        value["eyeComponentAuthority"] = True
        return value

    monkeypatch.setattr(runtime, "read_review", elevated)
    with pytest.raises(runtime.SourceIrisReviewRuntimeError, match="crossed eye-component"):
        runtime.build_reviewed_runtime(
            base_runtime_dir=base_dir,
            iris_candidate_dir=candidate_dir,
            source_eye_appearance_dir=source_dir,
            bodyrig_revision=REVIEW_REVISION,
            output_dir=tmp_path / "reviewed",
        )
