from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p3_device_distillation_runner import (
    REQUIRED_STUDENT_COMPONENTS,
    _digest,
    _file_sha,
    _sha,
    _strict_v1,
    _text,
)
from .photoreal_p3_quest2_eye_student_runner import (
    ARTIFACT_KINDS,
    FORMAT as EYE_RECEIPT_FORMAT,
    IMPLEMENTED_COMPONENTS as EYE_IMPLEMENTED_COMPONENTS,
    REMAINING_BLOCKERS as EYE_REMAINING_BLOCKERS,
    VERSION as EYE_RECEIPT_VERSION,
    _eye_metadata,
)
from . import photoreal_p3_quest2_hair_component as hair_component_module
from .photoreal_p3_quest2_hair_component import (
    FORMAT as HAIR_COMPONENT_FORMAT,
    PhotorealP3Quest2HairComponentError,
    graft_teacher_hair_component,
)


FORMAT = "bodyrig-photoreal-p3-quest2-hair-student-receipt"
VERSION = 1
HAIR_ENVELOPE_FORMAT = "bodyrig-photoreal-p3-exavatar-quest2-hair-envelope"
IMPLEMENTED_COMPONENTS = (
    "specialized-eye-component",
    "teacher-derived-hair-component",
)
REMAINING_BLOCKERS = (
    "teacher-student-fidelity-delta-measurement",
    "p3-distillation-manifest",
)


class PhotorealP3Quest2HairStudentRunnerError(ValueError):
    pass


def _hair_receipt_fields() -> set[str]:
    return {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_receipt_sha256",
        "p3_quest2_eye_student_receipt_sha256",
        "hair_envelope_sha256",
        "hair_runner_revision_sha256",
        "hair_component_revision_sha256",
        "target_model",
        "student_representation",
        "required_student_components",
        "implemented_student_components",
        "eye_component",
        "hair_component",
        "student_artifacts",
        "artifact_bytes_verified_by_core",
        "staged_teacher_only",
        "student_candidate_complete",
        "specialized_eye_component_complete",
        "teacher_derived_hair_component_complete",
        "p3_distillation_complete",
        "remaining_blockers",
        "physical_face_closeup_review_required",
        "physical_hair_silhouette_review_required",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_quest2_hair_student_receipt_sha256",
    }


def validate_hair_student_receipt(
    value: Mapping[str, Any],
    *,
    hair_output_root: str | Path,
) -> dict[str, Any]:
    if set(value) != _hair_receipt_fields() or value.get("format") != FORMAT:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair receipt fields/format mismatch"
        )
    try:
        _strict_v1(value.get("version"), label="Quest2 hair receipt")
    except Exception as exc:
        raise PhotorealP3Quest2HairStudentRunnerError(str(exc)) from exc
    if value.get("version") != VERSION:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair receipt version mismatch"
        )

    _text(value.get("performer_id"), label="Quest2 hair performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="Quest2 hair epoch", maximum=256)
    for field in (
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_receipt_sha256",
        "p3_quest2_eye_student_receipt_sha256",
        "hair_envelope_sha256",
        "hair_runner_revision_sha256",
        "hair_component_revision_sha256",
        "p3_quest2_hair_student_receipt_sha256",
    ):
        _sha(value.get(field), label=f"Quest2 hair receipt {field}")

    if (
        value.get("target_model") != "quest-2"
        or value.get("student_representation") != "skinned-mesh-pbr"
        or value.get("required_student_components") != list(REQUIRED_STUDENT_COMPONENTS)
        or value.get("implemented_student_components") != list(IMPLEMENTED_COMPONENTS)
        or value.get("remaining_blockers") != list(REMAINING_BLOCKERS)
    ):
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair receipt student/component authority mismatch"
        )

    for field, expected in (
        ("artifact_bytes_verified_by_core", True),
        ("staged_teacher_only", True),
        ("student_candidate_complete", True),
        ("specialized_eye_component_complete", True),
        ("teacher_derived_hair_component_complete", True),
        ("p3_distillation_complete", False),
        ("physical_face_closeup_review_required", True),
        ("physical_hair_silhouette_review_required", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"Quest2 hair receipt authority mismatch: {field}"
            )

    try:
        eye_metadata = _eye_metadata(value.get("eye_component"))
    except Exception as exc:
        raise PhotorealP3Quest2HairStudentRunnerError(str(exc)) from exc

    hair_metadata = value.get("hair_component")
    if not isinstance(hair_metadata, Mapping):
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair component metadata is missing"
        )
    required_hair = {
        "format",
        "version",
        "sourceEyeReceiptSha256",
        "teacherBasecolorSha256",
        "teacherHairEnvelopeSha256",
        "selectionMode",
        "hairFaceCount",
        "hairVertexCount",
        "sourceDerived",
        "generativeGeometry",
        "bodyTopologyModified",
        "separateRuntimePrimitive",
        "teacherDerivedAppearance",
        "physicalSilhouetteReviewRequired",
        "teacherDerivedHairComponentImplemented",
        "separateEyelashGeometryClaimed",
        "runtimeAcceptanceAuthority",
        "photorealAcceptanceAuthority",
        "productionActivation",
        "outputVrmSha256",
    }
    if set(hair_metadata) != required_hair or hair_metadata.get("format") != HAIR_COMPONENT_FORMAT:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair component metadata fields/format mismatch"
        )
    if hair_metadata.get("version") != 1:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair component metadata version mismatch"
        )
    for field in (
        "sourceEyeReceiptSha256",
        "teacherBasecolorSha256",
        "teacherHairEnvelopeSha256",
        "outputVrmSha256",
    ):
        _sha(hair_metadata.get(field), label=f"Quest2 hair component {field}")
    if (
        hair_metadata.get("sourceEyeReceiptSha256")
        != value["p3_quest2_eye_student_receipt_sha256"]
        or hair_metadata.get("teacherHairEnvelopeSha256")
        != value["hair_envelope_sha256"]
    ):
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair component provenance mismatch"
        )
    for field, expected in (
        ("sourceDerived", True),
        ("generativeGeometry", False),
        ("bodyTopologyModified", False),
        ("separateRuntimePrimitive", True),
        ("teacherDerivedAppearance", True),
        ("physicalSilhouetteReviewRequired", True),
        ("teacherDerivedHairComponentImplemented", True),
        ("separateEyelashGeometryClaimed", False),
        ("runtimeAcceptanceAuthority", False),
        ("photorealAcceptanceAuthority", False),
        ("productionActivation", False),
    ):
        if hair_metadata.get(field) is not expected:
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"Quest2 hair component authority mismatch: {field}"
            )

    root = Path(hair_output_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair output root is missing/not regular"
        )
    artifacts = _artifact_records(
        value.get("student_artifacts"),
        root=root,
        label="Quest2 hair",
    )
    avatar = next(
        item for item in artifacts
        if item["kind"] == "student-runtime-package"
    )
    basecolor = next(
        item for item in artifacts
        if item["kind"] == "teacher-derived-basecolor"
    )
    if hair_metadata["outputVrmSha256"] != avatar["sha256"]:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair metadata does not bind current student VRM bytes"
        )
    if hair_metadata["teacherBasecolorSha256"] != basecolor["sha256"]:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair metadata does not bind current basecolor bytes"
        )
    if eye_metadata["outputVrmSha256"] == avatar["sha256"]:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair stage did not materialize distinct student VRM bytes"
        )

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    expected = {item["relative_path"] for item in artifacts} | {
        "p3-quest2-hair-student-receipt.json"
    }
    if actual != expected:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair output artifact universe drifted"
        )

    claimed = value["p3_quest2_hair_student_receipt_sha256"]
    if _digest(value, omit="p3_quest2_hair_student_receipt_sha256") != claimed:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair receipt digest mismatch"
        )

    result = dict(value)
    result["student_artifacts"] = artifacts
    result["eye_component"] = eye_metadata
    result["hair_component"] = dict(hair_metadata)
    return result


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3Quest2HairStudentRunnerError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3Quest2HairStudentRunnerError(f"{label} must be a JSON object")
    return value


def _artifact_records(
    value: Any,
    *,
    root: Path,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        raise PhotorealP3Quest2HairStudentRunnerError(f"{label} artifact universe is incomplete")
    normalized: list[dict[str, Any]] = []
    seen_kind: set[str] = set()
    seen_path: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {
            "kind",
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP3Quest2HairStudentRunnerError(f"{label} artifact fields mismatch")
        kind = _text(raw.get("kind"), label=f"{label} artifact kind", maximum=64)
        relative = _text(raw.get("relative_path"), label=f"{label} artifact path").replace("\\", "/")
        first = relative.split("/", 1)[0]
        if (
            relative.startswith("/")
            or relative.startswith("../")
            or "/../" in f"/{relative}/"
            or ":" in first
        ):
            raise PhotorealP3Quest2HairStudentRunnerError(f"{label} artifact path escapes root")
        if kind not in ARTIFACT_KINDS or kind in seen_kind or relative in seen_path:
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"{label} artifact universe is repeated/unsupported"
            )
        seen_kind.add(kind)
        seen_path.add(relative)
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"{label} artifact escapes root"
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
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"{label} artifact size/path drifted: {relative}"
            )
        observed = _file_sha(path)
        expected = _sha(raw.get("sha256"), label=f"{label} artifact SHA-256")
        if observed != expected:
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"{label} artifact bytes drifted: {relative}"
            )
        normalized.append(
            {
                "kind": kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed,
            }
        )
    if seen_kind != set(ARTIFACT_KINDS):
        raise PhotorealP3Quest2HairStudentRunnerError(f"{label} artifact kind universe mismatch")
    return sorted(normalized, key=lambda item: item["relative_path"])


def _eye_receipt_fields() -> set[str]:
    return {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_receipt_sha256",
        "target_model",
        "student_representation",
        "required_student_components",
        "implemented_student_components",
        "eye_component",
        "student_artifacts",
        "artifact_bytes_verified_by_core",
        "staged_teacher_only",
        "student_candidate_complete",
        "specialized_eye_component_complete",
        "p3_distillation_complete",
        "remaining_blockers",
        "physical_face_closeup_review_required",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_quest2_eye_student_receipt_sha256",
    }


def validate_eye_receipt(
    value: Mapping[str, Any],
    *,
    eye_output_root: str | Path,
) -> dict[str, Any]:
    if set(value) != _eye_receipt_fields() or value.get("format") != EYE_RECEIPT_FORMAT:
        raise PhotorealP3Quest2HairStudentRunnerError("Quest2 eye receipt fields/format mismatch")
    try:
        _strict_v1(value.get("version"), label="Quest2 eye receipt")
    except Exception as exc:
        raise PhotorealP3Quest2HairStudentRunnerError(str(exc)) from exc
    if value.get("version") != EYE_RECEIPT_VERSION:
        raise PhotorealP3Quest2HairStudentRunnerError("Quest2 eye receipt version mismatch")

    _text(value.get("performer_id"), label="Quest2 eye performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="Quest2 eye epoch", maximum=256)
    for field in (
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_receipt_sha256",
        "p3_quest2_eye_student_receipt_sha256",
    ):
        _sha(value.get(field), label=f"Quest2 eye receipt {field}")

    if (
        value.get("target_model") != "quest-2"
        or value.get("student_representation") != "skinned-mesh-pbr"
        or value.get("required_student_components") != list(REQUIRED_STUDENT_COMPONENTS)
        or value.get("implemented_student_components") != list(EYE_IMPLEMENTED_COMPONENTS)
        or value.get("remaining_blockers") != list(EYE_REMAINING_BLOCKERS)
    ):
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 eye receipt student/component authority mismatch"
        )
    for field, expected in (
        ("artifact_bytes_verified_by_core", True),
        ("staged_teacher_only", True),
        ("student_candidate_complete", True),
        ("specialized_eye_component_complete", True),
        ("p3_distillation_complete", False),
        ("physical_face_closeup_review_required", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"Quest2 eye receipt authority mismatch: {field}"
            )

    try:
        eye_metadata = _eye_metadata(value.get("eye_component"))
    except Exception as exc:
        raise PhotorealP3Quest2HairStudentRunnerError(str(exc)) from exc

    root = Path(eye_output_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise PhotorealP3Quest2HairStudentRunnerError("Quest2 eye output root is missing/not regular")
    artifacts = _artifact_records(value.get("student_artifacts"), root=root, label="Quest2 eye")
    avatar = next(item for item in artifacts if item["kind"] == "student-runtime-package")
    if eye_metadata["outputVrmSha256"] != avatar["sha256"]:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 eye metadata does not bind current student VRM bytes"
        )

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    expected = {item["relative_path"] for item in artifacts} | {
        "p3-quest2-eye-student-receipt.json"
    }
    if actual != expected:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 eye output artifact universe drifted before hair stage"
        )

    claimed = value["p3_quest2_eye_student_receipt_sha256"]
    if _digest(value, omit="p3_quest2_eye_student_receipt_sha256") != claimed:
        raise PhotorealP3Quest2HairStudentRunnerError("Quest2 eye receipt digest mismatch")

    result = dict(value)
    result["student_artifacts"] = artifacts
    result["eye_component"] = eye_metadata
    return result


def validate_hair_envelope(
    value: Mapping[str, Any],
    *,
    eye_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_receipt_sha256",
        "teacher_checkpoint_sha256",
        "generator_sha256",
        "body_vertex_count",
        "body_face_count",
        "teacher_point_count",
        "selection_mode",
        "selected_face_count",
        "selected_vertex_count",
        "seed_face_count",
        "body_height",
        "head_search_radius",
        "outward_offset_p50",
        "outward_offset_p95",
        "outward_offset_max",
        "head_footprint_span_body_ratio",
        "vertical_span_body_ratio",
        "selected_faces",
        "source_derived",
        "generative_geometry",
        "body_topology_modified",
        "physical_silhouette_review_required",
        "hair_component_authority",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "hair_envelope_sha256",
    }
    if set(value) != required or value.get("format") != HAIR_ENVELOPE_FORMAT:
        raise PhotorealP3Quest2HairStudentRunnerError("Quest2 hair envelope fields/format mismatch")
    try:
        _strict_v1(value.get("version"), label="Quest2 hair envelope")
    except Exception as exc:
        raise PhotorealP3Quest2HairStudentRunnerError(str(exc)) from exc

    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_receipt_sha256",
    ):
        if value.get(field) != eye_receipt.get(field):
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"Quest2 hair envelope/eye lineage mismatch: {field}"
            )
    for field in ("teacher_checkpoint_sha256", "generator_sha256", "hair_envelope_sha256"):
        _sha(value.get(field), label=f"Quest2 hair envelope {field}")

    for field in (
        "body_vertex_count",
        "body_face_count",
        "teacher_point_count",
        "selected_face_count",
        "selected_vertex_count",
        "seed_face_count",
    ):
        raw = value.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"Quest2 hair envelope {field} is invalid"
            )
    if value["body_vertex_count"] != 10475 or value["selected_face_count"] < 32:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair envelope topology/selection is implausible"
        )
    selected_faces = value.get("selected_faces")
    if not isinstance(selected_faces, list) or len(selected_faces) != value["selected_face_count"]:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair envelope selected-face count differs from payload"
        )

    for field in (
        "body_height",
        "head_search_radius",
        "outward_offset_p50",
        "outward_offset_p95",
        "outward_offset_max",
        "head_footprint_span_body_ratio",
        "vertical_span_body_ratio",
    ):
        raw = value.get(field)
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw))
            or float(raw) < 0.0
        ):
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"Quest2 hair envelope {field} is invalid"
            )
    if value["selection_mode"] not in {
        "strict-teacher-shell",
        "short-hair-teacher-fallback",
    }:
        raise PhotorealP3Quest2HairStudentRunnerError("Quest2 hair envelope selection mode is invalid")
    for field, expected in (
        ("source_derived", True),
        ("generative_geometry", False),
        ("body_topology_modified", False),
        ("physical_silhouette_review_required", True),
        ("hair_component_authority", False),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"Quest2 hair envelope authority mismatch: {field}"
            )

    claimed = value["hair_envelope_sha256"]
    if _digest(value, omit="hair_envelope_sha256") != claimed:
        raise PhotorealP3Quest2HairStudentRunnerError("Quest2 hair envelope digest mismatch")
    return dict(value)


def _hair_metadata(value: Mapping[str, Any], *, envelope: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "sourceEyeReceiptSha256",
        "teacherBasecolorSha256",
        "teacherHairEnvelopeSha256",
        "selectionMode",
        "hairFaceCount",
        "hairVertexCount",
        "sourceDerived",
        "generativeGeometry",
        "bodyTopologyModified",
        "separateRuntimePrimitive",
        "teacherDerivedAppearance",
        "physicalSilhouetteReviewRequired",
        "teacherDerivedHairComponentImplemented",
        "separateEyelashGeometryClaimed",
        "runtimeAcceptanceAuthority",
        "photorealAcceptanceAuthority",
        "productionActivation",
        "outputVrmSha256",
    }
    if set(value) != required or value.get("format") != HAIR_COMPONENT_FORMAT or value.get("version") != 1:
        raise PhotorealP3Quest2HairStudentRunnerError("Quest2 hair component metadata fields/format mismatch")
    for field in (
        "sourceEyeReceiptSha256",
        "teacherBasecolorSha256",
        "teacherHairEnvelopeSha256",
        "outputVrmSha256",
    ):
        _sha(value.get(field), label=f"Quest2 hair metadata {field}")
    if (
        value.get("teacherHairEnvelopeSha256") != envelope["hair_envelope_sha256"]
        or value.get("selectionMode") != envelope["selection_mode"]
        or value.get("hairFaceCount") != envelope["selected_face_count"]
        or value.get("hairVertexCount") != envelope["selected_face_count"] * 3
    ):
        raise PhotorealP3Quest2HairStudentRunnerError("Quest2 hair metadata/envelope mismatch")
    for field, expected in (
        ("sourceDerived", True),
        ("generativeGeometry", False),
        ("bodyTopologyModified", False),
        ("separateRuntimePrimitive", True),
        ("teacherDerivedAppearance", True),
        ("physicalSilhouetteReviewRequired", True),
        ("teacherDerivedHairComponentImplemented", True),
        ("separateEyelashGeometryClaimed", False),
        ("runtimeAcceptanceAuthority", False),
        ("photorealAcceptanceAuthority", False),
        ("productionActivation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3Quest2HairStudentRunnerError(
                f"Quest2 hair metadata authority mismatch: {field}"
            )
    return dict(value)


def build_hair_student(
    eye_receipt: Mapping[str, Any],
    hair_envelope: Mapping[str, Any],
    *,
    eye_output_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    eye = validate_eye_receipt(eye_receipt, eye_output_root=eye_output_root)
    envelope = validate_hair_envelope(hair_envelope, eye_receipt=eye)

    source_root = Path(eye_output_root).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    if destination.exists():
        raise PhotorealP3Quest2HairStudentRunnerError(
            f"Quest2 hair student output already exists: {destination}"
        )
    destination.mkdir(parents=True)

    avatar_record = next(
        item for item in eye["student_artifacts"] if item["kind"] == "student-runtime-package"
    )
    basecolor_record = next(
        item for item in eye["student_artifacts"] if item["kind"] == "teacher-derived-basecolor"
    )
    avatar_path = source_root / avatar_record["relative_path"]
    basecolor_path = source_root / basecolor_record["relative_path"]
    avatar_bytes = avatar_path.read_bytes()
    basecolor_bytes = basecolor_path.read_bytes()

    try:
        hair_vrm, raw_metadata = graft_teacher_hair_component(
            avatar_bytes,
            teacher_basecolor_png=basecolor_bytes,
            teacher_basecolor_sha256=basecolor_record["sha256"],
            hair_envelope=envelope,
            source_eye_receipt_sha256=eye["p3_quest2_eye_student_receipt_sha256"],
        )
    except PhotorealP3Quest2HairComponentError as exc:
        raise PhotorealP3Quest2HairStudentRunnerError(str(exc)) from exc
    metadata = _hair_metadata(raw_metadata, envelope=envelope)

    student_dir = destination / "student"
    student_dir.mkdir()
    avatar_out = student_dir / "avatar.vrm"
    basecolor_out = student_dir / "basecolor.png"
    avatar_out.write_bytes(hair_vrm)
    shutil.copyfile(basecolor_path, basecolor_out)

    if _file_sha(avatar_out) != metadata["outputVrmSha256"]:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair student VRM bytes differ after persistence"
        )
    if _file_sha(basecolor_out) != basecolor_record["sha256"]:
        raise PhotorealP3Quest2HairStudentRunnerError(
            "Quest2 hair stage changed teacher basecolor bytes"
        )

    artifacts = [
        {
            "kind": "student-runtime-package",
            "relative_path": "student/avatar.vrm",
            "size_bytes": avatar_out.stat().st_size,
            "sha256": _file_sha(avatar_out),
        },
        {
            "kind": "teacher-derived-basecolor",
            "relative_path": "student/basecolor.png",
            "size_bytes": basecolor_out.stat().st_size,
            "sha256": _file_sha(basecolor_out),
        },
    ]

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": eye["performer_id"],
        "selected_epoch_id": eye["selected_epoch_id"],
        "teacher_input_sha256": eye["teacher_input_sha256"],
        "p3_device_distillation_plan_sha256": eye["p3_device_distillation_plan_sha256"],
        "p3_device_distillation_request_sha256": eye["p3_device_distillation_request_sha256"],
        "p3_quest2_student_candidate_receipt_sha256": eye[
            "p3_quest2_student_candidate_receipt_sha256"
        ],
        "p3_quest2_eye_student_receipt_sha256": eye[
            "p3_quest2_eye_student_receipt_sha256"
        ],
        "hair_envelope_sha256": envelope["hair_envelope_sha256"],
        "hair_runner_revision_sha256": _file_sha(Path(__file__).resolve()),
        "hair_component_revision_sha256": _file_sha(
            Path(hair_component_module.__file__).resolve()
        ),
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "required_student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "implemented_student_components": list(IMPLEMENTED_COMPONENTS),
        "eye_component": dict(eye["eye_component"]),
        "hair_component": metadata,
        "student_artifacts": artifacts,
        "artifact_bytes_verified_by_core": True,
        "staged_teacher_only": True,
        "student_candidate_complete": True,
        "specialized_eye_component_complete": True,
        "teacher_derived_hair_component_complete": True,
        "p3_distillation_complete": False,
        "remaining_blockers": list(REMAINING_BLOCKERS),
        "physical_face_closeup_review_required": True,
        "physical_hair_silhouette_review_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_quest2_hair_student_receipt_sha256"] = _digest(
        result,
        omit="p3_quest2_hair_student_receipt_sha256",
    )
    receipt_path = destination / "p3-quest2-hair-student-receipt.json"
    receipt_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Graft an exact ExAvatar-teacher-derived connected hair shell onto "
            "the core-verified Quest2 specialized-eye student."
        )
    )
    parser.add_argument("--eye-receipt", type=Path, required=True)
    parser.add_argument("--eye-output-root", type=Path, required=True)
    parser.add_argument("--hair-envelope", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        result = build_hair_student(
            _read_json(args.eye_receipt, label="Quest2 eye student receipt"),
            _read_json(args.hair_envelope, label="Quest2 teacher hair envelope"),
            eye_output_root=args.eye_output_root,
            output_root=args.output_root,
        )
    except (OSError, PhotorealP3Quest2HairStudentRunnerError) as exc:
        print(f"BodyRig P3 Quest2 teacher hair: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P3_QUEST2_TEACHER_HAIR_COMPLETE",
                "implemented_student_components": result["implemented_student_components"],
                "remaining_blockers": result["remaining_blockers"],
                "physical_hair_silhouette_review_required": True,
                "p3_distillation_complete": False,
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
