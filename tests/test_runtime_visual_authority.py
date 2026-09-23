from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.runtime_visual_authority as visual


REVISION = "a" * 40
BODY_ID = "bodyid-test"
PACKAGE_SHA = "b" * 64


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _acceptance(root: Path, avatar_bytes: bytes = b"photoreal-avatar") -> tuple[Path, str]:
    runtime = root / "runtime"
    runtime.mkdir(parents=True)
    avatar = runtime / "avatar.vrm"
    avatar.write_bytes(avatar_bytes)
    avatar_sha = _sha(avatar)
    manifest = runtime / "runtime-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "format": "bodyrig-runtime-assets",
                "version": 1,
                "body_id": BODY_ID,
                "package_sha256": PACKAGE_SHA,
                "avatar_sha256": avatar_sha,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    acceptance = root / "bodyrig-acceptance.json"
    acceptance.write_text(
        json.dumps(
            {
                "format": "bodyrig-rig-acceptance",
                "version": 1,
                "bodyrig_revision": REVISION,
                "package": {
                    "body_id": BODY_ID,
                    "package_sha256": PACKAGE_SHA,
                },
                "runtime": {"manifest_sha256": _sha(manifest)},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return acceptance, avatar_sha


def _p3_receipt(path: Path, avatar_sha: str) -> dict:
    value = {
        "format": "bodyrig-photoreal-p3-physical-runtime-review",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-pass",
        "runtime_review_status": "pass",
        "runtime_acceptance_authority": True,
        "photoreal_acceptance_authority": True,
        "physical_device_review_complete": True,
        "production_activation": False,
        "student_artifacts": [
            {"relative_path": "student/avatar.vrm", "sha256": avatar_sha}
        ],
        "installed_student_artifacts": [
            {"relative_path": "student/avatar.vrm", "sha256": avatar_sha}
        ],
        "p3_physical_runtime_review_sha256": "c" * 64,
    }
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return value


def test_promotion_binds_exact_runtime_avatar_to_p3_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, avatar_sha = _acceptance(tmp_path)
    p3 = _p3_receipt(tmp_path / "p3.json", avatar_sha)
    monkeypatch.setattr(visual, "validate_physical_runtime_review_receipt", lambda value: dict(value))

    authority = visual.promote_runtime_visual_authority(tmp_path, tmp_path / "p3.json")

    assert authority["avatar_sha256"] == avatar_sha
    assert authority["renderer_visualization_authorized"] is True
    assert authority["production_activation"] is False
    assert visual.validate_runtime_visual_authority(tmp_path)["avatar_sha256"] == avatar_sha
    assert p3["photoreal_acceptance_authority"] is True


def test_promotion_rejects_p3_pass_for_different_avatar_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _acceptance(tmp_path)
    _p3_receipt(tmp_path / "p3.json", "d" * 64)
    monkeypatch.setattr(visual, "validate_physical_runtime_review_receipt", lambda value: dict(value))

    with pytest.raises(
        visual.RuntimeVisualAuthorityError,
        match="different avatar bytes",
    ):
        visual.promote_runtime_visual_authority(tmp_path, tmp_path / "p3.json")


def test_authority_rejects_runtime_avatar_mutation_after_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, avatar_sha = _acceptance(tmp_path)
    _p3_receipt(tmp_path / "p3.json", avatar_sha)
    monkeypatch.setattr(visual, "validate_physical_runtime_review_receipt", lambda value: dict(value))
    visual.promote_runtime_visual_authority(tmp_path, tmp_path / "p3.json")

    (tmp_path / "runtime" / "avatar.vrm").write_bytes(b"mutated")

    with pytest.raises(
        visual.RuntimeVisualAuthorityError,
        match="runtime avatar bytes differ",
    ):
        visual.validate_runtime_visual_authority(tmp_path)


def test_authority_is_create_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, avatar_sha = _acceptance(tmp_path)
    _p3_receipt(tmp_path / "p3.json", avatar_sha)
    monkeypatch.setattr(visual, "validate_physical_runtime_review_receipt", lambda value: dict(value))
    visual.promote_runtime_visual_authority(tmp_path, tmp_path / "p3.json")

    with pytest.raises(
        visual.RuntimeVisualAuthorityError,
        match="already exists",
    ):
        visual.promote_runtime_visual_authority(tmp_path, tmp_path / "p3.json")
