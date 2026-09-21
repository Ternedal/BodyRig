from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p2_exavatar_animation_execution_input import (
    PhotorealP2ExAvatarAnimationExecutionInputError,
    validate_exavatar_animation_execution_input,
)
from .photoreal_p2_heldout_animated_human_review import (
    PhotorealP2HeldoutAnimatedHumanReviewError,
    require_p3_device_distillation_authority,
)


FORMAT = "bodyrig-photoreal-p3-device-distillation-plan"
VERSION = 1
PROFILE_FORMAT = "bodyrig-photoreal-device-target-profile"
PROFILE_VERSION = 1

TARGET_MODELS = ("quest-2", "quest-3", "quest-3s")
CANDIDATE_STUDENT_REPRESENTATIONS = (
    "skinned-mesh-pbr",
    "skinned-mesh-neural-texture",
    "hybrid-mesh-neural-residual",
    "specialized-eye-component",
    "teacher-derived-hair-component",
    "gaussian-splat-optional",
)
FIDELITY_DELTA_DIMENSIONS = (
    "identity_likeness",
    "face_detail",
    "eyes",
    "hair_silhouette_and_appearance",
    "skin_material_response",
    "hands_and_extremities",
    "motion_identity_preservation",
    "temporal_stability",
)

PROFILE_FIELDS = {
    "format",
    "version",
    "operator_supplied",
    "target_family",
    "target_model",
    "target_runtime",
    "target_refresh_hz",
    "max_frame_time_ms",
    "stereo_rendering_required",
    "vr_safe_frame_pacing_required",
    "teacher_quality_ceiling_preserved",
    "fidelity_delta_reporting_required",
    "production_activation",
}

TEACHER_SOURCE_FIELDS = {
    "kind",
    "root_kind",
    "relative_path",
    "size_bytes",
    "sha256",
}


class PhotorealP3DeviceDistillationPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3DeviceDistillationPlanError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3DeviceDistillationPlanError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP3DeviceDistillationPlanError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP3DeviceDistillationPlanError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealP3DeviceDistillationPlanError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3DeviceDistillationPlanError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP3DeviceDistillationPlanError(
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
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device distillation artifact cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP3DeviceDistillationPlanError(
            f"P3 teacher source is missing/not regular: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if (
        clean.startswith("/")
        or clean.startswith("../")
        or "/../" in f"/{clean}/"
        or ":" in first
    ):
        raise PhotorealP3DeviceDistillationPlanError(f"{label} escapes its root")
    return clean


def _verify_file(
    root: Path,
    *,
    kind: str,
    root_kind: str,
    relative_path: Any,
    size_bytes: Any,
    expected_sha256: Any,
) -> dict[str, Any]:
    relative = _relative_path(
        relative_path,
        label=f"P3 {kind} relative path",
    )
    path = (root / Path(relative)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP3DeviceDistillationPlanError(
            f"P3 {kind} path escapes its root"
        ) from exc
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 1
        or not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != size_bytes
    ):
        raise PhotorealP3DeviceDistillationPlanError(
            f"P3 {kind} size/path drifted: {relative}"
        )
    expected = _sha(
        expected_sha256,
        label=f"P3 {kind} SHA-256",
    )
    observed = _file_sha(path)
    if observed != expected:
        raise PhotorealP3DeviceDistillationPlanError(
            f"P3 {kind} bytes drifted: {relative}"
        )
    return {
        "kind": kind,
        "root_kind": root_kind,
        "relative_path": relative,
        "size_bytes": size_bytes,
        "sha256": observed,
    }


def validate_device_target_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != PROFILE_FIELDS:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device target profile fields must match v1 exactly"
        )
    if value.get("format") != PROFILE_FORMAT:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device target profile format/version mismatch"
        )
    _strict_v1(value.get("version"), label="P3 device target profile")
    if value.get("operator_supplied") is not True:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device target profile must be operator supplied"
        )
    if value.get("target_family") != "meta-quest":
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device target family is unsupported"
        )
    model = value.get("target_model")
    if model not in TARGET_MODELS:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device target model is unsupported"
        )
    if value.get("target_runtime") != "standalone":
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device target runtime must be standalone"
        )

    refresh = value.get("target_refresh_hz")
    frame_time = value.get("max_frame_time_ms")
    if (
        isinstance(refresh, bool)
        or not isinstance(refresh, (int, float))
        or not math.isfinite(float(refresh))
        or not 30.0 <= float(refresh) <= 240.0
    ):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device target refresh rate is invalid"
        )
    if (
        isinstance(frame_time, bool)
        or not isinstance(frame_time, (int, float))
        or not math.isfinite(float(frame_time))
        or float(frame_time) <= 0
    ):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device target frame-time budget is invalid"
        )
    refresh_value = round(float(refresh), 6)
    frame_time_value = round(float(frame_time), 6)
    expected_frame_time = round(1000.0 / refresh_value, 6)
    if frame_time_value != expected_frame_time:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 target frame-time budget must equal 1000/target_refresh_hz"
        )

    for field in (
        "stereo_rendering_required",
        "vr_safe_frame_pacing_required",
        "teacher_quality_ceiling_preserved",
        "fidelity_delta_reporting_required",
    ):
        if value.get(field) is not True:
            raise PhotorealP3DeviceDistillationPlanError(
                f"P3 device target requirement missing: {field}"
            )
    if value.get("production_activation") is not False:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device target profile crossed production authority"
        )

    return {
        "format": PROFILE_FORMAT,
        "version": PROFILE_VERSION,
        "operator_supplied": True,
        "target_family": "meta-quest",
        "target_model": str(model),
        "target_runtime": "standalone",
        "target_refresh_hz": refresh_value,
        "max_frame_time_ms": frame_time_value,
        "stereo_rendering_required": True,
        "vr_safe_frame_pacing_required": True,
        "teacher_quality_ceiling_preserved": True,
        "fidelity_delta_reporting_required": True,
        "production_activation": False,
    }


def _teacher_sources(
    execution_input: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    identity_root: str | Path,
) -> list[dict[str, Any]]:
    teacher_root = Path(teacher_output_root).expanduser().resolve()
    identity_dir = Path(identity_root).expanduser().resolve()
    for root, label in (
        (teacher_root, "accepted teacher output root"),
        (identity_dir, "accepted identity export root"),
    ):
        if not root.is_dir() or root.is_symlink():
            raise PhotorealP3DeviceDistillationPlanError(
                f"P3 {label} is missing/not regular: {root}"
            )

    checkpoint = execution_input.get("teacher_checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 execution input lacks teacher checkpoint"
        )
    result = [
        _verify_file(
            teacher_root,
            kind="teacher-checkpoint",
            root_kind="teacher-output",
            relative_path=checkpoint.get("relative_path"),
            size_bytes=checkpoint.get("size_bytes"),
            expected_sha256=checkpoint.get("sha256"),
        )
    ]

    identity = execution_input.get("identity_artifacts")
    if not isinstance(identity, list) or len(identity) != 4:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 execution input identity artifact universe is incomplete"
        )
    for raw in identity:
        if not isinstance(raw, Mapping):
            raise PhotorealP3DeviceDistillationPlanError(
                "P3 identity artifact is invalid"
            )
        kind = _text(
            raw.get("kind"),
            label="P3 identity artifact kind",
            maximum=64,
        )
        result.append(
            _verify_file(
                identity_dir,
                kind=kind,
                root_kind="identity-export",
                relative_path=raw.get("export_relative_path"),
                size_bytes=raw.get("size_bytes"),
                expected_sha256=raw.get("sha256"),
            )
        )

    result.sort(key=lambda item: (item["root_kind"], item["kind"], item["relative_path"]))
    kinds = {item["kind"] for item in result}
    if kinds != {
        "teacher-checkpoint",
        "shape-param",
        "face-offset",
        "joint-offset",
        "locator-offset",
    }:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 teacher source kind universe mismatch"
        )
    return result


def build_p3_device_distillation_plan(
    p2_human_review: Mapping[str, Any],
    execution_input: Mapping[str, Any],
    target_profile: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    identity_root: str | Path,
) -> dict[str, Any]:
    try:
        review = require_p3_device_distillation_authority(p2_human_review)
    except PhotorealP2HeldoutAnimatedHumanReviewError as exc:
        raise PhotorealP3DeviceDistillationPlanError(str(exc)) from exc
    try:
        accepted_input = validate_exavatar_animation_execution_input(execution_input)
    except PhotorealP2ExAvatarAnimationExecutionInputError as exc:
        raise PhotorealP3DeviceDistillationPlanError(
            f"P3 ExAvatar execution-input readback failed: {exc}"
        ) from exc
    profile = validate_device_target_profile(target_profile)

    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
    ):
        if review.get(field) != accepted_input.get(field):
            raise PhotorealP3DeviceDistillationPlanError(
                f"P3 human PASS / teacher input lineage mismatch: {field}"
            )
    execution_input_sha = _sha(
        accepted_input.get("p2_exavatar_animation_execution_input_sha256"),
        label="P3 ExAvatar execution input SHA-256",
    )
    if review.get("p2_exavatar_animation_execution_input_sha256") != execution_input_sha:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 human PASS targets a different ExAvatar execution input"
        )
    checkpoint = accepted_input.get("teacher_checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 ExAvatar execution input checkpoint binding is missing"
        )
    checkpoint_sha = _sha(
        checkpoint.get("sha256"),
        label="P3 accepted checkpoint SHA-256",
    )
    if review.get("consumed_checkpoint_sha256") != checkpoint_sha:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 human PASS targets different frozen teacher checkpoint bytes"
        )

    teacher_sources = _teacher_sources(
        accepted_input,
        teacher_output_root=teacher_output_root,
        identity_root=identity_root,
    )
    target_profile_sha = _digest(profile)

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": review["performer_id"],
        "selected_epoch_id": review["selected_epoch_id"],
        "teacher_input_sha256": review["teacher_input_sha256"],
        "p2_animation_plan_sha256": review["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": execution_input_sha,
        "p2_animated_human_review_sha256": _sha(
            review.get("p2_heldout_animated_human_review_sha256"),
            label="P2 animated human review SHA-256",
        ),
        "accepted_teacher_checkpoint_sha256": checkpoint_sha,
        "teacher_source_artifacts": teacher_sources,
        "teacher_source_artifact_count": len(teacher_sources),
        "teacher_source_bytes_reverified": True,
        "review_media_is_quality_evidence_not_teacher_source": True,
        "target_profile": profile,
        "target_profile_sha256": target_profile_sha,
        "candidate_student_representations": list(
            CANDIDATE_STUDENT_REPRESENTATIONS
        ),
        "gaussian_splat_requires_explicit_target_support": True,
        "teacher_remains_visual_authority": True,
        "student_may_not_claim_fidelity_above_teacher": True,
        "required_fidelity_delta_dimensions": list(FIDELITY_DELTA_DIMENSIONS),
        "required_fidelity_delta_dimension_count": len(FIDELITY_DELTA_DIMENSIONS),
        "fidelity_delta_measurement_required": True,
        "human_runtime_visual_acceptance_required": True,
        "distillation_adapter_required": True,
        "distillation_adapter_selected": False,
        "p3_distillation_execution_authorized": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_device_distillation_plan_sha256"] = _digest(
        result,
        omit="p3_device_distillation_plan_sha256",
    )
    return validate_p3_device_distillation_plan(result)


def validate_p3_device_distillation_plan(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "accepted_teacher_checkpoint_sha256",
        "teacher_source_artifacts",
        "teacher_source_artifact_count",
        "teacher_source_bytes_reverified",
        "review_media_is_quality_evidence_not_teacher_source",
        "target_profile",
        "target_profile_sha256",
        "candidate_student_representations",
        "gaussian_splat_requires_explicit_target_support",
        "teacher_remains_visual_authority",
        "student_may_not_claim_fidelity_above_teacher",
        "required_fidelity_delta_dimensions",
        "required_fidelity_delta_dimension_count",
        "fidelity_delta_measurement_required",
        "human_runtime_visual_acceptance_required",
        "distillation_adapter_required",
        "distillation_adapter_selected",
        "p3_distillation_execution_authorized",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_device_distillation_plan_sha256",
    }
    if set(value) != expected_fields:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device distillation plan fields must match v1 exactly"
        )
    if value.get("format") != FORMAT:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device distillation plan format/version mismatch"
        )
    _strict_v1(value.get("version"), label="P3 device distillation plan")
    _text(value.get("performer_id"), label="P3 performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P3 epoch", maximum=256)
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "accepted_teacher_checkpoint_sha256",
        "target_profile_sha256",
    ):
        _sha(value.get(field), label=f"P3 device distillation plan {field}")

    sources = value.get("teacher_source_artifacts")
    count = value.get("teacher_source_artifact_count")
    if (
        not isinstance(sources, list)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != 5
        or len(sources) != count
    ):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 teacher source artifact count mismatch"
        )
    normalized: list[dict[str, Any]] = []
    seen_paths: set[tuple[str, str]] = set()
    seen_kinds: set[str] = set()
    for raw in sources:
        if not isinstance(raw, Mapping) or set(raw) != TEACHER_SOURCE_FIELDS:
            raise PhotorealP3DeviceDistillationPlanError(
                "P3 teacher source artifact fields must match v1 exactly"
            )
        kind = _text(raw.get("kind"), label="P3 teacher source kind", maximum=64)
        root_kind = _text(
            raw.get("root_kind"),
            label="P3 teacher source root kind",
            maximum=64,
        )
        if root_kind not in {"teacher-output", "identity-export"}:
            raise PhotorealP3DeviceDistillationPlanError(
                "P3 teacher source root kind is invalid"
            )
        relative = _relative_path(
            raw.get("relative_path"),
            label="P3 teacher source relative path",
        )
        key = (root_kind, relative)
        if key in seen_paths or kind in seen_kinds:
            raise PhotorealP3DeviceDistillationPlanError(
                "P3 teacher source artifact universe repeats path/kind"
            )
        seen_paths.add(key)
        seen_kinds.add(kind)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP3DeviceDistillationPlanError(
                "P3 teacher source artifact size is invalid"
            )
        normalized.append(
            {
                "kind": kind,
                "root_kind": root_kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": _sha(
                    raw.get("sha256"),
                    label="P3 teacher source artifact SHA-256",
                ),
            }
        )
    if seen_kinds != {
        "teacher-checkpoint",
        "shape-param",
        "face-offset",
        "joint-offset",
        "locator-offset",
    }:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 teacher source artifact kind universe mismatch"
        )
    if sources != sorted(
        normalized,
        key=lambda item: (item["root_kind"], item["kind"], item["relative_path"]),
    ):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 teacher source artifact universe is not canonical"
        )
    checkpoint_sources = [
        item for item in normalized if item["kind"] == "teacher-checkpoint"
    ]
    if (
        len(checkpoint_sources) != 1
        or checkpoint_sources[0]["root_kind"] != "teacher-output"
        or checkpoint_sources[0]["sha256"]
        != value["accepted_teacher_checkpoint_sha256"]
    ):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 accepted teacher checkpoint binding mismatch"
        )

    profile = value.get("target_profile")
    if not isinstance(profile, Mapping):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 target profile is invalid"
        )
    normalized_profile = validate_device_target_profile(profile)
    if value.get("target_profile_sha256") != _digest(normalized_profile):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 target profile digest mismatch"
        )

    if value.get("candidate_student_representations") != list(
        CANDIDATE_STUDENT_REPRESENTATIONS
    ):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 student representation candidate universe mismatch"
        )
    if value.get("required_fidelity_delta_dimensions") != list(
        FIDELITY_DELTA_DIMENSIONS
    ):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 fidelity delta dimension universe mismatch"
        )
    dimension_count = value.get("required_fidelity_delta_dimension_count")
    if (
        isinstance(dimension_count, bool)
        or not isinstance(dimension_count, int)
        or dimension_count != len(FIDELITY_DELTA_DIMENSIONS)
    ):
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 fidelity delta dimension count mismatch"
        )

    for field, expected in (
        ("teacher_source_bytes_reverified", True),
        ("review_media_is_quality_evidence_not_teacher_source", True),
        ("gaussian_splat_requires_explicit_target_support", True),
        ("teacher_remains_visual_authority", True),
        ("student_may_not_claim_fidelity_above_teacher", True),
        ("fidelity_delta_measurement_required", True),
        ("human_runtime_visual_acceptance_required", True),
        ("distillation_adapter_required", True),
        ("distillation_adapter_selected", False),
        ("p3_distillation_execution_authorized", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3DeviceDistillationPlanError(
                f"P3 device distillation plan authority mismatch: {field}"
            )

    claimed = _sha(
        value.get("p3_device_distillation_plan_sha256"),
        label="P3 device distillation plan SHA-256",
    )
    if _digest(value, omit="p3_device_distillation_plan_sha256") != claimed:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device distillation plan digest mismatch"
        )
    return dict(value)


def require_p3_distillation_execution_authority(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_p3_device_distillation_plan(value)
    if validated.get("p3_distillation_execution_authorized") is not True:
        raise PhotorealP3DeviceDistillationPlanError(
            "P3 device distillation execution is not authorized"
        )
    return validated


def build_p3_device_distillation_plan_files(
    p2_human_review_path: str | Path,
    execution_input_path: str | Path,
    target_profile_path: str | Path,
    *,
    teacher_output_root: str | Path,
    identity_root: str | Path,
    output_path: str | Path,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    result = build_p3_device_distillation_plan(
        _read_json(p2_human_review_path, label="P2 animated human review receipt"),
        _read_json(execution_input_path, label="P2 ExAvatar execution input"),
        _read_json(target_profile_path, label="P3 device target profile"),
        teacher_output_root=teacher_output_root,
        identity_root=identity_root,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP3DeviceDistillationPlanError(
                f"P3 device distillation plan already exists: {output}"
            )
        existing = _read_json(
            output,
            label="existing P3 device distillation plan",
        )
        if existing != result:
            raise PhotorealP3DeviceDistillationPlanError(
                "existing P3 device distillation plan differs from canonical current state"
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
            "Build a Meta Quest P3 distillation plan from an exact human P2 "
            "animated-teacher PASS and the accepted frozen ExAvatar teacher bytes."
        )
    )
    parser.add_argument("--p2-human-review", type=Path, required=True)
    parser.add_argument("--execution-input", type=Path, required=True)
    parser.add_argument("--target-profile", type=Path, required=True)
    parser.add_argument("--teacher-output-root", type=Path, required=True)
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = build_p3_device_distillation_plan_files(
            args.p2_human_review,
            args.execution_input,
            args.target_profile,
            teacher_output_root=args.teacher_output_root,
            identity_root=args.identity_root,
            output_path=args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP3DeviceDistillationPlanError as exc:
        print(f"BodyRig P3 device distillation plan: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "P3_DEVICE_DISTILLATION_EXECUTION_AUTHORIZED",
                "target_model": plan["target_profile"]["target_model"],
                "teacher_source_artifact_count": plan[
                    "teacher_source_artifact_count"
                ],
                "review_media_is_quality_evidence_not_teacher_source": True,
                "p3_distillation_execution_authorized": True,
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
