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
from .photoreal_p3_quest2_eye_component import (
    FORMAT as EYE_COMPONENT_FORMAT,
    PhotorealP3Quest2EyeComponentError,
    graft_specialized_eye_component,
)
from .photoreal_p3_quest2_student_candidate_runner import (
    BLOCKERS as CANDIDATE_BLOCKERS,
    RECEIPT_FORMAT as CANDIDATE_RECEIPT_FORMAT,
    RECEIPT_VERSION as CANDIDATE_RECEIPT_VERSION,
)


FORMAT = "bodyrig-photoreal-p3-quest2-eye-student-receipt"
VERSION = 1
IMPLEMENTED_COMPONENTS = ("specialized-eye-component",)
REMAINING_BLOCKERS = (
    "teacher-derived-hair-component",
    "teacher-student-fidelity-delta-measurement",
    "p3-distillation-manifest",
)
ARTIFACT_KINDS = (
    "student-runtime-package",
    "teacher-derived-basecolor",
)


class PhotorealP3Quest2EyeStudentRunnerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3Quest2EyeStudentRunnerError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3Quest2EyeStudentRunnerError(
            f"{label} must be a JSON object"
        )
    return value


def _candidate_receipt_fields() -> set[str]:
    return {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_sha256",
        "target_model",
        "student_representation",
        "required_student_components",
        "implemented_student_components",
        "student_artifacts",
        "appearance_metrics",
        "artifact_bytes_verified_by_core",
        "staged_teacher_only",
        "student_candidate_complete",
        "p3_distillation_complete",
        "remaining_blockers",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_quest2_student_candidate_receipt_sha256",
    }


def validate_candidate_receipt(
    value: Mapping[str, Any],
    *,
    candidate_output_root: str | Path,
) -> dict[str, Any]:
    if (
        set(value) != _candidate_receipt_fields()
        or value.get("format") != CANDIDATE_RECEIPT_FORMAT
    ):
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 candidate receipt fields/format mismatch"
        )
    try:
        _strict_v1(
            value.get("version"),
            label="Quest2 candidate receipt",
        )
    except Exception as exc:
        raise PhotorealP3Quest2EyeStudentRunnerError(str(exc)) from exc
    if value.get("version") != CANDIDATE_RECEIPT_VERSION:
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 candidate receipt version mismatch"
        )

    _text(
        value.get("performer_id"),
        label="Quest2 candidate performer",
        maximum=256,
    )
    _text(
        value.get("selected_epoch_id"),
        label="Quest2 candidate epoch",
        maximum=256,
    )
    for field in (
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_quest2_student_candidate_sha256",
    ):
        _sha(
            value.get(field),
            label=f"Quest2 candidate receipt {field}",
        )

    if (
        value.get("target_model") != "quest-2"
        or value.get("student_representation") != "skinned-mesh-pbr"
        or value.get("required_student_components")
        != list(REQUIRED_STUDENT_COMPONENTS)
        or value.get("implemented_student_components") != []
        or value.get("remaining_blockers") != list(CANDIDATE_BLOCKERS)
    ):
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 candidate receipt student/component authority mismatch"
        )

    for field, expected in (
        ("artifact_bytes_verified_by_core", True),
        ("staged_teacher_only", True),
        ("student_candidate_complete", True),
        ("p3_distillation_complete", False),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3Quest2EyeStudentRunnerError(
                f"Quest2 candidate receipt authority mismatch: {field}"
            )

    root = Path(candidate_output_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 candidate output root is missing/not regular"
        )
    artifacts = value.get("student_artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 candidate receipt artifact universe is incomplete"
        )
    seen_kind: set[str] = set()
    seen_path: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {
            "kind",
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP3Quest2EyeStudentRunnerError(
                "Quest2 candidate receipt artifact fields mismatch"
            )
        kind = _text(
            raw.get("kind"),
            label="Quest2 candidate artifact kind",
            maximum=64,
        )
        relative = _text(
            raw.get("relative_path"),
            label="Quest2 candidate artifact path",
        ).replace("\\", "/")
        first = relative.split("/", 1)[0]
        if (
            relative.startswith("/")
            or relative.startswith("../")
            or "/../" in f"/{relative}/"
            or ":" in first
        ):
            raise PhotorealP3Quest2EyeStudentRunnerError(
                "Quest2 candidate artifact path escapes output root"
            )
        if (
            kind not in ARTIFACT_KINDS
            or kind in seen_kind
            or relative in seen_path
        ):
            raise PhotorealP3Quest2EyeStudentRunnerError(
                "Quest2 candidate artifact universe is repeated/unsupported"
            )
        seen_kind.add(kind)
        seen_path.add(relative)
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PhotorealP3Quest2EyeStudentRunnerError(
                "Quest2 candidate artifact escapes output root"
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
            raise PhotorealP3Quest2EyeStudentRunnerError(
                f"Quest2 candidate artifact size/path drifted: {relative}"
            )
        observed = _file_sha(path)
        expected_sha = _sha(
            raw.get("sha256"),
            label="Quest2 candidate artifact SHA-256",
        )
        if observed != expected_sha:
            raise PhotorealP3Quest2EyeStudentRunnerError(
                f"Quest2 candidate artifact bytes drifted: {relative}"
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
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 candidate artifact kind universe mismatch"
        )

    claimed = _sha(
        value.get("p3_quest2_student_candidate_receipt_sha256"),
        label="Quest2 candidate receipt SHA-256",
    )
    if _digest(
        value,
        omit="p3_quest2_student_candidate_receipt_sha256",
    ) != claimed:
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 candidate receipt digest mismatch"
        )

    result = dict(value)
    result["student_artifacts"] = sorted(
        normalized,
        key=lambda item: item["relative_path"],
    )
    return result


def _artifact(
    receipt: Mapping[str, Any],
    kind: str,
) -> Mapping[str, Any]:
    for item in receipt["student_artifacts"]:
        if item["kind"] == kind:
            return item
    raise PhotorealP3Quest2EyeStudentRunnerError(
        f"Quest2 candidate artifact is missing: {kind}"
    )


def _eye_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "sourceCandidateReceiptSha256",
        "teacherBasecolorSha256",
        "leftEyeJointIndex",
        "rightEyeJointIndex",
        "leftEyeFaceCount",
        "rightEyeFaceCount",
        "surfaceScale",
        "corneaScale",
        "teacherDerivedAppearance",
        "separateRuntimePrimitives",
        "cornealMaterialApplied",
        "eyelashStatus",
        "physicalFaceCloseupReviewRequired",
        "specializedEyeComponentImplemented",
        "runtimeAcceptanceAuthority",
        "photorealAcceptanceAuthority",
        "productionActivation",
        "outputVrmSha256",
    }
    if set(value) != required or value.get("format") != EYE_COMPONENT_FORMAT:
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 eye component metadata fields/format mismatch"
        )
    if value.get("version") != 1:
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 eye component metadata version mismatch"
        )
    for field in ("sourceCandidateReceiptSha256", "teacherBasecolorSha256", "outputVrmSha256"):
        _sha(value.get(field), label=f"Quest2 eye metadata {field}")
    for field in ("leftEyeFaceCount", "rightEyeFaceCount"):
        raw = value.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 8:
            raise PhotorealP3Quest2EyeStudentRunnerError(
                f"Quest2 eye metadata {field} is invalid"
            )
    for field in ("surfaceScale", "corneaScale"):
        raw = value.get(field)
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw))
            or float(raw) <= 1.0
        ):
            raise PhotorealP3Quest2EyeStudentRunnerError(
                f"Quest2 eye metadata {field} is invalid"
            )
    if (
        value.get("leftEyeJointIndex") != 23
        or value.get("rightEyeJointIndex") != 24
        or value.get("teacherDerivedAppearance") is not True
        or value.get("separateRuntimePrimitives") is not True
        or value.get("cornealMaterialApplied") is not True
        or value.get("eyelashStatus")
        != "teacher-derived-hair-component-pending"
        or value.get("physicalFaceCloseupReviewRequired") is not True
        or value.get("specializedEyeComponentImplemented") is not True
        or value.get("runtimeAcceptanceAuthority") is not False
        or value.get("photorealAcceptanceAuthority") is not False
        or value.get("productionActivation") is not False
    ):
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 eye component metadata crossed authority boundary"
        )
    return dict(value)


def build_eye_student(
    candidate_receipt: Mapping[str, Any],
    *,
    candidate_output_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    candidate = validate_candidate_receipt(
        candidate_receipt,
        candidate_output_root=candidate_output_root,
    )
    source_root = Path(candidate_output_root).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    if destination.exists():
        raise PhotorealP3Quest2EyeStudentRunnerError(
            f"Quest2 eye student output already exists: {destination}"
        )
    destination.mkdir(parents=True)

    avatar_record = _artifact(candidate, "student-runtime-package")
    basecolor_record = _artifact(candidate, "teacher-derived-basecolor")
    avatar_path = source_root / avatar_record["relative_path"]
    basecolor_path = source_root / basecolor_record["relative_path"]
    avatar_bytes = avatar_path.read_bytes()
    basecolor_bytes = basecolor_path.read_bytes()

    try:
        eye_vrm, raw_metadata = graft_specialized_eye_component(
            avatar_bytes,
            teacher_basecolor_png=basecolor_bytes,
            source_candidate_receipt_sha256=candidate[
                "p3_quest2_student_candidate_receipt_sha256"
            ],
            teacher_basecolor_sha256=basecolor_record["sha256"],
        )
    except PhotorealP3Quest2EyeComponentError as exc:
        raise PhotorealP3Quest2EyeStudentRunnerError(str(exc)) from exc

    metadata = _eye_metadata(raw_metadata)
    student_dir = destination / "student"
    student_dir.mkdir()
    avatar_out = student_dir / "avatar.vrm"
    basecolor_out = student_dir / "basecolor.png"
    avatar_out.write_bytes(eye_vrm)
    shutil.copyfile(basecolor_path, basecolor_out)

    if _file_sha(basecolor_out) != basecolor_record["sha256"]:
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 eye stage changed teacher basecolor bytes"
        )
    if _file_sha(avatar_out) != metadata["outputVrmSha256"]:
        raise PhotorealP3Quest2EyeStudentRunnerError(
            "Quest2 eye stage VRM bytes differ after persistence"
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
        "performer_id": candidate["performer_id"],
        "selected_epoch_id": candidate["selected_epoch_id"],
        "teacher_input_sha256": candidate["teacher_input_sha256"],
        "p3_device_distillation_plan_sha256": candidate[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_request_sha256": candidate[
            "p3_device_distillation_request_sha256"
        ],
        "p3_quest2_student_candidate_receipt_sha256": candidate[
            "p3_quest2_student_candidate_receipt_sha256"
        ],
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "required_student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "implemented_student_components": list(IMPLEMENTED_COMPONENTS),
        "eye_component": metadata,
        "student_artifacts": artifacts,
        "artifact_bytes_verified_by_core": True,
        "staged_teacher_only": True,
        "student_candidate_complete": True,
        "specialized_eye_component_complete": True,
        "p3_distillation_complete": False,
        "remaining_blockers": list(REMAINING_BLOCKERS),
        "physical_face_closeup_review_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_quest2_eye_student_receipt_sha256"] = _digest(
        result,
        omit="p3_quest2_eye_student_receipt_sha256",
    )
    receipt_path = destination / "p3-quest2-eye-student-receipt.json"
    receipt_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Graft a teacher-derived specialized eye component onto the "
            "core-verified Quest2 ExAvatar student candidate."
        )
    )
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    parser.add_argument("--candidate-output-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_eye_student(
            _read_json(
                args.candidate_receipt,
                label="Quest2 student candidate receipt",
            ),
            candidate_output_root=args.candidate_output_root,
            output_root=args.output_root,
        )
    except PhotorealP3Quest2EyeStudentRunnerError as exc:
        print(
            f"BodyRig P3 Quest2 specialized eyes: FAIL: {exc}",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "status": "P3_QUEST2_SPECIALIZED_EYES_COMPLETE",
                "implemented_student_components": result[
                    "implemented_student_components"
                ],
                "remaining_blockers": result["remaining_blockers"],
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
