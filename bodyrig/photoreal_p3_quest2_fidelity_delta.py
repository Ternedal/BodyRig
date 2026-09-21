from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p3_device_distillation_plan import FIDELITY_DELTA_DIMENSIONS
from .photoreal_p3_device_distillation_runner import (
    _digest,
    _file_sha,
    _sha,
    _strict_v1,
    _text,
)
from .photoreal_p3_quest2_hair_student_runner import (
    IMPLEMENTED_COMPONENTS,
    validate_hair_student_receipt,
)


FORMAT = "bodyrig-photoreal-p3-quest2-fidelity-delta-evidence"
VERSION = 1
POLICY_REVISION = "bodyrig-p3-quest2-fidelity-delta-v1"
REMAINING_BLOCKERS = ("p3-distillation-manifest",)

ARTIFACT_FIELDS = {"kind", "relative_path", "size_bytes", "sha256"}
COMPONENT_METRIC_FIELDS = {"metric", "value", "unit"}
MEASUREMENT_FIELDS = {
    "dimension",
    "metric",
    "value",
    "unit",
    "teacher_reference",
    "student_reference",
    "component_metrics",
}
EXPECTED_COMPONENT_METRICS = {
    "identity_likeness": (
        "symmetric-surface-chamfer-rms/body-height",
    ),
    "face_detail": (
        "face-surface-chamfer-rms/body-height",
        "face-basecolor-rgb-rmse",
    ),
    "eyes": (
        "eye-surface-chamfer-rms/body-height",
        "eye-basecolor-rgb-rmse",
    ),
    "hair_silhouette_and_appearance": (
        "hair-surface-chamfer-rms/body-height",
        "hair-basecolor-rgb-rmse",
    ),
    "skin_material_response": (
        "skin-basecolor-rgb-rmse",
    ),
    "hands_and_extremities": (
        "extremity-surface-chamfer-rms/body-height",
    ),
    "motion_identity_preservation": (
        "teacher-pose-dependent-refinement-residual-rmse/body-height",
    ),
    "temporal_stability": (
        "teacher-refinement-frame-delta-rmse/body-height",
    ),
}


class PhotorealP3Quest2FidelityDeltaError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3Quest2FidelityDeltaError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3Quest2FidelityDeltaError(
            f"{label} must be a JSON object"
        )
    return value


def _finite_nonnegative(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3Quest2FidelityDeltaError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise PhotorealP3Quest2FidelityDeltaError(f"{label} is invalid")
    return result


def _artifact_records(
    value: Any,
    *,
    root: Path,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity student artifact universe is incomplete"
        )
    normalized: list[dict[str, Any]] = []
    seen_kind: set[str] = set()
    seen_path: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealP3Quest2FidelityDeltaError(
                "Quest2 fidelity student artifact fields mismatch"
            )
        kind = _text(
            raw.get("kind"),
            label="Quest2 fidelity artifact kind",
            maximum=64,
        )
        relative = _text(
            raw.get("relative_path"),
            label="Quest2 fidelity artifact path",
        ).replace("\\", "/")
        first = relative.split("/", 1)[0]
        if (
            relative.startswith("/")
            or relative.startswith("../")
            or "/../" in f"/{relative}/"
            or ":" in first
            or relative in seen_path
            or kind in seen_kind
        ):
            raise PhotorealP3Quest2FidelityDeltaError(
                "Quest2 fidelity artifact universe is repeated/unsafe"
            )
        seen_path.add(relative)
        seen_kind.add(kind)
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PhotorealP3Quest2FidelityDeltaError(
                "Quest2 fidelity artifact escapes student root"
            ) from exc
        size = raw.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
        ):
            raise PhotorealP3Quest2FidelityDeltaError(
                f"Quest2 fidelity artifact size/path drifted: {relative}"
            )
        observed = _file_sha(path)
        expected = _sha(
            raw.get("sha256"),
            label="Quest2 fidelity artifact SHA-256",
        )
        if observed != expected:
            raise PhotorealP3Quest2FidelityDeltaError(
                f"Quest2 fidelity artifact bytes drifted: {relative}"
            )
        normalized.append(
            {
                "kind": kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed,
            }
        )
    if seen_kind != {
        "student-runtime-package",
        "teacher-derived-basecolor",
    }:
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity artifact kind universe mismatch"
        )
    return sorted(normalized, key=lambda item: item["relative_path"])


def _measurement(raw: Mapping[str, Any]) -> dict[str, Any]:
    if set(raw) != MEASUREMENT_FIELDS:
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity measurement fields mismatch"
        )
    dimension = _text(
        raw.get("dimension"),
        label="Quest2 fidelity dimension",
        maximum=96,
    )
    if dimension not in FIDELITY_DELTA_DIMENSIONS:
        raise PhotorealP3Quest2FidelityDeltaError(
            f"Quest2 fidelity dimension is unsupported: {dimension}"
        )
    teacher_reference = _text(
        raw.get("teacher_reference"),
        label=f"Quest2 {dimension} teacher reference",
        maximum=512,
    )
    student_reference = _text(
        raw.get("student_reference"),
        label=f"Quest2 {dimension} student reference",
        maximum=512,
    )
    if "sha256:" not in teacher_reference or "sha256:" not in student_reference:
        raise PhotorealP3Quest2FidelityDeltaError(
            f"Quest2 {dimension} references must contain exact SHA-256 authority"
        )

    components = raw.get("component_metrics")
    expected_names = EXPECTED_COMPONENT_METRICS[dimension]
    if not isinstance(components, list) or len(components) != len(expected_names):
        raise PhotorealP3Quest2FidelityDeltaError(
            f"Quest2 {dimension} component metric universe is incomplete"
        )
    normalized_components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in components:
        if not isinstance(item, Mapping) or set(item) != COMPONENT_METRIC_FIELDS:
            raise PhotorealP3Quest2FidelityDeltaError(
                f"Quest2 {dimension} component metric fields mismatch"
            )
        name = _text(
            item.get("metric"),
            label=f"Quest2 {dimension} component metric",
            maximum=160,
        )
        if name not in expected_names or name in seen:
            raise PhotorealP3Quest2FidelityDeltaError(
                f"Quest2 {dimension} component metric is unsupported/repeated"
            )
        seen.add(name)
        unit = _text(
            item.get("unit"),
            label=f"Quest2 {dimension} component unit",
            maximum=80,
        )
        if unit not in {"normalized-rmse", "rgb-0-1-rmse"}:
            raise PhotorealP3Quest2FidelityDeltaError(
                f"Quest2 {dimension} component unit is unsupported"
            )
        normalized_components.append(
            {
                "metric": name,
                "value": _finite_nonnegative(
                    item.get("value"),
                    label=f"Quest2 {dimension} component value",
                ),
                "unit": unit,
            }
        )
    if seen != set(expected_names):
        raise PhotorealP3Quest2FidelityDeltaError(
            f"Quest2 {dimension} component metric universe is incomplete"
        )
    normalized_components.sort(key=lambda item: expected_names.index(item["metric"]))

    value = _finite_nonnegative(
        raw.get("value"),
        label=f"Quest2 {dimension} aggregate value",
    )
    expected_value = max(item["value"] for item in normalized_components)
    if abs(value - expected_value) > 1e-9:
        raise PhotorealP3Quest2FidelityDeltaError(
            f"Quest2 {dimension} aggregate must equal worst measured component"
        )

    expected_metric = (
        expected_names[0]
        if len(expected_names) == 1
        else "worst-axis(" + ",".join(expected_names) + ")"
    )
    if raw.get("metric") != expected_metric:
        raise PhotorealP3Quest2FidelityDeltaError(
            f"Quest2 {dimension} aggregate metric is non-canonical"
        )
    expected_unit = (
        normalized_components[0]["unit"]
        if len(normalized_components) == 1
        else "dimensionless-worst-axis-delta"
    )
    if raw.get("unit") != expected_unit:
        raise PhotorealP3Quest2FidelityDeltaError(
            f"Quest2 {dimension} aggregate unit is non-canonical"
        )

    return {
        "dimension": dimension,
        "metric": expected_metric,
        "value": value,
        "unit": expected_unit,
        "teacher_reference": teacher_reference,
        "student_reference": student_reference,
        "component_metrics": normalized_components,
    }


def canonical_manifest_measurements(
    evidence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    validated = validate_fidelity_delta_evidence_structure(evidence)
    return [
        {
            "dimension": item["dimension"],
            "metric": item["metric"],
            "value": item["value"],
            "unit": item["unit"],
            "teacher_reference": item["teacher_reference"],
            "student_reference": item["student_reference"],
        }
        for item in validated["fidelity_delta_measurements"]
    ]


def validate_fidelity_delta_evidence_structure(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_receipt_sha256",
        "p3_quest2_eye_student_receipt_sha256",
        "p3_quest2_hair_student_receipt_sha256",
        "target_model",
        "student_representation",
        "implemented_student_components",
        "teacher_checkpoint_sha256",
        "teacher_point_count",
        "student_artifacts",
        "measurement_policy_revision",
        "fidelity_delta_measurements",
        "fidelity_delta_complete",
        "p3_distillation_complete",
        "remaining_blockers",
        "human_runtime_visual_acceptance_required",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_quest2_fidelity_delta_evidence_sha256",
    }
    if set(value) != expected_fields or value.get("format") != FORMAT:
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity evidence fields/format mismatch"
        )
    try:
        _strict_v1(value.get("version"), label="Quest2 fidelity evidence")
    except Exception as exc:
        raise PhotorealP3Quest2FidelityDeltaError(str(exc)) from exc
    if value.get("version") != VERSION:
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity evidence version mismatch"
        )

    _text(
        value.get("performer_id"),
        label="Quest2 fidelity performer",
        maximum=256,
    )
    _text(
        value.get("selected_epoch_id"),
        label="Quest2 fidelity epoch",
        maximum=256,
    )
    for field in (
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_receipt_sha256",
        "p3_quest2_eye_student_receipt_sha256",
        "p3_quest2_hair_student_receipt_sha256",
        "teacher_checkpoint_sha256",
        "p3_quest2_fidelity_delta_evidence_sha256",
    ):
        _sha(value.get(field), label=f"Quest2 fidelity evidence {field}")

    if (
        value.get("target_model") != "quest-2"
        or value.get("student_representation") != "skinned-mesh-pbr"
        or value.get("implemented_student_components")
        != list(IMPLEMENTED_COMPONENTS)
        or value.get("measurement_policy_revision") != POLICY_REVISION
        or value.get("remaining_blockers") != list(REMAINING_BLOCKERS)
    ):
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity evidence representation/policy mismatch"
        )
    teacher_point_count = value.get("teacher_point_count")
    if (
        isinstance(teacher_point_count, bool)
        or not isinstance(teacher_point_count, int)
        or teacher_point_count < 10475
    ):
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity teacher point count is invalid"
        )
    for field, expected in (
        ("fidelity_delta_complete", True),
        ("p3_distillation_complete", False),
        ("human_runtime_visual_acceptance_required", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3Quest2FidelityDeltaError(
                f"Quest2 fidelity evidence authority mismatch: {field}"
            )

    measurements = value.get("fidelity_delta_measurements")
    if (
        not isinstance(measurements, list)
        or len(measurements) != len(FIDELITY_DELTA_DIMENSIONS)
    ):
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity measurement universe is incomplete"
        )
    by_dimension: dict[str, dict[str, Any]] = {}
    for raw in measurements:
        if not isinstance(raw, Mapping):
            raise PhotorealP3Quest2FidelityDeltaError(
                "Quest2 fidelity measurement must be an object"
            )
        normalized = _measurement(raw)
        dimension = normalized["dimension"]
        if dimension in by_dimension:
            raise PhotorealP3Quest2FidelityDeltaError(
                "Quest2 fidelity measurement dimension is repeated"
            )
        by_dimension[dimension] = normalized
    if set(by_dimension) != set(FIDELITY_DELTA_DIMENSIONS):
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity measurement dimensions are incomplete"
        )

    claimed = value["p3_quest2_fidelity_delta_evidence_sha256"]
    if _digest(
        value,
        omit="p3_quest2_fidelity_delta_evidence_sha256",
    ) != claimed:
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity evidence digest mismatch"
        )

    normalized = dict(value)
    normalized["fidelity_delta_measurements"] = [
        by_dimension[dimension] for dimension in FIDELITY_DELTA_DIMENSIONS
    ]
    return normalized


def validate_fidelity_delta_evidence(
    value: Mapping[str, Any],
    *,
    hair_receipt: Mapping[str, Any],
    hair_output_root: str | Path,
) -> dict[str, Any]:
    try:
        hair = validate_hair_student_receipt(
            hair_receipt,
            hair_output_root=hair_output_root,
        )
    except Exception as exc:
        raise PhotorealP3Quest2FidelityDeltaError(str(exc)) from exc

    evidence = validate_fidelity_delta_evidence_structure(value)
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_receipt_sha256",
        "p3_quest2_eye_student_receipt_sha256",
        "target_model",
        "student_representation",
        "implemented_student_components",
    ):
        if evidence.get(field) != hair.get(field):
            raise PhotorealP3Quest2FidelityDeltaError(
                f"Quest2 fidelity/hair provenance mismatch: {field}"
            )
    if (
        evidence["p3_quest2_hair_student_receipt_sha256"]
        != hair["p3_quest2_hair_student_receipt_sha256"]
    ):
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity evidence targets different hair receipt bytes"
        )

    root = Path(hair_output_root).expanduser().resolve()
    artifacts = _artifact_records(evidence.get("student_artifacts"), root=root)
    if artifacts != hair["student_artifacts"]:
        raise PhotorealP3Quest2FidelityDeltaError(
            "Quest2 fidelity evidence targets different student artifact bytes"
        )
    evidence["student_artifacts"] = artifacts
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strict-read exact Quest2 P3 teacher/student fidelity-delta evidence."
    )
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--hair-receipt", type=Path, required=True)
    parser.add_argument("--hair-output-root", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        evidence = validate_fidelity_delta_evidence(
            _read_json(args.evidence, label="Quest2 fidelity evidence"),
            hair_receipt=_read_json(args.hair_receipt, label="Quest2 hair receipt"),
            hair_output_root=args.hair_output_root,
        )
    except (OSError, PhotorealP3Quest2FidelityDeltaError) as exc:
        print(f"BodyRig P3 Quest2 fidelity delta: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P3_QUEST2_FIDELITY_DELTA_VERIFIED",
                "dimension_count": len(evidence["fidelity_delta_measurements"]),
                "remaining_blockers": evidence["remaining_blockers"],
                "p3_distillation_complete": False,
                "human_runtime_visual_acceptance_required": True,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
