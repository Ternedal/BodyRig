from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig.photoreal_model_set import build_model_set


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_reference_vision_adapter.py"
SPEC = importlib.util.spec_from_file_location("bodyrig_photoreal_reference_vision_adapter_test", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


def _model_root(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    insight = root / "insightface"
    configs = root / "configs"
    weights = root / "weights"
    insight.mkdir(parents=True)
    configs.mkdir()
    weights.mkdir()
    (insight / "buffalo-l-placeholder.bin").write_bytes(b"face-model")
    (configs / "pose.py").write_text("model = {}\n", encoding="utf-8")
    (configs / "det.py").write_text("model = {}\n", encoding="utf-8")
    (weights / "pose.pth").write_bytes(b"pose-weights")
    (weights / "det.pth").write_bytes(b"det-weights")
    (root / "bodyrig-reference-vision-v1.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-photoreal-reference-vision-models",
                "version": 1,
                "insightface_root": "insightface",
                "insightface_name": "buffalo_l",
                "mmpose_pose_config": "configs/pose.py",
                "mmpose_pose_weights": "weights/pose.pth",
                "mmdet_config": "configs/det.py",
                "mmdet_weights": "weights/det.pth",
                "identity_embedding_dimension": 512,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


def test_adapter_module_imports_without_heavy_vision_dependencies() -> None:
    assert adapter.ADAPTER_NAME == "bodyrig-reference-vision-v1"
    assert len(adapter._self_revision()) == 64


def test_bbox_accepts_numpy_style_tolist_objects() -> None:
    class ArrayLike:
        def tolist(self):
            return [[1.0, 2.0, 11.0, 22.0]]

    assert adapter._bbox(ArrayLike()) == (1.0, 2.0, 11.0, 22.0)


def test_write_result_requires_precreated_empty_bodyrig_output(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    adapter._write_result(adapter.FRAME_REQUEST, {"ok": True}, output)
    assert json.loads((output / "observations.json").read_text(encoding="utf-8")) == {"ok": True}

    with pytest.raises(adapter.ReferenceVisionError, match="must be empty"):
        adapter._write_result(adapter.FRAME_REQUEST, {"ok": True}, output)


def test_adapter_recomputes_exact_model_set_before_loading_models(tmp_path: Path) -> None:
    model_root = _model_root(tmp_path)
    model_set = build_model_set(model_root)
    revision = adapter._self_revision()
    request = {
        "format": "bodyrig-photoreal-frame-analyzer-request",
        "version": 1,
        "adapter": adapter.ADAPTER_NAME,
        "revision": revision,
        "model_set_sha256": model_set["model_set_sha256"],
    }
    args = SimpleNamespace(
        bodyrig_adapter=adapter.ADAPTER_NAME,
        bodyrig_revision=revision,
        bodyrig_model_set_sha256=model_set["model_set_sha256"],
    )

    manifest = adapter._verify_provenance(args, request, model_root)
    assert manifest.identity_embedding_dimension == 512
    assert manifest.insightface_name == "buffalo_l"

    (model_root / "weights" / "pose.pth").write_bytes(b"changed")
    with pytest.raises(adapter.ReferenceVisionError, match="do not match pinned model-set"):
        adapter._verify_provenance(args, request, model_root)


def test_adapter_rejects_request_for_other_exact_adapter_revision(tmp_path: Path) -> None:
    model_root = _model_root(tmp_path)
    model_set = build_model_set(model_root)
    request = {
        "format": "bodyrig-photoreal-frame-analyzer-request",
        "version": 1,
        "adapter": adapter.ADAPTER_NAME,
        "revision": "0" * 64,
        "model_set_sha256": model_set["model_set_sha256"],
    }
    args = SimpleNamespace(
        bodyrig_adapter=adapter.ADAPTER_NAME,
        bodyrig_revision=adapter._self_revision(),
        bodyrig_model_set_sha256=model_set["model_set_sha256"],
    )
    with pytest.raises(adapter.ReferenceVisionError, match="exact adapter bytes"):
        adapter._verify_provenance(args, request, model_root)


def test_frame_analyzer_routes_equi_through_unique_deprojected_viewports(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace(embedding_dimension=512)
    raw_image = object()
    authority = {"format": "bodyrig-spherical-v2-projection-authority", "version": 1}
    request = {
        "performer_id": "42",
        "sources": [
            {
                "source_key": "scene:s1:E:/vr.mp4",
                "source_sha256": "a" * 64,
                "kind": "video",
                "projection": "equi",
                "projection_authority": authority,
                "samples": [{"timestamp_seconds": 1.0, "eye": "left"}],
            }
        ],
    }
    args = SimpleNamespace(
        bodyrig_adapter=adapter.ADAPTER_NAME,
        bodyrig_revision="r1",
        bodyrig_model_set_sha256="b" * 64,
    )
    monkeypatch.setattr(adapter, "_read_sample", lambda *_args: (raw_image, True))
    seen_authority = []

    def deproject(_runtime, image, projection_authority):
        assert image is raw_image
        seen_authority.append(projection_authority)
        return [("v00", object()), ("v01", object())]

    def candidate_rows(_runtime, _image, *, base, candidate_prefix=""):
        return [{**base, "candidate_id": f"{candidate_prefix}person-000"}]

    monkeypatch.setattr(adapter, "deproject_equirectangular_views", deproject)
    monkeypatch.setattr(adapter, "_candidate_rows", candidate_rows)
    result = adapter._frame_result(runtime, request, args)

    assert seen_authority == [authority]
    assert [row["candidate_id"] for row in result["observations"]] == ["v00-person-000", "v01-person-000"]
    assert all(row["projection"] == "equi" for row in result["observations"])


def test_spatial_identity_bootstrap_remains_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "_read_sample", lambda *_args: (object(), True))
    with pytest.raises(adapter.ReferenceVisionError, match="cannot establish identity authority"):
        adapter._single_identity(SimpleNamespace(), {}, {})
