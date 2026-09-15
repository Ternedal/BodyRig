from __future__ import annotations

import hashlib
import json

import pytest

import bodyrig.photoreal_calibration_provenance_pipeline as pipeline
from bodyrig.photoreal_calibration_provenance_authority import (
    PhotorealCalibrationProvenanceAuthorityError,
)
from bodyrig.photoreal_teacher_input import _digest


def _sealed() -> dict[str, object]:
    calibration_sha = "a" * 64
    inventory_sha = "b" * 64
    raw = json.dumps(
        {
            "identity_calibration_sha256": calibration_sha,
            "negative_inventory_sha256": inventory_sha,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        "identity_calibration_sha256": calibration_sha,
        "negative_inventory_sha256": inventory_sha,
        "identity_calibration_provenance_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _sealed_artifact(calibration: dict[str, object]) -> dict[str, object]:
    return {
        "negative_inventory_sha256": calibration["negative_inventory_sha256"],
        "identity_calibration_provenance_sha256": calibration[
            "identity_calibration_provenance_sha256"
        ],
    }


def test_frame_authority_requires_valid_calibration_seal(monkeypatch: pytest.MonkeyPatch) -> None:
    calibration = _sealed()
    monkeypatch.setattr(
        pipeline,
        "authorize_frame_identities",
        lambda plan, measurements, bank, value: {"authorized": True},
    )

    result = pipeline.authorize_frame_identities_sealed({}, {}, {}, calibration)

    assert result["authorized"] is True
    assert result["negative_inventory_sha256"] == calibration["negative_inventory_sha256"]
    assert result["identity_calibration_provenance_sha256"] == calibration[
        "identity_calibration_provenance_sha256"
    ]


def test_legacy_core_only_calibration_fails_before_frame_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def authorize(*args: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(pipeline, "authorize_frame_identities", authorize)
    with pytest.raises(PhotorealCalibrationProvenanceAuthorityError):
        pipeline.authorize_frame_identities_sealed(
            {}, {}, {}, {"identity_calibration_sha256": "a" * 64}
        )
    assert called is False


def test_frame_index_requires_and_propagates_upstream_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calibration = _sealed()
    authority = _sealed_artifact(calibration)
    monkeypatch.setattr(
        pipeline,
        "build_frame_index",
        lambda plan, receipt, observations: {"frame_count": 3},
    )

    result = pipeline.build_frame_index_sealed({}, {}, authority)

    assert result["frame_count"] == 3
    assert result["negative_inventory_sha256"] == calibration["negative_inventory_sha256"]
    assert result["identity_calibration_provenance_sha256"] == calibration[
        "identity_calibration_provenance_sha256"
    ]


@pytest.mark.parametrize(
    "missing",
    ["negative_inventory_sha256", "identity_calibration_provenance_sha256"],
)
def test_frame_index_rejects_legacy_authority_before_builder(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    calibration = _sealed()
    authority = _sealed_artifact(calibration)
    authority.pop(missing)
    called = False

    def build(*args: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(pipeline, "build_frame_index", build)
    with pytest.raises(pipeline.PhotorealCalibrationProvenancePipelineError):
        pipeline.build_frame_index_sealed({}, {}, authority)
    assert called is False


def test_teacher_manifest_is_resealed_after_provenance_is_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calibration = _sealed()
    frame_index = _sealed_artifact(calibration)
    monkeypatch.setattr(
        pipeline,
        "build_teacher_input",
        lambda plan, receipt, index, selection: {
            "format": "bodyrig-photoreal-teacher-input",
            "version": 1,
            "teacher_input_sha256": "0" * 64,
        },
    )

    result = pipeline.build_teacher_input_sealed({}, {}, frame_index, {})
    claimed = result["teacher_input_sha256"]
    unsigned = dict(result)
    unsigned.pop("teacher_input_sha256")

    assert result["negative_inventory_sha256"] == calibration["negative_inventory_sha256"]
    assert result["identity_calibration_provenance_sha256"] == calibration[
        "identity_calibration_provenance_sha256"
    ]
    assert claimed == _digest(unsigned)
    assert claimed != "0" * 64


def test_teacher_builder_rejects_malformed_provenance_before_legacy_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calibration = _sealed()
    frame_index = _sealed_artifact(calibration)
    frame_index["negative_inventory_sha256"] = 1
    called = False

    def build(*args: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(pipeline, "build_teacher_input", build)
    with pytest.raises(pipeline.PhotorealCalibrationProvenancePipelineError):
        pipeline.build_teacher_input_sealed({}, {}, frame_index, {})
    assert called is False
