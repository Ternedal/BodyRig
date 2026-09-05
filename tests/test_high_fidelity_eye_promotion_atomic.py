from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.high_fidelity_eye_promotion_atomic as atomic


def _common(tmp_path: Path) -> dict[str, object]:
    target = tmp_path / "target.mrbody"
    target.write_bytes(b"target")
    return {
        "candidate_package_path": tmp_path / "candidate.mrbody",
        "target_package_path": target,
        "base_runtime_dir": tmp_path,
        "iris_candidate_dir": tmp_path,
        "source_eye_appearance_dir": tmp_path,
        "reviewed_runtime_dir": tmp_path,
        "eye_runtime_dir": tmp_path,
        "bridge_script_sha256": "a" * 64,
    }


def _stub_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_root: Path) -> None:
    receipt = tmp_path / "source-eye-runtime-rebuild.json"
    receipt.write_text("{}\n", encoding="utf-8")
    eye_vrm = tmp_path / "source-eye-review.vrm"
    eye_vrm.write_bytes(b"eye")
    monkeypatch.setattr(
        atomic.core,
        "_validated_rebuild",
        lambda *args, **kwargs: ({}, eye_vrm, receipt, "b" * 64),
    )
    monkeypatch.setattr(atomic.core, "_sha256_file", lambda path: "c" * 64)
    monkeypatch.setattr(atomic.core, "_promotion_root", lambda *args, **kwargs: final_root)


def test_atomic_entrypoint_removes_new_final_authority_when_core_revalidation_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    final_root = tmp_path / "final"
    _stub_authority(tmp_path, monkeypatch, final_root)

    def failing_write(*args, **kwargs):
        final_root.mkdir()
        (final_root / "promoted.mrbody").write_bytes(b"invalid-final")
        raise atomic.HighFidelityEyePromotionError("post-write revalidation failed")

    monkeypatch.setattr(atomic.core, "write_promotion", failing_write)

    with pytest.raises(atomic.HighFidelityEyePromotionError, match="post-write revalidation failed"):
        atomic.write_promotion(
            "hfpreview-" + "1" * 32,
            promotion_bodyrig_revision="d" * 40,
            **_common(tmp_path),
        )

    assert not final_root.exists()


def test_atomic_entrypoint_never_removes_preexisting_create_only_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    final_root = tmp_path / "final"
    final_root.mkdir()
    marker = final_root / "keep"
    marker.write_text("existing-authority", encoding="utf-8")
    _stub_authority(tmp_path, monkeypatch, final_root)

    def failing_write(*args, **kwargs):
        raise atomic.HighFidelityEyePromotionError("refusing to overwrite existing authority")

    monkeypatch.setattr(atomic.core, "write_promotion", failing_write)

    with pytest.raises(atomic.HighFidelityEyePromotionError, match="refusing to overwrite"):
        atomic.write_promotion(
            "hfpreview-" + "2" * 32,
            promotion_bodyrig_revision="d" * 40,
            **_common(tmp_path),
        )

    assert marker.read_text(encoding="utf-8") == "existing-authority"


def test_atomic_entrypoint_preserves_verified_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    final_root = tmp_path / "final"
    _stub_authority(tmp_path, monkeypatch, final_root)

    expected = {"packagePath": str(final_root / "promoted.mrbody"), "productionActivation": False}

    def successful_write(*args, **kwargs):
        final_root.mkdir()
        (final_root / "promoted.mrbody").write_bytes(b"verified")
        return expected

    monkeypatch.setattr(atomic.core, "write_promotion", successful_write)

    value = atomic.write_promotion(
        "hfpreview-" + "3" * 32,
        promotion_bodyrig_revision="d" * 40,
        **_common(tmp_path),
    )

    assert value == expected
    assert (final_root / "promoted.mrbody").read_bytes() == b"verified"
