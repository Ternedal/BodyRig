from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig.photoreal_model_set import build_model_set


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_reference_vision_adapter.py"
SPEC = importlib.util.spec_from_file_location("bodyrig_photoreal_reference_vision_adapter_test", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
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
