from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.source_hair_eye_preview_runtime as preview


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_WRAPPER = ROOT / "run-source-hair-eye-windows-preview.ps1"
FIDELITY_WRAPPER = ROOT / "run-fidelity-windows-render-probe.ps1"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_package(path: Path, bodyprint: bytes) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bodyprint.json", bodyprint)
    return path


def _source_receipt(*, package_sha: str, review_vrm_sha: str) -> dict[str, object]:
    return {
        "format": "bodyrig-source-hair-eye-review-runtime",
        "version": 1,
        "bodyrigRevision": "a" * 40,
        "bridgeScriptSha256": "b" * 64,
        "bodyId": "test-body",
        "packageSha256": package_sha,
        "baseAvatarVrmSha256": "c" * 64,
        "sourceHairBodyBindingSha256": "d" * 64,
        "hairCandidateReceiptSha256": "e" * 64,
        "eyeComponentReceiptSha256": "f" * 64,
        "eyeAppearanceReceiptSha256": "1" * 64,
        "reviewVrmSha256": review_vrm_sha,
        "bridgeResultSha256": "2" * 64,
        "targetModelFamily": "female",
        "hairMeshIndex": 1,
        "eyeMeshIndex": 2,
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 13,
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


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, bytes, bytes]:
    bodyprint = b'{"format":"modelrig-bodyprint","version":1}\n'
    package = _write_package(tmp_path / "candidate.mrbody", bodyprint)
    review_vrm = b"review-vrm-with-source-hair-eyes-and-cornea"
    review_root = tmp_path / "review"
    review_root.mkdir()
    (review_root / "source-hair-eye-review.vrm").write_bytes(review_vrm)
    receipt = _source_receipt(package_sha=_sha(package.read_bytes()), review_vrm_sha=_sha(review_vrm))
    (review_root / "source-hair-eye-review-runtime.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    monkeypatch.setattr(
        preview,
        "validate_package",
        lambda path: SimpleNamespace(manifest={"id": "test-body", "name": "Test Body"}),
    )
    monkeypatch.setattr(preview, "validate_vrm1", lambda raw: None)
    return package, review_root, review_vrm, bodyprint


def test_materialize_binds_exact_review_avatar_and_stays_review_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, review_root, review_vrm, bodyprint = _fixture(tmp_path, monkeypatch)
    destination = tmp_path / "preview-runtime"

    result = preview.materialize(
        package_path=package,
        review_runtime_dir=review_root,
        destination=destination,
    )

    assert result["ok"] is True
    assert result["review_vrm_sha256"] == _sha(review_vrm)
    assert result["comparison_only"] is True
    assert result["production_activation"] is False
    assert (destination / "avatar.vrm").read_bytes() == review_vrm
    assert (destination / "bodyprint.json").read_bytes() == bodyprint

    manifest = json.loads((destination / "runtime-manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "format": "bodyrig-runtime-assets",
        "version": 1,
        "body_id": "test-body",
        "body_name": "Test Body",
        "package_sha256": _sha(package.read_bytes()),
        "avatar": "avatar.vrm",
        "avatar_sha256": _sha(review_vrm),
        "bodyprint": "bodyprint.json",
        "bodyprint_sha256": _sha(bodyprint),
        "payloads": ["avatar.vrm", "bodyprint.json"],
    }

    authority = json.loads((destination / "review-runtime-authority.json").read_text(encoding="utf-8"))
    assert authority["format"] == "bodyrig-source-hair-eye-preview-runtime"
    assert authority["version"] == 1
    assert authority["packageSha256"] == _sha(package.read_bytes())
    assert authority["reviewVrmSha256"] == _sha(review_vrm)
    assert authority["bodyprintSha256"] == _sha(bodyprint)
    assert authority["runtimeManifestSha256"] == _sha((destination / "runtime-manifest.json").read_bytes())
    assert authority["sourceHairRuntimeApplied"] is True
    assert authority["sourceEyeSurfaceApplied"] is True
    assert authority["cornealMaterialStatus"] == "runtime-applied"
    assert authority["comparisonOnly"] is True
    assert authority["humanReviewRequired"] is True
    assert authority["physicalAcceptanceAuthority"] is False
    assert authority["productionActivation"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sourceHairRuntimeApplied", False),
        ("sourceEyeSurfaceApplied", False),
        ("cornealMaterialStatus", "missing"),
        ("productionActivation", True),
    ],
)
def test_materialize_rejects_incomplete_or_activating_source_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    package, review_root, review_vrm, _ = _fixture(tmp_path, monkeypatch)
    receipt_path = review_root / "source-hair-eye-review-runtime.json"
    receipt = _source_receipt(package_sha=_sha(package.read_bytes()), review_vrm_sha=_sha(review_vrm))
    receipt[field] = value
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(
        preview.SourceHairEyePreviewRuntimeError,
        match="non-activating review authority",
    ):
        preview.materialize(
            package_path=package,
            review_runtime_dir=review_root,
            destination=tmp_path / "preview-runtime",
        )

    assert not (tmp_path / "preview-runtime").exists()


def test_windows_preview_operator_requires_exact_hair_eye_avatar_and_four_views() -> None:
    wrapper = PREVIEW_WRAPPER.read_text(encoding="utf-8")

    for marker in (
        "bodyrig.source_hair_eye_preview_runtime",
        'ReviewRuntimeDir = $previewRuntime',
        'bodyrig-source-hair-eye-preview-runtime',
        'reviewVrmSha256',
        'sourceHairRuntimeApplied',
        'sourceEyeSurfaceApplied',
        'cornealMaterialStatus',
        'physicalAcceptanceAuthority -ne $false',
        'productionActivation -ne $false',
        "front-full,three-quarter-full,side-full,face-front",
        "source-hair-eye-review-runtime",
        "review_avatar_sha256",
        "BodyRig source hair + eye Windows preview: READY",
    ):
        assert marker in wrapper


def test_fidelity_renderer_preview_mode_binds_probe_to_exact_review_vrm() -> None:
    wrapper = FIDELITY_WRAPPER.read_text(encoding="utf-8")

    for marker in (
        'Pass exactly one of -AcceptanceDir, -PackagePath or -ReviewRuntimeDir',
        'review-runtime-authority.json',
        'bodyrig-source-hair-eye-preview-runtime',
        'sourceHairRuntimeApplied',
        'sourceEyeSurfaceApplied',
        'cornealMaterialStatus',
        'physicalAcceptanceAuthority',
        'productionActivation',
        'reviewVrmSha256',
        'runtime.avatar_sha256',
        'probe.avatar_sha256',
        'source-hair-eye-review-runtime',
    ):
        assert marker in wrapper
