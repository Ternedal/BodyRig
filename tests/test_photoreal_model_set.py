from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig.photoreal_model_set import PhotorealModelSetError, build_model_set


def test_model_set_digest_is_deterministic_and_content_bound(tmp_path: Path) -> None:
    root = tmp_path / "models"
    (root / "identity").mkdir(parents=True)
    (root / "pose").mkdir()
    (root / "identity" / "recognition.onnx").write_bytes(b"identity-v1")
    (root / "pose" / "pose.onnx").write_bytes(b"pose-v1")

    first = build_model_set(root)
    second = build_model_set(root)

    assert first == second
    assert first["file_count"] == 2
    assert len(first["model_set_sha256"]) == 64
    assert [item["path"] for item in first["files"]] == [
        "identity/recognition.onnx",
        "pose/pose.onnx",
    ]
    assert first["build_only"] is True
    assert first["runtime_dependency"] is False
    assert first["production_activation"] is False

    original = first["model_set_sha256"]
    (root / "pose" / "pose.onnx").write_bytes(b"pose-v2")
    changed = build_model_set(root)
    assert changed["model_set_sha256"] != original


def test_model_set_digest_binds_relative_paths_not_absolute_root(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "same.onnx").write_bytes(b"same")
    (right / "same.onnx").write_bytes(b"same")

    assert build_model_set(left)["model_set_sha256"] == build_model_set(right)["model_set_sha256"]


def test_model_set_rejects_empty_root(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(PhotorealModelSetError, match="contains no files"):
        build_model_set(root)


def test_model_set_rejects_empty_asset(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    (root / "empty.onnx").write_bytes(b"")
    with pytest.raises(PhotorealModelSetError, match="asset is empty"):
        build_model_set(root)
