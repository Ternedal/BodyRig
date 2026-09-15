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


def test_identity_bootstrap_rejects_spatial_source_before_deprojection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "_read_sample", lambda *_args, **_kwargs: (IMAGE, True))

    with pytest.raises(adapter.ReferenceVisionError, match="spatial source cannot establish identity authority"):
        adapter._single_identity(RUNTIME, SOURCE, SAMPLE)


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
