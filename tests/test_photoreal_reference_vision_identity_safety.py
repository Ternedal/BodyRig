from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_reference_vision_adapter.py"
SPEC = importlib.util.spec_from_file_location("bodyrig_photoreal_reference_identity_safety_test", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


RUNTIME = SimpleNamespace(embedding_dimension=4)
SOURCE = {"source_key": "scene:s1:E:/clip.mp4"}
SAMPLE = {"timestamp_seconds": 1.0, "eye": "mono"}
IMAGE = object()
FACE = object()


def test_identity_bootstrap_rejects_spatial_source_without_exact_projection_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "_read_sample", lambda *_args, **_kwargs: (IMAGE, True))

    with pytest.raises(adapter.ReferenceVisionError, match="requires exact equirectangular projection authority"):
        adapter._single_identity(RUNTIME, SOURCE, SAMPLE)


def test_identity_bootstrap_deprojects_authorized_equi_before_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewport = object()
    source = {
        **SOURCE,
        "projection": "equi",
        "projection_authority": {"format": "bodyrig-explicit-projection-authority", "version": 1},
    }
    monkeypatch.setattr(adapter, "_read_sample", lambda *_args, **_kwargs: (IMAGE, True))
    seen: dict[str, object] = {}

    def deproject(runtime, image, authority):
        seen["runtime"] = runtime
        seen["image"] = image
        seen["authority"] = authority
        return [("front", viewport)]

    monkeypatch.setattr(adapter, "deproject_equirectangular_views", deproject)
    monkeypatch.setattr(adapter, "_candidates", lambda _runtime, image: [{"face": FACE}] if image is viewport else [])
    monkeypatch.setattr(adapter, "_embedding", lambda *_args, **_kwargs: [1.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(adapter, "_frame_sha", lambda image: "b" * 64 if image is viewport else "c" * 64)

    assert adapter._single_identity(RUNTIME, source, SAMPLE) == (
        "b" * 64,
        [1.0, 0.0, 0.0, 0.0],
    )
    assert seen == {
        "runtime": RUNTIME,
        "image": IMAGE,
        "authority": source["projection_authority"],
    }


def test_identity_bootstrap_drops_spatial_sample_when_multiple_viewports_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left = object()
    right = object()
    source = {
        **SOURCE,
        "projection": "equi",
        "projection_authority": {"format": "bodyrig-explicit-projection-authority", "version": 1},
    }
    monkeypatch.setattr(adapter, "_read_sample", lambda *_args, **_kwargs: (IMAGE, True))
    monkeypatch.setattr(
        adapter,
        "deproject_equirectangular_views",
        lambda *_args, **_kwargs: [("left", left), ("right", right)],
    )
    monkeypatch.setattr(adapter, "_candidates", lambda *_args, **_kwargs: [{"face": FACE}])
    monkeypatch.setattr(adapter, "_embedding", lambda *_args, **_kwargs: [1.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(adapter, "_frame_sha", lambda image: "d" * 64 if image is left else "e" * 64)

    assert adapter._single_identity(RUNTIME, source, SAMPLE) is None


def test_identity_bootstrap_drops_sample_with_multiple_people(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "_read_sample", lambda *_args, **_kwargs: (IMAGE, False))
    monkeypatch.setattr(
        adapter,
        "_candidates",
        lambda *_args, **_kwargs: [
            {"face": FACE},
            {"face": object()},
        ],
    )

    assert adapter._single_identity(RUNTIME, SOURCE, SAMPLE) is None


def test_identity_bootstrap_drops_sample_without_face_embedding_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "_read_sample", lambda *_args, **_kwargs: (IMAGE, False))
    monkeypatch.setattr(adapter, "_candidates", lambda *_args, **_kwargs: [{"face": None}])

    assert adapter._single_identity(RUNTIME, SOURCE, SAMPLE) is None


def test_identity_bootstrap_accepts_only_one_unambiguous_face(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "_read_sample", lambda *_args, **_kwargs: (IMAGE, False))
    monkeypatch.setattr(adapter, "_candidates", lambda *_args, **_kwargs: [{"face": FACE}])
    monkeypatch.setattr(adapter, "_embedding", lambda *_args, **_kwargs: [1.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(adapter, "_frame_sha", lambda *_args, **_kwargs: "a" * 64)

    assert adapter._single_identity(RUNTIME, SOURCE, SAMPLE) == (
        "a" * 64,
        [1.0, 0.0, 0.0, 0.0],
    )
