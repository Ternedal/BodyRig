from __future__ import annotations

import hashlib
import json

import pytest

import bodyrig.face_secondary_hair_eye_review as review
from bodyrig.bridges.sith_pbr_material import _read_glb, _write_glb
from bodyrig.high_fidelity_face_secondary_runtime import NODE_NAME


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_vrm() -> bytes:
    binary = b"hair-eye-review-base"
    document = {
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [],
        "accessors": [],
        "materials": [{"name": "ExistingBodyMaterial"}],
        "meshes": [{"name": "ExistingBodyMesh", "primitives": []}],
        "nodes": [
            {"name": "smplx_head", "translation": [0.0, 1.60, 0.0]},
            {"name": "smplx_jaw", "translation": [0.0, 1.51, 0.035]},
            {"name": "smplx_left_eye", "translation": [0.031, 1.64, 0.075]},
            {"name": "smplx_right_eye", "translation": [-0.031, 1.64, 0.075]},
            {"name": "BodyRigSourceHairReview", "mesh": 0, "skin": 0},
            {"name": "BodyRigSourceEyeReview", "mesh": 0, "skin": 0},
        ],
        "skins": [{"joints": [0, 1, 2, 3]}],
        "scenes": [{"nodes": [0, 1, 2, 3, 4, 5]}],
        "extras": {
            "bodyrig": {
                "hairReviewRuntime": {
                    "format": "bodyrig-source-hair-review-runtime-metadata",
                    "version": 1,
                    "comparisonOnly": True,
                    "humanReviewRequired": True,
                    "hairComponentAuthority": False,
                    "productionActivation": False,
                },
                "eyeReviewRuntime": {
                    "format": "bodyrig-source-eye-review-runtime-metadata",
                    "version": 1,
                    "eyeComponentReceiptSha256": "1" * 64,
                    "eyeAppearanceReceiptSha256": "2" * 64,
                    "canonicalEyeBakeSha256": "3" * 64,
                    "targetModelFamily": "female",
                    "leftEyeJointIndex": 2,
                    "rightEyeJointIndex": 3,
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
                },
                "appearanceTransfer": {
                    "activeBaseColorSha256": "9" * 64,
                    "policyRevision": "test-promoted-appearance-v1",
                },
                "keepMe": {"authority": "hair-eye-source"},
            }
        },
    }
    return _write_glb(document, binary)


def _source_runtime(tmp_path, *, package_sha: str, body_id: str = "body-1", revision: str = "a" * 40):
    root = tmp_path / "hair-eye-runtime"
    root.mkdir()
    vrm = _source_vrm()
    (root / review.SOURCE_VRM_NAME).write_bytes(vrm)
    receipt = {
        "format": review.SOURCE_FORMAT,
        "version": 1,
        "bodyrigRevision": revision,
        "bridgeScriptSha256": "0" * 64,
        "bodyId": body_id,
        "packageSha256": package_sha,
        "baseAvatarVrmSha256": "1" * 64,
        "sourceHairBodyBindingSha256": "2" * 64,
        "hairCandidateReceiptSha256": "3" * 64,
        "eyeComponentReceiptSha256": "4" * 64,
        "eyeAppearanceReceiptSha256": "5" * 64,
        "reviewVrmSha256": _sha(vrm),
        "bridgeResultSha256": "6" * 64,
        "targetModelFamily": "female",
        "hairMeshIndex": 1,
        "eyeMeshIndex": 2,
        "leftEyeFaceCount": 32,
        "rightEyeFaceCount": 32,
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
    path = root / review.SOURCE_RECEIPT_NAME
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return root, receipt, vrm


def test_build_adds_face_secondary_without_promoting_hair_eyes_or_package(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"current-floor-package")
    package_sha = _sha(package.read_bytes())
    monkeypatch.setattr(review, "_package_authority", lambda _path: ("body-1", package_sha))
    source_root, source_receipt, source_vrm = _source_runtime(tmp_path, package_sha=package_sha)

    output = tmp_path / "face-secondary"
    result = review.build(package, source_root, output, bodyrig_revision="a" * 40)
    reread = review.read_runtime(output)

    assert reread["reviewVrmSha256"] == result["reviewVrmSha256"]
    assert result["sourceHairPreserved"] is True
    assert result["sourceEyeSurfacePreserved"] is True
    assert result["faceSecondaryComponentAuthority"] is False
    assert result["packageMutationPerformed"] is False
    assert result["productionActivation"] is False
    assert package.read_bytes() == b"current-floor-package"
    assert result["sourceHairEyeReviewVrmSha256"] == _sha(source_vrm)

    document, _binary = _read_glb((output / review.VRM_NAME).read_bytes())
    bodyrig = document["extras"]["bodyrig"]
    assert bodyrig["keepMe"] == {"authority": "hair-eye-source"}
    assert bodyrig["appearanceTransfer"] == {
        "activeBaseColorSha256": "9" * 64,
        "policyRevision": "test-promoted-appearance-v1",
    }
    assert bodyrig["hairReviewRuntime"]["hairComponentAuthority"] is False
    assert bodyrig["eyeReviewRuntime"]["eyeComponentAuthority"] is False
    embedded = bodyrig[review.EMBEDDED_KEY]
    assert embedded["faceSecondaryComponentAuthority"] is False
    assert embedded["packageMutationPerformed"] is False
    assert embedded["generativeIdentitySynthesis"] is False
    names = {item.get("name") for item in document["nodes"] if isinstance(item, dict)}
    assert "BodyRigSourceHairReview" in names
    assert "BodyRigSourceEyeReview" in names
    assert NODE_NAME in names
    assert source_receipt["reviewVrmSha256"] == _sha(source_vrm)


def test_build_rejects_runtime_for_different_package_bytes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"package-a")
    monkeypatch.setattr(review, "_package_authority", lambda _path: ("body-1", _sha(b"package-a")))
    source_root, _receipt, _vrm = _source_runtime(tmp_path, package_sha=_sha(b"package-b"))

    with pytest.raises(review.FaceSecondaryHairEyeReviewError, match="different body/package bytes"):
        review.build(package, source_root, tmp_path / "out", bodyrig_revision="a" * 40)


def test_build_rejects_promoted_or_non_review_eye_boundary(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"package")
    package_sha = _sha(package.read_bytes())
    monkeypatch.setattr(review, "_package_authority", lambda _path: ("body-1", package_sha))
    source_root, receipt, _vrm = _source_runtime(tmp_path, package_sha=package_sha)
    receipt["eyeComponentAuthority"] = True
    (source_root / review.SOURCE_RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(review.FaceSecondaryHairEyeReviewError, match="review-only authority boundary"):
        review.build(package, source_root, tmp_path / "out", bodyrig_revision="a" * 40)


def test_runtime_detects_review_vrm_tamper(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"package")
    package_sha = _sha(package.read_bytes())
    monkeypatch.setattr(review, "_package_authority", lambda _path: ("body-1", package_sha))
    source_root, _receipt, _vrm = _source_runtime(tmp_path, package_sha=package_sha)
    output = tmp_path / "out"
    review.build(package, source_root, output, bodyrig_revision="a" * 40)
    (output / review.VRM_NAME).write_bytes((output / review.VRM_NAME).read_bytes() + b"tamper")

    with pytest.raises(review.FaceSecondaryHairEyeReviewError, match="bytes changed"):
        review.read_runtime(output)


def test_build_rejects_hair_eye_runtime_that_lost_promoted_appearance_authority(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"package")
    package_sha = _sha(package.read_bytes())
    monkeypatch.setattr(review, "_package_authority", lambda _path: ("body-1", package_sha))
    source_root, receipt, _vrm = _source_runtime(tmp_path, package_sha=package_sha)
    vrm_path = source_root / review.SOURCE_VRM_NAME
    document, binary = _read_glb(vrm_path.read_bytes())
    del document["extras"]["bodyrig"]["appearanceTransfer"]
    broken = _write_glb(document, binary)
    vrm_path.write_bytes(broken)
    receipt["reviewVrmSha256"] = _sha(broken)
    (source_root / review.SOURCE_RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(review.FaceSecondaryHairEyeReviewError, match="appearanceTransfer authority required by HFN"):
        review.build(package, source_root, tmp_path / "out-missing-appearance", bodyrig_revision="a" * 40)
