from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig import high_fidelity_face_secondary_preview as preview
from bodyrig.high_fidelity_face_secondary_preview import HighFidelityFaceSecondaryPreviewError


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    prep_dir = tmp_path / "prep"
    runtime_dir = tmp_path / "runtime"
    render_dir = tmp_path / "render"
    prep_dir.mkdir()
    runtime_dir.mkdir()

    runtime_receipt = runtime_dir / "runtime.json"
    review_vrm = runtime_dir / "face-secondary-review.vrm"
    runtime_receipt.write_bytes(b"runtime-receipt-v1")
    review_vrm.write_bytes(b"face-secondary-review-vrm-v1")

    bodyrig_revision = "a" * 40
    body_id = "body-test"
    source_package_sha = "b" * 64
    comparison_package_sha = "c" * 64
    prepared = {
        "format": preview.FORMAT,
        "version": preview.VERSION,
        "bodyrigRevision": bodyrig_revision,
        "canonicalBodyId": body_id,
        "sourcePackageSha256": source_package_sha,
        "sourceRuntimeReceiptSha256": _sha(runtime_receipt.read_bytes()),
        "sourceReviewVrmSha256": _sha(review_vrm.read_bytes()),
        "comparisonPackageSha256": comparison_package_sha,
        "comparisonPackageName": preview.COMPARISON_PACKAGE_NAME,
        "comparisonOnly": True,
        "physicalAcceptanceAuthority": False,
        "humanReviewRequired": True,
        "packagePromotionAuthority": False,
        "productionActivation": False,
        "comparisonPackagePath": str(prep_dir / preview.COMPARISON_PACKAGE_NAME),
        "preparationPath": str(prep_dir / preview.PREPARATION_NAME),
    }
    runtime = {
        "sourcePackageSha256": source_package_sha,
        "canonicalBodyId": body_id,
        "bodyrigRevision": bodyrig_revision,
        "reviewVrmSha256": _sha(review_vrm.read_bytes()),
        "reviewVrmPath": str(review_vrm),
        "receiptPath": str(runtime_receipt),
    }
    monkeypatch.setattr(preview, "read_preparation", lambda _path: dict(prepared))
    monkeypatch.setattr(preview, "read_runtime", lambda _path: dict(runtime))

    snapshots = render_dir / "snapshots"
    snapshots.mkdir(parents=True)
    manifest_items = []
    for name in preview.CANONICAL_VIEWS:
        raw = (name + "-png").encode("ascii")
        path = snapshots / f"{name}.png"
        path.write_bytes(raw)
        manifest_items.append({"view": name, "file": f"{name}.png", "sha256": _sha(raw), "width": 1024, "height": 1024})
    for name in preview.DIAGNOSTIC_VIEWS:
        (snapshots / f"{name}.png").write_bytes((name + "-diagnostic").encode("ascii"))

    _write_json(render_dir / "comparison-authority.json", {
        "format": "bodyrig-fidelity-comparison-authority",
        "version": 1,
        "authority": "validated-package-comparison-only",
        "bodyrig_revision": bodyrig_revision,
        "runtime_manifest_sha256": "d" * 64,
        "package_sha256": comparison_package_sha,
        "physical_acceptance_authority": False,
        "comparison_only": True,
        "production_activation": False,
    })
    _write_json(snapshots / "fidelity-render-set.json", {
        "format": "bodyrig-fidelity-render-set",
        "version": 1,
        "body_id": body_id,
        "package_sha256": comparison_package_sha,
        "semantics": "visual-fidelity-not-identity-verification",
        "snapshots": manifest_items,
    })
    return prep_dir, runtime_dir, render_dir


def test_finalize_and_read_preview_bind_mouth_open_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prep_dir, runtime_dir, render_dir = _evidence(tmp_path, monkeypatch)
    result = preview.finalize_preview(prep_dir, runtime_dir, render_dir)
    assert result["mouthOpenPoseRendered"] is True
    assert set(result["diagnosticViewSha256"]) == set(preview.DIAGNOSTIC_VIEWS)
    assert result["faceSecondaryComponentAuthority"] is False
    assert result["packagePromotionAuthority"] is False
    assert result["productionActivation"] is False

    verified = preview.read_preview(prep_dir, runtime_dir, render_dir)
    assert verified["diagnosticViewSha256"] == result["diagnosticViewSha256"]

    mouth = render_dir / "snapshots" / "mouth-open.png"
    mouth.write_bytes(mouth.read_bytes() + b"tamper")
    with pytest.raises(HighFidelityFaceSecondaryPreviewError, match="stale: diagnosticViewSha256"):
        preview.read_preview(prep_dir, runtime_dir, render_dir)


def test_finalize_is_create_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prep_dir, runtime_dir, render_dir = _evidence(tmp_path, monkeypatch)
    preview.finalize_preview(prep_dir, runtime_dir, render_dir)
    with pytest.raises(HighFidelityFaceSecondaryPreviewError, match="create-only"):
        preview.finalize_preview(prep_dir, runtime_dir, render_dir)


def test_renderer_package_binding_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prep_dir, runtime_dir, render_dir = _evidence(tmp_path, monkeypatch)
    authority_path = render_dir / "comparison-authority.json"
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    authority["package_sha256"] = "e" * 64
    _write_json(authority_path, authority)
    with pytest.raises(HighFidelityFaceSecondaryPreviewError, match="different revision/package"):
        preview.finalize_preview(prep_dir, runtime_dir, render_dir)
