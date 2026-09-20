from __future__ import annotations

import importlib.util
import math
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_identity_flip_tta_diagnostic.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_photoreal_identity_flip_tta_diagnostic_test",
    TOOL,
)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def _bank() -> dict[str, object]:
    return {
        "performer_id": "42",
        "identity_bank_sha256": "b" * 64,
        "extractor": "bodyrig-reference-vision-v1",
        "extractor_revision": "r" * 64,
        "model_set_sha256": "a" * 64,
        "embedding_dimension": 2,
    }


def _source() -> dict[str, object]:
    return {
        "source_key": "scene:9:E:/negative.mp4",
        "source_sha256": "c" * 64,
        "subject_performer_id": "99",
        "resolved_path": "E:/negative.mp4",
        "samples": [
            {
                "timestamp_seconds": 1.25,
                "eye": "mono",
            }
        ],
    }


def _calibration_request() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-calibration-extractor-request",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": "b" * 64,
        "adapter": "bodyrig-reference-vision-v1",
        "revision": "r" * 64,
        "model_set_sha256": "a" * 64,
        "embedding_dimension": 2,
        "sources": [_source()],
        "measurement_only": True,
        "calibration_only": True,
        "identity_matching_authority": False,
        "teacher_training_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _negative_observations() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-negative-observations",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": "b" * 64,
        "extractor": "bodyrig-reference-vision-v1",
        "extractor_revision": "r" * 64,
        "model_set_sha256": "a" * 64,
        "embedding_dimension": 2,
        "observations": [
            {
                "source_key": "scene:9:E:/negative.mp4",
                "source_sha256": "c" * 64,
                "subject_performer_id": "99",
                "timestamp_seconds": 1.25,
                "eye": "mono",
                "frame_sha256": "f" * 64,
                "embedding": [-1.0, 0.0],
            }
        ],
        "calibration_only": True,
        "build_only": True,
        "identity_matching_authority": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_tta_mean_l2_normalizes_inputs_and_output() -> None:
    result = diagnostic._tta_mean(
        [3.0, 0.0],
        [0.0, 4.0],
        dimension=2,
    )

    assert result == pytest.approx(
        [1.0 / math.sqrt(2.0), 1.0 / math.sqrt(2.0)]
    )
    assert math.sqrt(sum(value * value for value in result)) == pytest.approx(1.0)


def test_aligned_crop_flip_uses_original_face_alignment_without_redetection_of_flipped_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeArray:
        size = 4

    class FakeVector:
        def __init__(self, values: list[float]) -> None:
            self.values = values

        def reshape(self, *_shape: int) -> "FakeVector":
            return self

        def tolist(self) -> list[float]:
            return list(self.values)

    class FakeNumpy:
        @staticmethod
        def ascontiguousarray(value: object) -> object:
            return value

        @staticmethod
        def asarray(value: list[float]) -> FakeVector:
            return FakeVector(value)

    class FakeCv2:
        @staticmethod
        def flip(_image: object, axis: int) -> FakeArray:
            assert axis == 1
            return FakeArray()

    class FakeRecognizer:
        input_size = (112, 112)

        def __init__(self) -> None:
            self.calls = 0

        def get_feat(self, _image: object) -> list[float]:
            self.calls += 1
            return [1.0, 0.0] if self.calls == 1 else [0.8, 0.6]

    face = types.SimpleNamespace(kps=[[0.0, 0.0]] * 5)
    recognizer = FakeRecognizer()
    runtime = types.SimpleNamespace(
        cv2=FakeCv2(),
        np=FakeNumpy(),
        face_app=types.SimpleNamespace(models={"recognition": recognizer}),
    )

    class FakeAdapter:
        @staticmethod
        def _candidates(_runtime: object, _image: object) -> list[dict[str, object]]:
            return [{"face": face}]

        @staticmethod
        def _embedding(_face: object, dimension: int) -> list[float]:
            assert dimension == 2
            return [1.0, 0.0]

    face_align = types.SimpleNamespace(
        norm_crop=lambda _image, *, landmark, image_size: (
            FakeArray()
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

    flipped, quality = diagnostic._aligned_crop_flip_measurement(
        adapter=FakeAdapter(),
        runtime=runtime,
        image=FakeArray(),
        original_embedding=[1.0, 0.0],
        dimension=2,
    )

    assert flipped == pytest.approx([0.8, 0.6])
    assert quality["status"] == "available"
    assert quality["recognition_input_size"] == 112
    assert quality["original_face_replay_cosine"] == pytest.approx(1.0)
    assert quality["aligned_original_replay_cosine"] == pytest.approx(1.0)
    assert recognizer.calls == 2


def test_score_models_reports_all_three_diagnostic_models() -> None:
    positives = [
        {"group_id": "scene:1", "embedding": [1.0, 0.0]},
        {
            "group_id": "scene:1",
            "embedding": diagnostic._normalize(
                [0.99, 0.05],
                dimension=2,
                label="p1",
            ),
        },
        {
            "group_id": "scene:2",
            "embedding": diagnostic._normalize(
                [0.98, 0.10],
                dimension=2,
                label="p2",
            ),
        },
        {
            "group_id": "scene:2",
            "embedding": diagnostic._normalize(
                [0.97, 0.12],
                dimension=2,
                label="p3",
            ),
        },
    ]
    negatives = [
        {"subject_performer_id": "99", "embedding": [-1.0, 0.0]},
        {
            "subject_performer_id": "100",
            "embedding": diagnostic._normalize(
                [-0.9, -0.1],
                dimension=2,
                label="n1",
            ),
        },
    ]

    result = diagnostic._score_models(positives, negatives)

    assert set(result) == {
        "current-reference-weighted",
        "group-balanced-centroid-lgo",
        "nearest-group-prototype",
    }
    for model in result.values():
        assert model["diagnostic_only"] is True
        assert model["observed_separation_margin"] > 0.05
        assert model["would_meet_margin"] is True


def test_calibration_request_keeps_matching_and_training_closed() -> None:
    request = _calibration_request()
    bank = _bank()

    sources = diagnostic._validate_calibration_request(
        request,
        performer_id="42",
        bank=bank,
        adapter_revision="r" * 64,
    )
    assert set(sources) == {"scene:9:E:/negative.mp4"}

    request["identity_matching_authority"] = True
    with pytest.raises(
        diagnostic.PhotorealIdentityFlipTtaDiagnosticError,
        match="authority boundary",
    ):
        diagnostic._validate_calibration_request(
            request,
            performer_id="42",
            bank=bank,
            adapter_revision="r" * 64,
        )


def test_negative_observations_reject_model_set_substitution() -> None:
    bank = _bank()
    request = _calibration_request()
    sources = diagnostic._validate_calibration_request(
        request,
        performer_id="42",
        bank=bank,
        adapter_revision="r" * 64,
    )
    observations = _negative_observations()
    observations["model_set_sha256"] = "d" * 64

    with pytest.raises(
        diagnostic.PhotorealIdentityFlipTtaDiagnosticError,
        match="model set mismatch",
    ):
        diagnostic._validate_negative_observations(
            observations,
            performer_id="42",
            bank=bank,
            adapter_revision="r" * 64,
            sources=sources,
            dimension=2,
        )


def test_negative_observations_keep_matching_training_and_production_closed() -> None:
    bank = _bank()
    request = _calibration_request()
    sources = diagnostic._validate_calibration_request(
        request,
        performer_id="42",
        bank=bank,
        adapter_revision="r" * 64,
    )
    observations = _negative_observations()

    result = diagnostic._validate_negative_observations(
        observations,
        performer_id="42",
        bank=bank,
        adapter_revision="r" * 64,
        sources=sources,
        dimension=2,
    )
    assert len(result) == 1

    observations["teacher_training_authorized"] = True
    with pytest.raises(
        diagnostic.PhotorealIdentityFlipTtaDiagnosticError,
        match="authority boundary",
    ):
        diagnostic._validate_negative_observations(
            observations,
            performer_id="42",
            bank=bank,
            adapter_revision="r" * 64,
            sources=sources,
            dimension=2,
        )
