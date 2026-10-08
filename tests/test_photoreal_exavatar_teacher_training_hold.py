from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_exavatar_teacher_adapter.py"


def _adapter():
    spec = importlib.util.spec_from_file_location(
        "bodyrig_exavatar_teacher_spatial_safety_test", ADAPTER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prepare(
    tmp_path: Path, *, spatial: bool = True,
) -> tuple[Path, dict[str, object]]:
    dataset = tmp_path / "dataset" / "bodyrig-42"
    dataset.mkdir(parents=True)
    source_key = "scene:807:test-video"
    source_sha = "1" * 64
    source_map = {
        "format": "bodyrig-photoreal-exavatar-source-map",
        "normalization_action": (
            "exact-authorized-deprojection" if spatial else "preserve-flat-mono-video"
        ),
        "projection": "equi" if spatial else "flat",
        "stereo_layout": "left-right" if spatial else "mono",
        "decode_mode": "spatial-deprojection-required" if spatial else "rectilinear-mono",
        "source_key": source_key,
        "frames": [{
            "eye": "left" if spatial else "mono",
            "source_frame_sha256": source_sha,
            "camera": {"yaw_degrees": 0} if spatial else None,
        }],
    }
    receipt = {
        "frames": [{
            "eye": "left" if spatial else "mono",
            "source_frame_sha256": source_sha,
            "camera": {"yaw_degrees": 0} if spatial else None,
        }]
    }
    (dataset / "bodyrig-source-map.json").write_text(json.dumps(source_map), encoding="utf-8")
    (dataset / "materialization-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    request = {"training_sources": [{"source_key": source_key, "projection": source_map["projection"]}]}
    return dataset, request


def test_spatial_training_is_refused_even_when_receipt_exists(tmp_path: Path) -> None:
    dataset, request = _prepare(tmp_path, spatial=True)
    adapter = _adapter()
    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="NO-GO: spatial/VR"):
        adapter._enforce_spatial_teacher_no_go(dataset, request)


def test_flat_mono_not_blocked_by_spatial_policy(tmp_path: Path) -> None:
    dataset, request = _prepare(tmp_path, spatial=False)
    _adapter()._enforce_spatial_teacher_no_go(dataset, request)


def test_missing_source_map_fails_closed(tmp_path: Path) -> None:
    dataset, request = _prepare(tmp_path)
    (dataset / "bodyrig-source-map.json").unlink()
    with pytest.raises(_adapter().ExAvatarTeacherAdapterError, match="NO-GO"):
        _adapter()._enforce_spatial_teacher_no_go(dataset, request)


def test_camera_metadata_cannot_be_disguised_as_flat_mono(tmp_path: Path) -> None:
    dataset, request = _prepare(tmp_path, spatial=False)
    source_map_path = dataset / "bodyrig-source-map.json"
    source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
    source_map["frames"][0]["camera"] = {"focal": [2000, 2000]}
    source_map_path.write_text(json.dumps(source_map), encoding="utf-8")
    with pytest.raises(_adapter().ExAvatarTeacherAdapterError, match="NO-GO"):
        _adapter()._enforce_spatial_teacher_no_go(dataset, request)


def test_spatial_requested_source_is_blocked_even_with_flat_marker(tmp_path: Path) -> None:
    dataset, request = _prepare(tmp_path, spatial=False)
    request["training_sources"][0]["projection"] = "mshp"
    with pytest.raises(_adapter().ExAvatarTeacherAdapterError, match="NO-GO"):
        _adapter()._enforce_spatial_teacher_no_go(dataset, request)


def test_teacher_entrypoint_refuses_spatial_before_preprocess_or_gpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    dataset, _ = _prepare(tmp_path, spatial=True)
    adapter = _adapter()
    root = tmp_path / "workspace"
    output = tmp_path / "empty-output"
    root.mkdir()
    output.mkdir()
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps({"request": "placeholder"}), encoding="utf-8")

    monkeypatch.setattr(adapter, "_validate_request", lambda *args: None)
    monkeypatch.setattr(adapter, "_validate_workspace", lambda *args: ({}, dataset))

    def unexpected(*args, **kwargs):
        raise AssertionError("preprocess, training or patching must not be reached")
    monkeypatch.setattr(adapter, "_validate_preprocess", unexpected)
    monkeypatch.setattr(adapter, "_run", unexpected)

    rc = adapter.main([
        "--workspace-root", str(root),
        "--runtime-preflight", str(tmp_path / "not-needed.json"),
        "--bodyrig-request", str(request_path),
        "--bodyrig-output", str(output),
        "--bodyrig-adapter", "exavatar-benchmark",
        "--bodyrig-revision", "testing",
        "--bodyrig-upstream-commit", adapter.UPSTREAM_COMMIT,
    ])
    assert rc == 1
    assert "NO-GO: spatial/VR" in capsys.readouterr().err
    assert list(output.iterdir()) == []
