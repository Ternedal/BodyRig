from __future__ import annotations

import copy

import pytest

import bodyrig.photoreal_p3_quest2_fidelity_delta as fidelity
from bodyrig.photoreal_p3_device_distillation_plan import (
    FIDELITY_DELTA_DIMENSIONS,
)
from bodyrig.photoreal_p3_device_distillation_runner import _digest
from bodyrig.photoreal_p3_quest2_fidelity_delta import (
    PhotorealP3Quest2FidelityDeltaError,
    canonical_manifest_measurements,
    validate_fidelity_delta_evidence_structure,
)


def _measurement(dimension: str, base: float) -> dict[str, object]:
    names = fidelity.EXPECTED_COMPONENT_METRICS[dimension]
    components = []
    for index, name in enumerate(names):
        unit = (
            "rgb-0-1-rmse"
            if "rgb-rmse" in name
            else "normalized-rmse"
        )
        components.append(
            {
                "metric": name,
                "value": round(base + index * 0.01, 9),
                "unit": unit,
            }
        )
    value = max(float(item["value"]) for item in components)
    return {
        "dimension": dimension,
        "metric": (
            names[0]
            if len(names) == 1
            else "worst-axis(" + ",".join(names) + ")"
        ),
        "value": value,
        "unit": (
            components[0]["unit"]
            if len(components) == 1
            else "dimensionless-worst-axis-delta"
        ),
        "teacher_reference": "sha256:" + "a" * 64 + "#teacher",
        "student_reference": "sha256:" + "b" * 64 + "#student",
        "component_metrics": components,
    }


def _evidence() -> dict[str, object]:
    result: dict[str, object] = {
        "format": fidelity.FORMAT,
        "version": fidelity.VERSION,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p3_device_distillation_plan_sha256": "2" * 64,
        "p3_device_distillation_request_sha256": "3" * 64,
        "p3_quest2_student_candidate_receipt_sha256": "4" * 64,
        "p3_quest2_eye_student_receipt_sha256": "5" * 64,
        "p3_quest2_hair_student_receipt_sha256": "6" * 64,
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "implemented_student_components": [
            "specialized-eye-component",
            "teacher-derived-hair-component",
        ],
        "teacher_checkpoint_sha256": "7" * 64,
        "teacher_point_count": 12000,
        "student_artifacts": [
            {
                "kind": "student-runtime-package",
                "relative_path": "student/avatar.vrm",
                "size_bytes": 100,
                "sha256": "8" * 64,
            },
            {
                "kind": "teacher-derived-basecolor",
                "relative_path": "student/basecolor.png",
                "size_bytes": 100,
                "sha256": "9" * 64,
            },
        ],
        "measurement_policy_revision": fidelity.POLICY_REVISION,
        "fidelity_delta_measurements": [
            _measurement(dimension, 0.01 + index * 0.01)
            for index, dimension in enumerate(FIDELITY_DELTA_DIMENSIONS)
        ],
        "fidelity_delta_complete": True,
        "p3_distillation_complete": False,
        "remaining_blockers": ["p3-distillation-manifest"],
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_quest2_fidelity_delta_evidence_sha256"] = _digest(result)
    return result


def _reseal(value: dict[str, object]) -> None:
    value["p3_quest2_fidelity_delta_evidence_sha256"] = _digest(
        value,
        omit="p3_quest2_fidelity_delta_evidence_sha256",
    )


def test_fidelity_evidence_requires_all_canonical_dimensions() -> None:
    evidence = _evidence()
    validated = validate_fidelity_delta_evidence_structure(evidence)

    assert [
        item["dimension"]
        for item in validated["fidelity_delta_measurements"]
    ] == list(FIDELITY_DELTA_DIMENSIONS)
    assert validated["remaining_blockers"] == ["p3-distillation-manifest"]
    assert validated["p3_distillation_complete"] is False
    assert validated["runtime_acceptance_authority"] is False


def test_face_eye_hair_aggregate_is_worst_measured_axis() -> None:
    evidence = _evidence()
    for dimension in (
        "face_detail",
        "eyes",
        "hair_silhouette_and_appearance",
    ):
        measurement = next(
            item
            for item in evidence["fidelity_delta_measurements"]
            if item["dimension"] == dimension
        )
        assert measurement["value"] == max(
            item["value"]
            for item in measurement["component_metrics"]
        )


def test_fidelity_evidence_rejects_arbitrary_weighted_score() -> None:
    evidence = _evidence()
    measurement = evidence["fidelity_delta_measurements"][1]
    measurement["value"] = 0.0001
    _reseal(evidence)

    with pytest.raises(
        PhotorealP3Quest2FidelityDeltaError,
        match="aggregate must equal worst measured component",
    ):
        validate_fidelity_delta_evidence_structure(evidence)


def test_fidelity_evidence_rejects_reference_without_digest() -> None:
    evidence = _evidence()
    measurement = evidence["fidelity_delta_measurements"][0]
    measurement["teacher_reference"] = "teacher-zero-pose"
    _reseal(evidence)

    with pytest.raises(
        PhotorealP3Quest2FidelityDeltaError,
        match="must contain exact SHA-256 authority",
    ):
        validate_fidelity_delta_evidence_structure(evidence)


def test_fidelity_evidence_cannot_reseal_p3_complete() -> None:
    evidence = _evidence()
    evidence["p3_distillation_complete"] = True
    _reseal(evidence)

    with pytest.raises(
        PhotorealP3Quest2FidelityDeltaError,
        match="p3_distillation_complete",
    ):
        validate_fidelity_delta_evidence_structure(evidence)


def test_canonical_manifest_measurements_strip_internal_components() -> None:
    evidence = _evidence()

    measurements = canonical_manifest_measurements(evidence)

    assert len(measurements) == 8
    assert all("component_metrics" not in item for item in measurements)
    assert set(measurements[0]) == {
        "dimension",
        "metric",
        "value",
        "unit",
        "teacher_reference",
        "student_reference",
    }


def test_fidelity_digest_tamper_is_rejected() -> None:
    evidence = _evidence()
    tampered = copy.deepcopy(evidence)
    tampered["performer_id"] = "other"

    with pytest.raises(
        PhotorealP3Quest2FidelityDeltaError,
        match="digest mismatch",
    ):
        validate_fidelity_delta_evidence_structure(tampered)


def test_fidelity_engine_samples_materialized_eye_and_hair_primitives() -> None:
    import inspect
    from tools import photoreal_p3_exavatar_quest2_fidelity_delta as engine

    source = inspect.getsource(engine.build_fidelity_evidence)

    assert "query=eye_surface_positions" in source
    assert "eye_surface_uvs" in source
    assert "eye_student_rgb = _texture_samples" in source
    assert "query=hair_positions" in source
    assert "hair_uvs" in source
    assert "hair_student_rgb = _texture_samples" in source
