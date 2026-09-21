from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_exavatar_teacher_adapter.py"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("bodyrig_test_exavatar_teacher_adapter_camera", ADAPTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_neutral_camera_manifest_matches_pinned_upstream_rotation_formula() -> None:
    adapter = _load_adapter()
    manifest = adapter._neutral_camera_manifest()

    assert manifest["format"] == "bodyrig-photoreal-exavatar-neutral-camera-manifest"
    assert manifest["version"] == 1
    assert manifest["upstream_commit"] == "d45268730c779fae4118f1a361cf9ff639bc4d1e"
    assert manifest["upstream_script"] == "avatar/main/get_neutral_pose.py"
    assert manifest["view_count"] == 50
    assert len(manifest["views"]) == 50

    first = manifest["views"][0]
    quarter = manifest["views"][12]
    half = manifest["views"][25]
    last = manifest["views"][49]

    assert first["index"] == 0
    assert first["render_relative_path"] == "review/neutral-pose/0.png"
    assert first["upstream_azimuth_radians"] == round(math.pi, 12)
    assert first["upstream_azimuth_degrees"] == 180.0
    assert first["normalized_azimuth_degrees"] == -180.0
    assert first["elevation_radians"] == round(-math.pi / 6.0, 12)
    assert first["elevation_degrees"] == -30.0

    assert quarter["upstream_azimuth_degrees"] == 266.4
    assert quarter["normalized_azimuth_degrees"] == -93.6
    assert half["upstream_azimuth_degrees"] == 360.0
    assert half["normalized_azimuth_degrees"] == 0.0
    assert last["upstream_azimuth_degrees"] == 532.8
    assert last["normalized_azimuth_degrees"] == 172.8


def test_neutral_camera_manifest_refuses_to_machine_label_semantic_views() -> None:
    adapter = _load_adapter()
    manifest = adapter._neutral_camera_manifest()

    assert manifest["semantic_view_labels_machine_assigned"] is False
    assert manifest["human_semantic_alignment_required"] is True
    assert all(item["semantic_view_label"] is None for item in manifest["views"])
    assert manifest["photoreal_acceptance_authority"] is False
    assert manifest["production_activation"] is False


def test_neutral_camera_manifest_digest_is_canonical() -> None:
    adapter = _load_adapter()
    manifest = adapter._neutral_camera_manifest()

    assert manifest["camera_manifest_sha256"] == adapter._digest(
        manifest,
        omit="camera_manifest_sha256",
    )


def test_neutral_camera_manifest_is_written_as_hash_bound_teacher_artifact(tmp_path: Path) -> None:
    adapter = _load_adapter()

    artifact = adapter._write_neutral_camera_manifest(tmp_path)
    path = tmp_path / artifact["relative_path"]
    value = json.loads(path.read_text(encoding="utf-8"))

    assert artifact["kind"] == "neutral-pose-camera-manifest"
    assert artifact["relative_path"] == "review/neutral-pose/cameras.json"
    assert artifact["size_bytes"] == path.stat().st_size
    assert artifact["sha256"] == adapter._file_sha(path)
    assert value["camera_manifest_sha256"] == adapter._digest(
        value,
        omit="camera_manifest_sha256",
    )
