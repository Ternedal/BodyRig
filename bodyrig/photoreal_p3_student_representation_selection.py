from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_p3_device_distillation_plan import (
    CANDIDATE_STUDENT_REPRESENTATIONS,
    PhotorealP3DeviceDistillationPlanError,
    require_p3_distillation_execution_authority,
)


FORMAT = "bodyrig-photoreal-p3-student-representation-selection"
VERSION = 1

PRIMARY_REPRESENTATIONS = (
    "skinned-mesh-pbr",
    "skinned-mesh-neural-texture",
    "hybrid-mesh-neural-residual",
    "gaussian-splat-optional",
)
OPTIONAL_COMPONENTS = (
    "specialized-eye-component",
    "teacher-derived-hair-component",
)


class PhotorealP3StudentRepresentationSelectionError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3StudentRepresentationSelectionError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3StudentRepresentationSelectionError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP3StudentRepresentationSelectionError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP3StudentRepresentationSelectionError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealP3StudentRepresentationSelectionError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3StudentRepresentationSelectionError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP3StudentRepresentationSelectionError(
            f"{label} format/version mismatch"
        )


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 student representation selection cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _normalize_components(values: Sequence[str]) -> list[str]:
    normalized = [
        _text(value, label="P3 optional student component", maximum=128)
        for value in values
    ]
    if len(normalized) != len(set(normalized)):
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 optional student components must be unique"
        )
    unknown = sorted(set(normalized) - set(OPTIONAL_COMPONENTS))
    if unknown:
        raise PhotorealP3StudentRepresentationSelectionError(
            f"P3 optional student component is unsupported: {unknown[0]}"
        )
    return sorted(normalized)


def build_p3_student_representation_selection(
    plan: Mapping[str, Any],
    *,
    primary_representation: str,
    optional_components: Sequence[str] = (),
) -> dict[str, Any]:
    try:
        accepted = require_p3_distillation_execution_authority(plan)
    except PhotorealP3DeviceDistillationPlanError as exc:
        raise PhotorealP3StudentRepresentationSelectionError(str(exc)) from exc

    primary = _text(
        primary_representation,
        label="P3 primary student representation",
        maximum=128,
    )
    if primary not in PRIMARY_REPRESENTATIONS:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 primary student representation is unsupported"
        )
    candidates = accepted.get("candidate_student_representations")
    if candidates != list(CANDIDATE_STUDENT_REPRESENTATIONS) or primary not in candidates:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 primary representation is outside the accepted plan candidate universe"
        )

    components = _normalize_components(optional_components)
    if any(component not in candidates for component in components):
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 optional component is outside the accepted plan candidate universe"
        )

    profile = accepted.get("target_profile")
    if not isinstance(profile, Mapping):
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 accepted target profile is missing"
        )
    target_model = _text(
        profile.get("target_model"),
        label="P3 target model",
        maximum=64,
    )
    if target_model not in {"quest-2", "quest-3", "quest-3s"}:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 target model is unsupported"
        )

    native_gaussian = primary == "gaussian-splat-optional"
    if target_model == "quest-2" and native_gaussian:
        raise PhotorealP3StudentRepresentationSelectionError(
            "Quest 2 P3 student cannot depend on native Gaussian splats"
        )

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": _text(
            accepted.get("performer_id"),
            label="P3 performer",
            maximum=256,
        ),
        "selected_epoch_id": _text(
            accepted.get("selected_epoch_id"),
            label="P3 selected epoch",
            maximum=256,
        ),
        "p3_device_distillation_plan_sha256": _sha(
            accepted.get("p3_device_distillation_plan_sha256"),
            label="P3 device distillation plan SHA-256",
        ),
        "target_profile_sha256": _sha(
            accepted.get("target_profile_sha256"),
            label="P3 target profile SHA-256",
        ),
        "target_model": target_model,
        "accepted_teacher_checkpoint_sha256": _sha(
            accepted.get("accepted_teacher_checkpoint_sha256"),
            label="P3 accepted teacher checkpoint SHA-256",
        ),
        "primary_representation": primary,
        "optional_components": components,
        "optional_component_count": len(components),
        "selection_source": "operator-explicit",
        "native_gaussian_dependency_selected": native_gaussian,
        "teacher_remains_visual_authority": True,
        "student_may_not_claim_fidelity_above_teacher": True,
        "fidelity_delta_measurement_required": True,
        "student_representation_selected": True,
        "distillation_adapter_required": True,
        "distillation_adapter_selected": False,
        "distillation_job_start_authorized": False,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_student_representation_selection_sha256"] = _digest(
        result,
        omit="p3_student_representation_selection_sha256",
    )
    return validate_p3_student_representation_selection(result)


def validate_p3_student_representation_selection(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "p3_device_distillation_plan_sha256",
        "target_profile_sha256",
        "target_model",
        "accepted_teacher_checkpoint_sha256",
        "primary_representation",
        "optional_components",
        "optional_component_count",
        "selection_source",
        "native_gaussian_dependency_selected",
        "teacher_remains_visual_authority",
        "student_may_not_claim_fidelity_above_teacher",
        "fidelity_delta_measurement_required",
        "student_representation_selected",
        "distillation_adapter_required",
        "distillation_adapter_selected",
        "distillation_job_start_authorized",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_student_representation_selection_sha256",
    }
    if set(value) != expected_fields:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 student representation selection fields must match v1 exactly"
        )
    if value.get("format") != FORMAT:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 student representation selection format/version mismatch"
        )
    _strict_v1(value.get("version"), label="P3 student representation selection")
    _text(value.get("performer_id"), label="P3 performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P3 selected epoch", maximum=256)
    for field in (
        "p3_device_distillation_plan_sha256",
        "target_profile_sha256",
        "accepted_teacher_checkpoint_sha256",
    ):
        _sha(value.get(field), label=f"P3 representation selection {field}")

    target_model = _text(value.get("target_model"), label="P3 target model", maximum=64)
    if target_model not in {"quest-2", "quest-3", "quest-3s"}:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 target model is unsupported"
        )
    primary = _text(
        value.get("primary_representation"),
        label="P3 primary student representation",
        maximum=128,
    )
    if primary not in PRIMARY_REPRESENTATIONS:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 primary student representation is unsupported"
        )

    components = value.get("optional_components")
    if not isinstance(components, list) or any(not isinstance(item, str) for item in components):
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 optional student components are invalid"
        )
    normalized_components = _normalize_components(components)
    if components != normalized_components:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 optional student components are not canonical"
        )
    count = value.get("optional_component_count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(components):
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 optional student component count mismatch"
        )
    if value.get("selection_source") != "operator-explicit":
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 student representation selection must be operator explicit"
        )

    native_gaussian = primary == "gaussian-splat-optional"
    if value.get("native_gaussian_dependency_selected") is not native_gaussian:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 native Gaussian dependency flag mismatch"
        )
    if target_model == "quest-2" and native_gaussian:
        raise PhotorealP3StudentRepresentationSelectionError(
            "Quest 2 P3 student cannot depend on native Gaussian splats"
        )

    for field, expected in (
        ("teacher_remains_visual_authority", True),
        ("student_may_not_claim_fidelity_above_teacher", True),
        ("fidelity_delta_measurement_required", True),
        ("student_representation_selected", True),
        ("distillation_adapter_required", True),
        ("distillation_adapter_selected", False),
        ("distillation_job_start_authorized", False),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3StudentRepresentationSelectionError(
                f"P3 representation selection authority mismatch: {field}"
            )

    claimed = _sha(
        value.get("p3_student_representation_selection_sha256"),
        label="P3 student representation selection SHA-256",
    )
    if _digest(value, omit="p3_student_representation_selection_sha256") != claimed:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 student representation selection digest mismatch"
        )
    return dict(value)


def require_p3_adapter_selection_authority(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_p3_student_representation_selection(value)
    if validated.get("student_representation_selected") is not True:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 student representation is not selected"
        )
    if validated.get("distillation_adapter_required") is not True:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 distillation adapter requirement is missing"
        )
    if validated.get("distillation_adapter_selected") is not False:
        raise PhotorealP3StudentRepresentationSelectionError(
            "P3 representation selection crossed adapter authority"
        )
    return validated


def build_p3_student_representation_selection_files(
    plan_path: str | Path,
    *,
    primary_representation: str,
    optional_components: Sequence[str],
    output_path: str | Path,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    result = build_p3_student_representation_selection(
        _read_json(plan_path, label="P3 device distillation plan"),
        primary_representation=primary_representation,
        optional_components=optional_components,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP3StudentRepresentationSelectionError(
                f"P3 student representation selection already exists: {output}"
            )
        existing = _read_json(
            output,
            label="existing P3 student representation selection",
        )
        if existing != result:
            raise PhotorealP3StudentRepresentationSelectionError(
                "existing P3 student representation selection differs from canonical current state"
            )
        return existing
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(
            result,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        stream.write("\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind one explicit P3 student representation to an accepted device "
            "distillation plan without selecting an adapter or starting distillation."
        )
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--primary", required=True, choices=PRIMARY_REPRESENTATIONS)
    parser.add_argument(
        "--component",
        action="append",
        default=[],
        choices=OPTIONAL_COMPONENTS,
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)

    try:
        selection = build_p3_student_representation_selection_files(
            args.plan,
            primary_representation=args.primary,
            optional_components=args.component,
            output_path=args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP3StudentRepresentationSelectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "target_model": selection["target_model"],
                "primary_representation": selection["primary_representation"],
                "optional_components": selection["optional_components"],
                "student_representation_selected": True,
                "distillation_adapter_selected": False,
                "distillation_job_start_authorized": False,
                "runtime_acceptance_authority": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
