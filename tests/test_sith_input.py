from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from bodyrig.sith_input import SithInputError, load_captured_identity, stage_sith_input


def _png(width: int = 1280, height: int = 1920, tail: bytes = b"fixture") -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + tail


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    workspace = tmp_path / "identity-workspace"
    capture = workspace / "identity-capture"
    capture.mkdir(parents=True)
    rgb = capture / "primary-rgb.png"
    rgba = capture / "primary-rgba.png"
    rgb.write_bytes(_png(tail=b"rgb"))
    rgba.write_bytes(_png(tail=b"rgba"))
    manifest = {
        "format": "bodyrig-private-identity-capture",
        "version": 1,
        "adapter": "opencv-identity-rgba",
        "revision": "1",
        "subject_track_id": "s00-t7",
        "primary": {
            "rgb": "primary-rgb.png",
            "rgba": "primary-rgba.png",
            "rgb_sha256": hashlib.sha256(rgb.read_bytes()).hexdigest(),
            "rgba_sha256": hashlib.sha256(rgba.read_bytes()).hexdigest(),
            "source_index": 0,
            "time_seconds": 1.25,
            "foreground_fraction": 0.42,
        },
    }
    capture_json = capture / "capture.json"
    capture_json.write_text(json.dumps(manifest), encoding="utf-8")
    return workspace, capture_json, rgb, rgba


def test_load_captured_identity_rehashes_private_capture(tmp_path: Path):
    workspace, capture_json, rgb, rgba = _workspace(tmp_path)
    loaded = load_captured_identity(workspace)

    assert loaded.rgb_path == rgb.resolve()
    assert loaded.rgba_path == rgba.resolve()
    assert loaded.rgba_size == (1280, 1920)
    assert loaded.capture_manifest_sha256 == hashlib.sha256(capture_json.read_bytes()).hexdigest()


def test_stage_sith_input_uses_canonical_single_image_and_upstream_profile(tmp_path: Path):
    workspace, _, _, rgba = _workspace(tmp_path)
    stage, manifest = stage_sith_input(workspace)

    assert (stage / "rgba" / "000.png").read_bytes() == rgba.read_bytes()
    assert (stage / "images").is_dir()
    assert (stage / "smplx").is_dir()
    assert (stage / "back_images").is_dir()
    assert (stage / "meshes").is_dir()
    assert manifest["centralize"] == {"size": 1024, "ratio": 0.85}
    assert manifest["openpose"]["model"] == "BODY_25"
    assert manifest["openpose"]["number_people_max"] == 1
    assert manifest["openpose"]["hand"] is True
    assert manifest["openpose"]["face"] is True

    with pytest.raises(SithInputError, match="already exists"):
        stage_sith_input(workspace)


def test_sith_input_rejects_capture_hash_substitution(tmp_path: Path):
    workspace, _, _, rgba = _workspace(tmp_path)
    rgba.write_bytes(rgba.read_bytes() + b"tampered")

    with pytest.raises(SithInputError, match="RGBA SHA-256 mismatch"):
        load_captured_identity(workspace)


def test_sith_input_rejects_path_traversal_and_unknown_capture_adapter(tmp_path: Path):
    workspace, capture_json, _, _ = _workspace(tmp_path)
    manifest = json.loads(capture_json.read_text(encoding="utf-8"))
    manifest["primary"]["rgba"] = "../primary-rgba.png"
    capture_json.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SithInputError, match="leaf filename"):
        load_captured_identity(workspace)

    workspace2, capture_json2, _, _ = _workspace(tmp_path / "other")
    manifest2 = json.loads(capture_json2.read_text(encoding="utf-8"))
    manifest2["adapter"] = "untrusted-capture"
    capture_json2.write_text(json.dumps(manifest2), encoding="utf-8")
    with pytest.raises(SithInputError, match="requires built-in"):
        load_captured_identity(workspace2)


def test_sith_input_rejects_non_png_even_with_matching_hash(tmp_path: Path):
    workspace, capture_json, _, rgba = _workspace(tmp_path)
    rgba.write_bytes(b"not-a-png")
    manifest = json.loads(capture_json.read_text(encoding="utf-8"))
    manifest["primary"]["rgba_sha256"] = hashlib.sha256(rgba.read_bytes()).hexdigest()
    capture_json.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SithInputError, match="not a canonical PNG"):
        load_captured_identity(workspace)
