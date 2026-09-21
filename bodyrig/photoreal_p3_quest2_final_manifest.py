from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p3_device_distillation_plan import (
    FIDELITY_DELTA_DIMENSIONS,
    validate_device_target_profile,
)
from .photoreal_p3_device_distillation_runner import (
    REQUEST_FORMAT,
    REQUEST_VERSION,
    REQUIRED_STUDENT_COMPONENTS,
    SOURCE_FIELDS,
    RESULT_FORMAT,
    RESULT_VERSION,
    _digest,
    _file_sha,
    _sha,
    _strict_v1,
    _text,
    build_execution_receipt,
    validate_distillation_result,
)
from .photoreal_p3_quest2_fidelity_delta import (
    FORMAT as FIDELITY_FORMAT,
    canonical_manifest_measurements,
    validate_fidelity_delta_evidence,
)
from .photoreal_p3_quest2_hair_student_runner import (
    FORMAT as HAIR_RECEIPT_FORMAT,
    validate_hair_student_receipt,
)


PROVENANCE_FORMAT = "bodyrig-photoreal-p3-quest2-modular-provenance"
PROVENANCE_VERSION = 1
WORKSPACE_FORMAT = "bodyrig-photoreal-p3-quest2-final-distillation-workspace"
WORKSPACE_VERSION = 1


class PhotorealP3Quest2FinalManifestError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3Quest2FinalManifestError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3Quest2FinalManifestError(
            f"{label} must be a JSON object"
        )
    return value


def _validate_request(value: Mapping[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "p3_device_distillation_plan_sha256",
        "target_profile",
        "target_profile_sha256",
        "target_model",
        "adapter",
        "adapter_revision",
        "student_representation",
        "student_components",
        "staged_teacher_sources",
        "required_fidelity_delta_dimensions",
        "teacher_remains_visual_authority",
        "student_may_not_claim_fidelity_above_teacher",
        "staged_teacher_only",
        "p3_distillation_execution_authorized",
        "human_runtime_visual_acceptance_required",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_device_distillation_request_sha256",
    }
    if set(value) != expected_fields or value.get("format") != REQUEST_FORMAT:
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final request fields/format mismatch"
        )
    try:
        _strict_v1(value.get("version"), label="P3 final request")
    except Exception as exc:
        raise PhotorealP3Quest2FinalManifestError(str(exc)) from exc
    if value.get("version") != REQUEST_VERSION:
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final request version mismatch"
        )
    _text(value.get("performer_id"), label="P3 final performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P3 final epoch", maximum=256)
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "p3_device_distillation_plan_sha256",
        "target_profile_sha256",
        "adapter_revision",
        "p3_device_distillation_request_sha256",
    ):
        _sha(value.get(field), label=f"P3 final request {field}")
    _text(value.get("adapter"), label="P3 final request adapter", maximum=80)

    if (
        value.get("target_model") != "quest-2"
        or value.get("student_representation") != "skinned-mesh-pbr"
        or value.get("student_components") != list(REQUIRED_STUDENT_COMPONENTS)
        or value.get("required_fidelity_delta_dimensions")
        != list(FIDELITY_DELTA_DIMENSIONS)
    ):
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final request target/student contract mismatch"
        )

    profile = value.get("target_profile")
    if not isinstance(profile, Mapping):
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final request target profile is invalid"
        )
    try:
        normalized_profile = validate_device_target_profile(profile)
    except Exception as exc:
        raise PhotorealP3Quest2FinalManifestError(str(exc)) from exc
    if normalized_profile.get("target_model") != "quest-2":
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final request target profile is not Quest 2"
        )
    if _digest(normalized_profile) != value["target_profile_sha256"]:
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final request target profile digest mismatch"
        )

    sources = value.get("staged_teacher_sources")
    if not isinstance(sources, list) or len(sources) != 5:
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final request staged teacher universe is incomplete"
        )
    normalized_sources: list[dict[str, Any]] = []
    seen_kind: set[str] = set()
    seen_path: set[str] = set()
    expected_roots = {
        "teacher-checkpoint": "teacher-output",
        "shape-param": "identity-export",
        "face-offset": "identity-export",
        "joint-offset": "identity-export",
        "locator-offset": "identity-export",
    }
    for raw in sources:
        if not isinstance(raw, Mapping) or set(raw) != SOURCE_FIELDS:
            raise PhotorealP3Quest2FinalManifestError(
                "P3 final request staged teacher fields mismatch"
            )
        kind = _text(
            raw.get("kind"),
            label="P3 final staged teacher kind",
            maximum=64,
        )
        root_kind = _text(
            raw.get("root_kind"),
            label="P3 final staged teacher root kind",
            maximum=64,
        )
        relative = _text(
            raw.get("relative_path"),
            label="P3 final staged teacher path",
        ).replace("\\", "/")
        first = relative.split("/", 1)[0]
        if (
            kind not in expected_roots
            or expected_roots[kind] != root_kind
            or kind in seen_kind
            or relative in seen_path
            or relative.startswith("/")
            or relative.startswith("../")
            or "/../" in f"/{relative}/"
            or ":" in first
        ):
            raise PhotorealP3Quest2FinalManifestError(
                "P3 final staged teacher universe is repeated/unsafe"
            )
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP3Quest2FinalManifestError(
                "P3 final staged teacher size is invalid"
            )
        seen_kind.add(kind)
        seen_path.add(relative)
        normalized_sources.append(
            {
                "kind": kind,
                "root_kind": root_kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": _sha(
                    raw.get("sha256"),
                    label="P3 final staged teacher SHA-256",
                ),
            }
        )
    if seen_kind != set(expected_roots):
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final staged teacher kind universe mismatch"
        )
    normalized_sources.sort(
        key=lambda item: (
            item["root_kind"],
            item["kind"],
            item["relative_path"],
        )
    )
    if sources != normalized_sources:
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final staged teacher universe is not canonical"
        )

    for field, expected in (
        ("teacher_remains_visual_authority", True),
        ("student_may_not_claim_fidelity_above_teacher", True),
        ("staged_teacher_only", True),
        ("p3_distillation_execution_authorized", True),
        ("human_runtime_visual_acceptance_required", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3Quest2FinalManifestError(
                f"P3 final request authority mismatch: {field}"
            )

    claimed = value["p3_device_distillation_request_sha256"]
    if _digest(value, omit="p3_device_distillation_request_sha256") != claimed:
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final request digest mismatch"
        )
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _artifact(path: Path, root: Path, *, kind: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP3Quest2FinalManifestError(
            f"P3 final artifact is missing/not regular: {path}"
        )
    return {
        "kind": kind,
        "relative_path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha(path),
    }


def _consumed_sources(request: Mapping[str, Any]) -> list[dict[str, str]]:
    result = [
        {
            "kind": item["kind"],
            "root_kind": item["root_kind"],
            "relative_path": item["relative_path"],
            "sha256": item["sha256"],
        }
        for item in request["staged_teacher_sources"]
    ]
    result.sort(
        key=lambda item: (
            item["root_kind"],
            item["kind"],
            item["relative_path"],
        )
    )
    return result


def _build_provenance(
    *,
    request: Mapping[str, Any],
    hair: Mapping[str, Any],
    fidelity: Mapping[str, Any],
    request_file_sha256: str,
    hair_receipt_file_sha256: str,
    fidelity_file_sha256: str,
    source_avatar_sha256: str,
    source_basecolor_sha256: str,
    copied_avatar_sha256: str,
    copied_basecolor_sha256: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "format": PROVENANCE_FORMAT,
        "version": PROVENANCE_VERSION,
        "performer_id": hair["performer_id"],
        "selected_epoch_id": hair["selected_epoch_id"],
        "teacher_input_sha256": hair["teacher_input_sha256"],
        "p3_device_distillation_plan_sha256": hair[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_request_sha256": request[
            "p3_device_distillation_request_sha256"
        ],
        "p3_quest2_student_candidate_receipt_sha256": hair[
            "p3_quest2_student_candidate_receipt_sha256"
        ],
        "p3_quest2_eye_student_receipt_sha256": hair[
            "p3_quest2_eye_student_receipt_sha256"
        ],
        "p3_quest2_hair_student_receipt_sha256": hair[
            "p3_quest2_hair_student_receipt_sha256"
        ],
        "p3_quest2_fidelity_delta_evidence_sha256": fidelity[
            "p3_quest2_fidelity_delta_evidence_sha256"
        ],
        "request_file_sha256": request_file_sha256,
        "hair_receipt_file_sha256": hair_receipt_file_sha256,
        "fidelity_evidence_file_sha256": fidelity_file_sha256,
        "teacher_checkpoint_sha256": fidelity["teacher_checkpoint_sha256"],
        "base_adapter": request["adapter"],
        "base_adapter_revision": request["adapter_revision"],
        "hair_runner_revision_sha256": hair["hair_runner_revision_sha256"],
        "hair_component_revision_sha256": hair["hair_component_revision_sha256"],
        "manifest_builder_revision_sha256": _file_sha(Path(__file__).resolve()),
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "implemented_student_components": list(
            hair["implemented_student_components"]
        ),
        "source_student_avatar_sha256": source_avatar_sha256,
        "source_student_basecolor_sha256": source_basecolor_sha256,
        "copied_student_avatar_sha256": copied_avatar_sha256,
        "copied_student_basecolor_sha256": copied_basecolor_sha256,
        "student_copy_byte_identical": (
            source_avatar_sha256 == copied_avatar_sha256
            and source_basecolor_sha256 == copied_basecolor_sha256
        ),
        "specialized_eye_component_complete": True,
        "teacher_derived_hair_component_complete": True,
        "fidelity_delta_complete": True,
        "distillation_complete": True,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    if result["student_copy_byte_identical"] is not True:
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final student copy differs from exact hair-stage artifacts"
        )
    result["p3_quest2_modular_provenance_sha256"] = _digest(
        result,
        omit="p3_quest2_modular_provenance_sha256",
    )
    return result


def materialize_final_distillation(
    *,
    candidate_workspace: str | Path,
    hair_output_root: str | Path,
    fidelity_evidence_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    candidate_root = Path(candidate_workspace).expanduser().resolve()
    hair_root = Path(hair_output_root).expanduser().resolve()
    fidelity_path = Path(fidelity_evidence_path).expanduser().resolve()
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealP3Quest2FinalManifestError(
            f"P3 final workspace already exists: {root}"
        )

    request_path = candidate_root / "request.json"
    hair_receipt_path = hair_root / "p3-quest2-hair-student-receipt.json"
    for path, label in (
        (request_path, "P3 candidate request"),
        (hair_receipt_path, "P3 hair receipt"),
        (fidelity_path, "P3 fidelity evidence"),
    ):
        if not path.is_file() or path.is_symlink():
            raise PhotorealP3Quest2FinalManifestError(
                f"{label} is missing/not regular: {path}"
            )

    request = _validate_request(
        _read_json(request_path, label="P3 candidate request")
    )
    hair_raw = _read_json(hair_receipt_path, label="P3 hair receipt")
    try:
        hair = validate_hair_student_receipt(
            hair_raw,
            hair_output_root=hair_root,
        )
    except Exception as exc:
        raise PhotorealP3Quest2FinalManifestError(str(exc)) from exc
    fidelity_raw = _read_json(fidelity_path, label="P3 fidelity evidence")
    try:
        fidelity = validate_fidelity_delta_evidence(
            fidelity_raw,
            hair_receipt=hair,
            hair_output_root=hair_root,
        )
    except Exception as exc:
        raise PhotorealP3Quest2FinalManifestError(str(exc)) from exc

    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "target_model",
        "student_representation",
    ):
        if hair.get(field) != request.get(field):
            raise PhotorealP3Quest2FinalManifestError(
                f"P3 final request/hair provenance mismatch: {field}"
            )
    if fidelity["p3_device_distillation_request_sha256"] != request[
        "p3_device_distillation_request_sha256"
    ]:
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final fidelity evidence targets different request bytes"
        )
    checkpoint_sources = [
        item
        for item in request["staged_teacher_sources"]
        if item["kind"] == "teacher-checkpoint"
    ]
    if (
        len(checkpoint_sources) != 1
        or checkpoint_sources[0]["sha256"]
        != fidelity["teacher_checkpoint_sha256"]
    ):
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final fidelity evidence targets different teacher checkpoint"
        )

    root.mkdir(parents=True)
    output = root / "output"
    student = output / "student"
    student.mkdir(parents=True)

    # Preserve exact upstream authority inputs beside the final output, not as
    # student artifacts.
    shutil.copyfile(request_path, root / "request.json")
    shutil.copyfile(hair_receipt_path, root / "hair-student-receipt.json")
    shutil.copyfile(fidelity_path, root / "fidelity-delta-evidence.json")

    source_avatar_record = next(
        item
        for item in hair["student_artifacts"]
        if item["kind"] == "student-runtime-package"
    )
    source_basecolor_record = next(
        item
        for item in hair["student_artifacts"]
        if item["kind"] == "teacher-derived-basecolor"
    )
    source_avatar = hair_root / source_avatar_record["relative_path"]
    source_basecolor = hair_root / source_basecolor_record["relative_path"]
    avatar = student / "avatar.vrm"
    basecolor = student / "basecolor.png"
    shutil.copyfile(source_avatar, avatar)
    shutil.copyfile(source_basecolor, basecolor)

    if (
        _file_sha(avatar) != source_avatar_record["sha256"]
        or _file_sha(basecolor) != source_basecolor_record["sha256"]
    ):
        raise PhotorealP3Quest2FinalManifestError(
            "P3 final copied student bytes differ from hair-stage authority"
        )

    provenance = _build_provenance(
        request=request,
        hair=hair,
        fidelity=fidelity,
        request_file_sha256=_file_sha(request_path),
        hair_receipt_file_sha256=_file_sha(hair_receipt_path),
        fidelity_file_sha256=_file_sha(fidelity_path),
        source_avatar_sha256=source_avatar_record["sha256"],
        source_basecolor_sha256=source_basecolor_record["sha256"],
        copied_avatar_sha256=_file_sha(avatar),
        copied_basecolor_sha256=_file_sha(basecolor),
    )
    provenance_path = student / "quest2-modular-provenance.json"
    _write_json(provenance_path, provenance)

    artifacts = [
        _artifact(
            avatar,
            output,
            kind="student-runtime-package",
        ),
        _artifact(
            basecolor,
            output,
            kind="teacher-derived-basecolor",
        ),
        _artifact(
            provenance_path,
            output,
            kind="quest2-modular-provenance",
        ),
    ]
    artifacts.sort(key=lambda item: item["relative_path"])

    manifest: dict[str, Any] = {
        "format": RESULT_FORMAT,
        "version": RESULT_VERSION,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "p2_animation_plan_sha256": request["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": request[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "p2_animated_human_review_sha256": request[
            "p2_animated_human_review_sha256"
        ],
        "p3_device_distillation_plan_sha256": request[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_request_sha256": request[
            "p3_device_distillation_request_sha256"
        ],
        "target_profile_sha256": request["target_profile_sha256"],
        "target_model": "quest-2",
        "adapter": request["adapter"],
        "adapter_revision": request["adapter_revision"],
        "student_representation": "skinned-mesh-pbr",
        "student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "distillation_complete": True,
        "consumed_teacher_sources": _consumed_sources(request),
        "fidelity_delta_measurements": canonical_manifest_measurements(fidelity),
        "student_artifacts": artifacts,
        "student_fidelity_claim_exceeds_teacher": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    manifest_path = output / "distillation-manifest.json"
    _write_json(manifest_path, manifest)

    try:
        validated_manifest = validate_distillation_result(
            manifest,
            request=request,
            output_dir=output,
        )
        execution_receipt = build_execution_receipt(validated_manifest)
    except Exception as exc:
        raise PhotorealP3Quest2FinalManifestError(str(exc)) from exc

    receipt_path = root / "p3-device-distillation-execution-receipt.json"
    _write_json(receipt_path, execution_receipt)
    workspace_receipt: dict[str, Any] = {
        "format": WORKSPACE_FORMAT,
        "version": WORKSPACE_VERSION,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "p3_device_distillation_request_sha256": request[
            "p3_device_distillation_request_sha256"
        ],
        "p3_quest2_hair_student_receipt_sha256": hair[
            "p3_quest2_hair_student_receipt_sha256"
        ],
        "p3_quest2_fidelity_delta_evidence_sha256": fidelity[
            "p3_quest2_fidelity_delta_evidence_sha256"
        ],
        "p3_quest2_modular_provenance_sha256": provenance[
            "p3_quest2_modular_provenance_sha256"
        ],
        "p3_device_distillation_execution_receipt_sha256": execution_receipt[
            "p3_device_distillation_execution_receipt_sha256"
        ],
        "distillation_complete": True,
        "student_artifact_count": len(artifacts),
        "artifact_bytes_verified_by_core": True,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    workspace_receipt["p3_quest2_final_workspace_receipt_sha256"] = _digest(
        workspace_receipt,
        omit="p3_quest2_final_workspace_receipt_sha256",
    )
    _write_json(root / "p3-quest2-final-workspace-receipt.json", workspace_receipt)

    return {
        "workspace": workspace_receipt,
        "manifest": validated_manifest,
        "execution_receipt": execution_receipt,
        "provenance": provenance,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the final modular Quest2 P3 distillation manifest from "
            "exact candidate, eye, hair and fidelity authority."
        )
    )
    parser.add_argument("--candidate-workspace", type=Path, required=True)
    parser.add_argument("--hair-output-root", type=Path, required=True)
    parser.add_argument("--fidelity-evidence", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        result = materialize_final_distillation(
            candidate_workspace=args.candidate_workspace,
            hair_output_root=args.hair_output_root,
            fidelity_evidence_path=args.fidelity_evidence,
            workspace=args.workspace,
        )
    except (OSError, PhotorealP3Quest2FinalManifestError) as exc:
        print(f"BodyRig P3 Quest2 final manifest: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P3_QUEST2_DISTILLATION_COMPLETE",
                "student_artifact_count": result["workspace"][
                    "student_artifact_count"
                ],
                "artifact_bytes_verified_by_core": True,
                "distillation_complete": True,
                "human_runtime_visual_acceptance_required": True,
                "runtime_acceptance_authority": False,
                "photoreal_acceptance_authority": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
