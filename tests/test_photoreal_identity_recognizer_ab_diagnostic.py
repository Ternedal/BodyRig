from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_identity_recognizer_ab_diagnostic.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_photoreal_identity_recognizer_ab_diagnostic_test",
    TOOL,
)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def _provenance() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-diagnostic-recognizer-provenance",
        "version": 1,
        "package": "antelopev2",
        "archive_url": (
            "https://github.com/deepinsight/insightface/releases/download/"
            "model-zoo/antelopev2.zip"
        ),
        "archive_sha256": (
            "8e182f14fc6e80b3bfa375b33eb6cff7ee05d8ef7633e738d1c89021dcf0c5c5"
        ),
        "recognizer_file": "glintr100.onnx",
        "recognizer_sha256": (
            "4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf"
        ),
        "recognition_architecture": "ResNet100",
        "recognition_training_set": "Glint360K",
        "embedding_dimension": 512,
        "input_size": 112,
        "preprocessing": "insightface-arcface-1",
        "license_operator_accepted": True,
        "diagnostic_only": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_alternate_provenance_is_exact_and_authority_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "glintr100.onnx").write_bytes(b"diagnostic")
    (tmp_path / "source-provenance.json").write_text(
        json.dumps(_provenance()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        diagnostic,
        "_sha256_file",
        lambda _path: diagnostic.ALTERNATE_RECOGNIZER_SHA256,
    )

    path, provenance = diagnostic._validate_alternate_provenance(root=tmp_path)

    assert path == tmp_path / "glintr100.onnx"
    assert provenance["diagnostic_only"] is True
    assert provenance["production_activation"] is False

    bad = _provenance()
    bad["identity_matching_authorized"] = True
    (tmp_path / "source-provenance.json").write_text(
        json.dumps(bad),
        encoding="utf-8",
    )
    with pytest.raises(
        diagnostic.PhotorealIdentityRecognizerAbDiagnosticError,
        match="identity_matching_authorized",
    ):
        diagnostic._validate_alternate_provenance(root=tmp_path)


def test_measure_recognizers_uses_one_original_alignment_for_both_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    face = types.SimpleNamespace(kps=[[0.0, 0.0]] * 5)
    aligned = object()

    class FakeNumpy:
        @staticmethod
        def ascontiguousarray(value: object) -> object:
            return value

    class FakeCurrentRecognizer:
        @staticmethod
        def get_feat(image: object) -> list[float]:
            assert image is aligned
            return [1.0, 0.0]

    class FakeAlternateRecognizer:
        @staticmethod
        def get_feat(image: object) -> list[float]:
            assert image is aligned
            return [0.8, 0.6]

    class FakeAdapter:
        @staticmethod
        def _candidates(_runtime: object, _image: object) -> list[dict[str, object]]:
            return [{"face": face}]

    runtime = types.SimpleNamespace(
        np=FakeNumpy(),
        face_app=types.SimpleNamespace(
            models={"recognition": FakeCurrentRecognizer()}
        ),
    )
    representation = types.SimpleNamespace(
        _single_face_measurement=lambda **_kwargs: (
            [1.0, 0.0],
            {"status": "available"},
        )
    )

    face_align = types.SimpleNamespace(
        norm_crop=lambda _image, *, landmark, image_size: (
            aligned
            if landmark is face.kps and image_size == 112
            else (_ for _ in ()).throw(AssertionError("unexpected alignment"))
        )
    )
    insightface = types.ModuleType("insightface")
    insightface_utils = types.ModuleType("insightface.utils")
    insightface_utils.face_align = face_align
    insightface.utils = insightface_utils
    monkeypatch.setitem(sys.modules, "insightface", insightface)
    monkeypatch.setitem(sys.modules, "insightface.utils", insightface_utils)

    current, alternate, quality = diagnostic._measure_recognizers(
        adapter=FakeAdapter(),
        runtime=runtime,
        representation=representation,
        alternate_recognizer=FakeAlternateRecognizer(),
        image=object(),
        dimension=2,
    )

    assert current == pytest.approx([1.0, 0.0])
    assert alternate == pytest.approx([0.8, 0.6])
    assert quality["status"] == "available"
    assert quality["current_direct_replay_cosine"] == pytest.approx(1.0)


def test_pinned_antelopev2_hashes_are_current_official_values() -> None:
    assert (
        diagnostic.ALTERNATE_ARCHIVE_SHA256
        == "8e182f14fc6e80b3bfa375b33eb6cff7ee05d8ef7633e738d1c89021dcf0c5c5"
    )
    assert (
        diagnostic.ALTERNATE_RECOGNIZER_SHA256
        == "4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf"
    )
    assert diagnostic.ALTERNATE_RECOGNIZER_FILE == "glintr100.onnx"
