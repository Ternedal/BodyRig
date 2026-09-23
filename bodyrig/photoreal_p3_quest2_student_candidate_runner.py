from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .bridges.sith_pbr_material import PBR_METHOD, PbrMaterialError, _read_glb
from .logged_process import LoggedProcessError, run_logged_process
from .photoreal_p3_device_distillation_runner import (
    REQUIRED_STUDENT_COMPONENTS,
    PhotorealP3DeviceDistillationRunnerError,
    _digest,
    _file_sha,
    _materialize_verified_adapter_command,
    _read_json,
    _safe_child,
    _sha,
    _strict_v1,
    _text,
    _verify_adapter_entrypoint,
    build_distillation_request,
    stage_teacher_sources,
    validate_distillation_config,
)


CANDIDATE_FORMAT = "bodyrig-photoreal-p3-exavatar-quest2-student-candidate"
CANDIDATE_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p3-quest2-student-candidate-receipt"
RECEIPT_VERSION = 1

BLOCKERS = (
    "specialized-eye-component",
    "teacher-derived-hair-component",
    "teacher-student-fidelity-delta-measurement",
    "p3-distillation-manifest",
)
ARTIFACT_KINDS = (
    "student-runtime-package",
    "teacher-derived-basecolor",
)
APPEARANCE_METRIC_FIELDS = {
    "appearance_method",
    "canonical_uv_template_sha256",
    "teacher_point_count",
    "baked_basecolor_sha256",
    "bake_width",
    "bake_height",
    "bake_occupied_texel_count",
    "bake_occupied_ratio",
    "bake_padded_texel_ratio",
    "bake_gutter_pixels",
    "teacher_point_distance_mean",
    "teacher_point_distance_p95",
    "teacher_point_distance_max",
}


class PhotorealP3Quest2StudentCandidateRunnerError(ValueError):
    pass


def _finite_nonnegative(value: Any, *, label: str) -> float:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            f"{label} is invalid"
        )
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            f"{label} is invalid"
        )
    return result


def _validate_appearance_metrics(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != APPEARANCE_METRIC_FIELDS:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate appearance metrics fields must match v1 exactly"
        )
    if raw.get("appearance_method") != (
        "exavatar-gaussian-nearest-canonical-uv-v1"
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate appearance method is not canonical"
        )
    normalized: dict[str, Any] = {
        "appearance_method": raw["appearance_method"],
        "canonical_uv_template_sha256": _sha(
            raw.get("canonical_uv_template_sha256"),
            label="Quest2 canonical UV template SHA-256",
        ),
        "baked_basecolor_sha256": _sha(
            raw.get("baked_basecolor_sha256"),
            label="Quest2 baked basecolor SHA-256",
        ),
    }
    for field in sorted(
        APPEARANCE_METRIC_FIELDS
        - {
            "appearance_method",
            "canonical_uv_template_sha256",
            "baked_basecolor_sha256",
        }
    ):
        normalized[field] = _finite_nonnegative(
            raw.get(field),
            label=f"Quest2 candidate appearance metric {field}",
        )
    if normalized["teacher_point_count"] < 10475:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate teacher point universe is too small"
        )
    if normalized["bake_width"] < 256 or normalized["bake_height"] < 256:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate baked texture is implausibly small"
        )
    if not 0.0 < normalized["bake_occupied_ratio"] <= 1.0:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate UV occupancy is invalid"
        )
    if not 0.0 < normalized["bake_padded_texel_ratio"] <= 1.0:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate padded UV occupancy is invalid"
        )
    return normalized


def _validate_runtime_avatar_contract(path: Path) -> None:
    try:
        document, _binary = _read_glb(path.read_bytes())
    except (OSError, PbrMaterialError) as exc:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            f"Quest2 candidate runtime avatar is invalid: {exc}"
        ) from exc

    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    refinement = bodyrig.get("materialRefinement") if isinstance(bodyrig, Mapping) else None
    if (
        not isinstance(bodyrig, Mapping)
        or bodyrig.get("placeholder") is not False
        or bodyrig.get("sourceDerivedVisualIdentity") is not True
        or not isinstance(refinement, Mapping)
        or refinement.get("method") != PBR_METHOD
        or refinement.get("sourceDerivedHeuristic") is not True
        or refinement.get("physicalMeasurement") is not False
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate runtime avatar lacks canonical source-derived PBR authority"
        )

    materials = document.get("materials")
    meshes = document.get("meshes")
    accessors = document.get("accessors")
    if (
        not isinstance(materials, list)
        or len(materials) != 1
        or not isinstance(materials[0], Mapping)
        or not isinstance(meshes, list)
        or len(meshes) != 1
        or not isinstance(meshes[0], Mapping)
        or not isinstance(accessors, list)
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate runtime avatar material/mesh contract is invalid"
        )
    material = materials[0]
    pbr = material.get("pbrMetallicRoughness")
    normal = material.get("normalTexture")
    if (
        not isinstance(pbr, Mapping)
        or not isinstance(normal, Mapping)
        or isinstance(normal.get("index"), bool)
        or not isinstance(normal.get("index"), int)
        or not isinstance(pbr.get("metallicRoughnessTexture"), Mapping)
        or isinstance(pbr["metallicRoughnessTexture"].get("index"), bool)
        or not isinstance(pbr["metallicRoughnessTexture"].get("index"), int)
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate runtime avatar lacks normal/roughness render payload"
        )

    primitives = meshes[0].get("primitives")
    if not isinstance(primitives, list) or len(primitives) != 1 or not isinstance(primitives[0], Mapping):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate runtime avatar body primitive is invalid"
        )
    attrs = primitives[0].get("attributes")
    if not isinstance(attrs, Mapping):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate runtime avatar body attributes are missing"
        )
    position_index = attrs.get("POSITION")
    source_index = attrs.get("_BODYRIG_SOURCE_VERTEX")
    if (
        isinstance(position_index, bool)
        or not isinstance(position_index, int)
        or isinstance(source_index, bool)
        or not isinstance(source_index, int)
        or not 0 <= position_index < len(accessors)
        or not 0 <= source_index < len(accessors)
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate runtime avatar lacks source-vertex geometry authority"
        )
    position = accessors[position_index]
    source = accessors[source_index]
    if (
        not isinstance(position, Mapping)
        or not isinstance(source, Mapping)
        or position.get("componentType") != 5126
        or position.get("type") != "VEC3"
        or source.get("componentType") != 5123
        or source.get("type") != "SCALAR"
        or source.get("count") != position.get("count")
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate source-vertex authority does not match body positions"
        )


def validate_candidate_manifest(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "target_model",
        "adapter",
        "adapter_revision",
        "student_representation",
        "required_student_components",
        "implemented_student_components",
        "geometry_source",
        "appearance_source",
        "teacher_checkpoint_sha256",
        "student_artifacts",
        "appearance_metrics",
        "teacher_point_count",
        "body_vertex_count",
        "body_face_count",
        "joint_count",
        "student_candidate_complete",
        "p3_distillation_complete",
        "remaining_blockers",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_quest2_student_candidate_sha256",
    }
    if set(value) != expected_fields or value.get("format") != CANDIDATE_FORMAT:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student candidate fields/format mismatch"
        )
    try:
        _strict_v1(value.get("version"), label="Quest2 student candidate")
    except PhotorealP3DeviceDistillationRunnerError as exc:
        raise PhotorealP3Quest2StudentCandidateRunnerError(str(exc)) from exc

    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "adapter",
        "adapter_revision",
        "student_representation",
    ):
        if value.get(field) != request.get(field):
            raise PhotorealP3Quest2StudentCandidateRunnerError(
                f"Quest2 student candidate provenance mismatch: {field}"
            )

    if (
        value.get("target_model") != "quest-2"
        or request.get("target_profile", {}).get("target_model") != "quest-2"
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student candidate target binding mismatch"
        )
    if value.get("student_representation") != "skinned-mesh-pbr":
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student candidate representation is not skinned-mesh-pbr"
        )
    if value.get("required_student_components") != list(
        REQUIRED_STUDENT_COMPONENTS
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student candidate required components mismatch"
        )
    if value.get("implemented_student_components") != []:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate v1 may not claim implemented eye/hair components"
        )
    if value.get("geometry_source") != (
        "accepted-exavatar-refined-first-subdivision-gaussian-surface"
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student geometry source is not refined ExAvatar source geometry"
        )
    if value.get("appearance_source") != (
        "accepted-exavatar-refined-zero-pose-gaussian-rgb"
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student appearance source is not canonical"
        )

    staged = request.get("staged_teacher_sources")
    if not isinstance(staged, list):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate request lacks staged teacher sources"
        )
    checkpoint_sha = None
    for item in staged:
        if isinstance(item, Mapping) and item.get("kind") == "teacher-checkpoint":
            checkpoint_sha = item.get("sha256")
            break
    if value.get("teacher_checkpoint_sha256") != checkpoint_sha:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student checkpoint binding mismatch"
        )

    artifacts = value.get("student_artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate student artifact universe is incomplete"
        )
    normalized_artifacts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_kinds: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {
            "kind",
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP3Quest2StudentCandidateRunnerError(
                "Quest2 candidate artifact fields must match v1 exactly"
            )
        kind = _text(
            raw.get("kind"),
            label="Quest2 candidate artifact kind",
            maximum=64,
        )
        if kind not in ARTIFACT_KINDS or kind in seen_kinds:
            raise PhotorealP3Quest2StudentCandidateRunnerError(
                "Quest2 candidate artifact kind universe mismatch"
            )
        seen_kinds.add(kind)
        relative, path = _safe_child(
            output_dir,
            raw.get("relative_path"),
            label="Quest2 candidate artifact path",
        )
        if relative in seen_paths:
            raise PhotorealP3Quest2StudentCandidateRunnerError(
                "Quest2 candidate repeats student artifact path"
            )
        seen_paths.add(relative)
        size = raw.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
        ):
            raise PhotorealP3Quest2StudentCandidateRunnerError(
                f"Quest2 candidate artifact size/path mismatch: {relative}"
            )
        observed = _file_sha(path)
        expected = _sha(
            raw.get("sha256"),
            label="Quest2 candidate artifact SHA-256",
        )
        if observed != expected:
            raise PhotorealP3Quest2StudentCandidateRunnerError(
                f"Quest2 candidate artifact SHA-256 mismatch: {relative}"
            )
        normalized_artifacts.append(
            {
                "kind": kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed,
            }
        )
    if seen_kinds != set(ARTIFACT_KINDS):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate artifact kind universe mismatch"
        )

    runtime_avatar = next(
        item
        for item in normalized_artifacts
        if item["kind"] == "student-runtime-package"
    )
    _runtime_relative, runtime_path = _safe_child(
        output_dir,
        runtime_avatar["relative_path"],
        label="Quest2 candidate runtime avatar",
    )
    _validate_runtime_avatar_contract(runtime_path)

    actual = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
        and path.resolve()
        != (output_dir / "quest2-student-candidate.json").resolve()
    }
    if actual != seen_paths:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate output artifact universe differs from manifest"
        )

    appearance = _validate_appearance_metrics(value.get("appearance_metrics"))
    basecolor = next(
        item
        for item in normalized_artifacts
        if item["kind"] == "teacher-derived-basecolor"
    )
    if appearance["baked_basecolor_sha256"] != basecolor["sha256"]:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate basecolor metric/artifact digest mismatch"
        )

    for field, expected in (
        ("teacher_point_count", int(appearance["teacher_point_count"])),
        ("joint_count", 55),
    ):
        raw = value.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw != expected:
            raise PhotorealP3Quest2StudentCandidateRunnerError(
                f"Quest2 candidate count mismatch: {field}"
            )
    vertex_count = value.get("body_vertex_count")
    if (
        isinstance(vertex_count, bool)
        or not isinstance(vertex_count, int)
        or not 10475 < vertex_count <= 65535
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate body vertex count is not a first-subdivision surface"
        )
    face_count = value.get("body_face_count")
    if (
        isinstance(face_count, bool)
        or not isinstance(face_count, int)
        or face_count != 20908 * 4
    ):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate body face count is not the canonical first subdivision"
        )

    if value.get("remaining_blockers") != list(BLOCKERS):
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate remaining blocker universe mismatch"
        )
    for field, expected in (
        ("student_candidate_complete", True),
        ("p3_distillation_complete", False),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3Quest2StudentCandidateRunnerError(
                f"Quest2 candidate authority mismatch: {field}"
            )

    claimed = _sha(
        value.get("p3_quest2_student_candidate_sha256"),
        label="Quest2 student candidate SHA-256",
    )
    if _digest(
        value,
        omit="p3_quest2_student_candidate_sha256",
    ) != claimed:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student candidate digest mismatch"
        )

    normalized = dict(value)
    normalized["student_artifacts"] = sorted(
        normalized_artifacts,
        key=lambda item: item["relative_path"],
    )
    normalized["appearance_metrics"] = appearance
    return normalized


def build_candidate_receipt(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "performer_id": candidate["performer_id"],
        "selected_epoch_id": candidate["selected_epoch_id"],
        "teacher_input_sha256": candidate["teacher_input_sha256"],
        "p3_device_distillation_plan_sha256": candidate[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_request_sha256": candidate[
            "p3_device_distillation_request_sha256"
        ],
        "p3_quest2_student_candidate_sha256": candidate[
            "p3_quest2_student_candidate_sha256"
        ],
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "required_student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "implemented_student_components": [],
        "student_artifacts": list(candidate["student_artifacts"]),
        "appearance_metrics": dict(candidate["appearance_metrics"]),
        "artifact_bytes_verified_by_core": True,
        "staged_teacher_only": True,
        "student_candidate_complete": True,
        "p3_distillation_complete": False,
        "remaining_blockers": list(BLOCKERS),
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_quest2_student_candidate_receipt_sha256"] = _digest(
        result,
        omit="p3_quest2_student_candidate_receipt_sha256",
    )
    return result


def run_external_candidate(
    config: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    identity_root: str | Path,
    workspace: str | Path,
    config_root: str | Path | None = None,
) -> dict[str, Any]:
    try:
        config = validate_distillation_config(config)
    except PhotorealP3DeviceDistillationRunnerError as exc:
        raise PhotorealP3Quest2StudentCandidateRunnerError(str(exc)) from exc
    if config["student_representation"] != "skinned-mesh-pbr":
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate runner requires skinned-mesh-pbr"
        )

    root_for_config = (
        Path.cwd().resolve()
        if config_root is None
        else Path(config_root).expanduser().resolve()
    )
    try:
        entrypoint = _verify_adapter_entrypoint(
            config,
            config_root=root_for_config,
        )
        verified_command = _materialize_verified_adapter_command(
            config,
            config_root=root_for_config,
            entrypoint=entrypoint,
        )
    except PhotorealP3DeviceDistillationRunnerError as exc:
        raise PhotorealP3Quest2StudentCandidateRunnerError(str(exc)) from exc

    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            f"Quest2 candidate workspace already exists: {root}"
        )
    root.mkdir(parents=True)
    staged_root = root / "staged-teacher"
    output_dir = root / "output"
    output_dir.mkdir()
    request_path = root / "request.json"
    log_path = root / "adapter.log"

    try:
        staged_sources = stage_teacher_sources(
            plan,
            teacher_output_root=teacher_output_root,
            identity_root=identity_root,
            staged_root=staged_root,
        )
        request = build_distillation_request(
            config,
            plan,
            staged_teacher_sources=staged_sources,
        )
    except PhotorealP3DeviceDistillationRunnerError as exc:
        raise PhotorealP3Quest2StudentCandidateRunnerError(str(exc)) from exc

    if request["target_profile"]["target_model"] != "quest-2":
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate runner received a non-Quest2 plan"
        )

    request_path.write_text(
        json.dumps(
            request,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    invoke = [
        *verified_command,
        "--bodyrig-request",
        str(request_path),
        "--bodyrig-teacher-root",
        str(staged_root),
        "--bodyrig-output",
        str(output_dir),
        "--bodyrig-adapter",
        config["adapter"],
        "--bodyrig-revision",
        config["revision"],
        "--bodyrig-student-representation",
        config["student_representation"],
        "--bodyrig-student-components",
        ",".join(config["student_components"]),
    ]
    try:
        completed = run_logged_process(
            invoke,
            log_path=log_path,
            timeout_seconds=config["timeout_seconds"],
        )
    except subprocess.TimeoutExpired as exc:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student candidate adapter timed out"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            f"Quest2 student candidate adapter could not complete: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            f"Quest2 student candidate adapter failed with exit code {completed.returncode}"
        )

    candidate_path = output_dir / "quest2-student-candidate.json"
    if not candidate_path.is_file() or candidate_path.is_symlink():
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 student candidate adapter produced no candidate manifest"
        )
    candidate = validate_candidate_manifest(
        _read_json(candidate_path, label="Quest2 student candidate manifest"),
        request=request,
        output_dir=output_dir,
    )

    for raw_source in staged_sources:
        _, path = _safe_child(
            staged_root,
            raw_source["relative_path"],
            label="Quest2 candidate staged teacher post-run path",
        )
        if (
            path.stat().st_size != raw_source["size_bytes"]
            or _file_sha(path) != raw_source["sha256"]
        ):
            raise PhotorealP3Quest2StudentCandidateRunnerError(
                "Quest2 candidate adapter mutated staged teacher source bytes"
            )
    actual_staged = {
        path.relative_to(staged_root).as_posix()
        for path in staged_root.rglob("*")
        if path.is_file()
    }
    if actual_staged != {
        item["relative_path"]
        for item in staged_sources
    }:
        raise PhotorealP3Quest2StudentCandidateRunnerError(
            "Quest2 candidate adapter changed staged teacher artifact universe"
        )

    receipt = build_candidate_receipt(candidate)
    receipt_path = root / "p3-quest2-student-candidate-receipt.json"
    receipt_path.write_text(
        json.dumps(
            receipt,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real ExAvatar-derived Quest2 base student candidate "
            "without granting final P3/runtime authority."
        )
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--teacher-output-root", type=Path, required=True)
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        config_path = args.config.expanduser().resolve()
        receipt = run_external_candidate(
            _read_json(config_path, label="Quest2 candidate adapter config"),
            _read_json(args.plan, label="P3 distillation plan"),
            teacher_output_root=args.teacher_output_root,
            identity_root=args.identity_root,
            workspace=args.workspace,
            config_root=config_path.parent,
        )
    except PhotorealP3Quest2StudentCandidateRunnerError as exc:
        print(
            f"BodyRig P3 Quest2 student candidate: FAIL: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "P3_QUEST2_STUDENT_CANDIDATE_COMPLETE",
                "student_candidate_complete": True,
                "p3_distillation_complete": False,
                "remaining_blockers": receipt["remaining_blockers"],
                "artifact_bytes_verified_by_core": True,
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
