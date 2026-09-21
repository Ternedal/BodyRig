from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p2_motion_input_plan import (
    PhotorealP2MotionInputPlanError,
    validate_motion_input_plan,
)
from .photoreal_scan_plan import (
    FORMAT as SCAN_PLAN_FORMAT,
    VERSION as SCAN_PLAN_VERSION,
    PROJECTION_AUTHORITY_FORMATS,
    PROJECTION_AUTHORITY_VERSION,
)


FORMAT = "bodyrig-photoreal-p2-motion-preparation-authority"
VERSION = 1

_SCAN_PLAN_FIELDS = {
    "format",
    "version",
    "performer_id",
    "performer_name",
    "strategy",
    "target_video_interval_seconds",
    "minimum_video_scout_samples",
    "maximum_video_scout_samples",
    "source_count",
    "planned_observation_count",
    "identity_bootstrap_policy",
    "identity_bootstrap_source_count",
    "identity_bootstrap_group_count",
    "sources",
    "all_sources_sha256_bound",
    "train_evaluation_assignment_inherited",
    "frame_analyzer_required",
    "teacher_training_authorized",
    "build_only",
    "runtime_dependency",
    "production_activation",
}

_SCAN_SOURCE_FIELDS = {
    "source_key",
    "source_sha256",
    "resolved_path",
    "kind",
    "split",
    "group_id",
    "source_binding",
    "performer_count",
    "projection",
    "projection_authority",
    "stereo_layout",
    "decode_mode",
    "sample_count",
    "samples",
    "identity_bootstrap_eligible",
}

_BINDING_FIELDS = {
    "source_ref",
    "source_key",
    "group_id",
    "split",
    "role",
    "source_sha256",
    "size_bytes",
    "resolved_path",
    "normalization_action",
    "scan_projection",
    "scan_stereo_layout",
    "scan_decode_mode",
    "projection_authority",
    "projection_authority_sha256",
    "motion_fitting_backend",
    "motion_fitting_camera_mode",
    "source_media_rehash_required",
    "preparation_execution_authorized",
}


class PhotorealP2MotionPreparationAuthorityError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2MotionPreparationAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP2MotionPreparationAuthorityError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealP2MotionPreparationAuthorityError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2MotionPreparationAuthorityError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP2MotionPreparationAuthorityError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2MotionPreparationAuthorityError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2MotionPreparationAuthorityError(f"{label} format/version mismatch")


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    try:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion preparation authority cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: str | Path) -> str:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise PhotorealP2MotionPreparationAuthorityError(f"required authority file is missing/not regular: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_scan_plan(scan_plan: Mapping[str, Any], *, performer_id: str) -> dict[str, dict[str, Any]]:
    if set(scan_plan) != _SCAN_PLAN_FIELDS:
        raise PhotorealP2MotionPreparationAuthorityError("P0 scan plan fields must match v1 exactly")
    if scan_plan.get("format") != SCAN_PLAN_FORMAT:
        raise PhotorealP2MotionPreparationAuthorityError("P0 scan plan format/version mismatch")
    _strict_v1(scan_plan.get("version"), label="P0 scan plan")
    if _text(scan_plan.get("performer_id"), label="P0 scan performer", maximum=256) != performer_id:
        raise PhotorealP2MotionPreparationAuthorityError("P0 scan/P2 motion performer mismatch")
    if scan_plan.get("strategy") != "uniform-midpoint-scout-v1":
        raise PhotorealP2MotionPreparationAuthorityError("P0 scan strategy mismatch")
    if scan_plan.get("identity_bootstrap_policy") != "train-only-single-performer-direct-binding-v1":
        raise PhotorealP2MotionPreparationAuthorityError("P0 scan identity bootstrap policy mismatch")
    for field, expected in (
        ("all_sources_sha256_bound", True),
        ("train_evaluation_assignment_inherited", True),
        ("frame_analyzer_required", True),
        ("teacher_training_authorized", False),
        ("build_only", True),
        ("runtime_dependency", False),
        ("production_activation", False),
    ):
        if scan_plan.get(field) is not expected:
            raise PhotorealP2MotionPreparationAuthorityError(f"P0 scan authority mismatch: {field}")

    values = scan_plan.get("sources")
    count = scan_plan.get("source_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise PhotorealP2MotionPreparationAuthorityError("P0 scan source count is invalid")
    if not isinstance(values, list) or len(values) != count:
        raise PhotorealP2MotionPreparationAuthorityError("P0 scan source count mismatch")

    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping) or set(raw) != _SCAN_SOURCE_FIELDS:
            raise PhotorealP2MotionPreparationAuthorityError("P0 scan source fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label="P0 scan source key")
        if source_key in result:
            raise PhotorealP2MotionPreparationAuthorityError("P0 scan plan repeats source key")
        if raw.get("kind") not in {"video", "image"}:
            raise PhotorealP2MotionPreparationAuthorityError("P0 scan source kind is invalid")
        if raw.get("split") not in {"train", "evaluation"}:
            raise PhotorealP2MotionPreparationAuthorityError("P0 scan source split is invalid")
        _sha(raw.get("source_sha256"), label="P0 scan source SHA-256")
        _text(raw.get("resolved_path"), label="P0 scan resolved path")
        _text(raw.get("group_id"), label="P0 scan group id")
        _text(raw.get("projection"), label="P0 scan projection", maximum=128)
        _text(raw.get("stereo_layout"), label="P0 scan stereo layout", maximum=128)
        _text(raw.get("decode_mode"), label="P0 scan decode mode", maximum=128)
        sample_count = raw.get("sample_count")
        samples = raw.get("samples")
        if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1:
            raise PhotorealP2MotionPreparationAuthorityError("P0 scan sample count is invalid")
        if not isinstance(samples, list) or len(samples) != sample_count:
            raise PhotorealP2MotionPreparationAuthorityError("P0 scan sample count mismatch")
        result[source_key] = dict(raw)
    return result


def _projection_authority(value: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(value, Mapping):
        raise PhotorealP2MotionPreparationAuthorityError(
            "spatial P2 motion source lacks exact P0 projection authority"
        )
    result = copy.deepcopy(dict(value))
    version = result.get("version")
    if (
        result.get("format") not in PROJECTION_AUTHORITY_FORMATS
        or isinstance(version, bool)
        or version != PROJECTION_AUTHORITY_VERSION
    ):
        raise PhotorealP2MotionPreparationAuthorityError(
            "spatial P2 motion projection authority format/version mismatch"
        )
    if result.get("projection_type") != "equi":
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion preparation v1 supports only exact equirectangular spatial authority"
        )
    if result.get("deprojection_authority") is not False:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P0 projection authority unexpectedly owns deprojection authority"
        )
    return result, _digest(result)


def _binding(task: Mapping[str, Any], scan_source: Mapping[str, Any]) -> dict[str, Any]:
    source_key = _text(task.get("source_key"), label="P2 motion task source key")
    if scan_source.get("source_key") != source_key:
        raise PhotorealP2MotionPreparationAuthorityError("P0/P2 motion source key mismatch")
    for field, scan_field in (
        ("source_sha256", "source_sha256"),
        ("resolved_path", "resolved_path"),
        ("group_id", "group_id"),
        ("split", "split"),
    ):
        if task.get(field) != scan_source.get(scan_field):
            raise PhotorealP2MotionPreparationAuthorityError(
                f"P0/P2 motion source binding mismatch: {field}"
            )
    if scan_source.get("kind") != "video":
        raise PhotorealP2MotionPreparationAuthorityError("P2 motion preparation requires video sources")

    action = _text(task.get("normalization_action"), label="P2 motion normalization action", maximum=128)
    projection = _text(scan_source.get("projection"), label="P0 scan projection", maximum=128)
    stereo = _text(scan_source.get("stereo_layout"), label="P0 scan stereo layout", maximum=128)
    decode_mode = _text(scan_source.get("decode_mode"), label="P0 scan decode mode", maximum=128)

    projection_authority: dict[str, Any] | None = None
    projection_authority_sha: str | None = None
    if action == "preserve-flat-mono-video":
        if projection != "flat" or stereo != "mono" or decode_mode != "rectilinear-mono":
            raise PhotorealP2MotionPreparationAuthorityError(
                "direct P2 motion source is not exact flat/mono authority"
            )
        if scan_source.get("projection_authority") is not None:
            raise PhotorealP2MotionPreparationAuthorityError(
                "flat/mono P2 motion source unexpectedly carries spatial projection authority"
            )
    elif action == "exact-authorized-deprojection":
        if projection != "equi" or decode_mode != "spatial-deprojection-required":
            raise PhotorealP2MotionPreparationAuthorityError(
                "P2 motion deprojection source is not exact equirectangular P0 authority"
            )
        if stereo not in {"mono", "side-by-side", "over-under"}:
            raise PhotorealP2MotionPreparationAuthorityError(
                "P2 motion deprojection source uses unsupported stereo layout"
            )
        projection_authority, projection_authority_sha = _projection_authority(
            scan_source.get("projection_authority")
        )
    else:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion normalization action is unsupported"
        )

    size = task.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise PhotorealP2MotionPreparationAuthorityError("P2 motion task source size is invalid")

    return {
        "source_ref": _text(task.get("source_ref"), label="P2 motion source ref", maximum=64),
        "source_key": source_key,
        "group_id": _text(task.get("group_id"), label="P2 motion group id"),
        "split": _text(task.get("split"), label="P2 motion split", maximum=16),
        "role": _text(task.get("role"), label="P2 motion role", maximum=64),
        "source_sha256": _sha(task.get("source_sha256"), label="P2 motion source SHA-256"),
        "size_bytes": size,
        "resolved_path": _text(task.get("resolved_path"), label="P2 motion resolved path"),
        "normalization_action": action,
        "scan_projection": projection,
        "scan_stereo_layout": stereo,
        "scan_decode_mode": decode_mode,
        "projection_authority": projection_authority,
        "projection_authority_sha256": projection_authority_sha,
        "motion_fitting_backend": "pinned-exavatar-fitting-v1",
        "motion_fitting_camera_mode": "virtual",
        "source_media_rehash_required": False,
        "preparation_execution_authorized": True,
    }


def _expected_bindings(
    input_plan: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    performer_id = _text(input_plan.get("performer_id"), label="P2 motion performer", maximum=256)
    scan_by_key = _validate_scan_plan(scan_plan, performer_id=performer_id)

    def collect(values: Any, *, expected_role: str, expected_split: str) -> list[dict[str, Any]]:
        if not isinstance(values, list) or not values:
            raise PhotorealP2MotionPreparationAuthorityError(
                f"P2 motion input plan contains no {expected_role} tasks"
            )
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in values:
            if not isinstance(raw, Mapping):
                raise PhotorealP2MotionPreparationAuthorityError("P2 motion input task is invalid")
            if raw.get("role") != expected_role or raw.get("split") != expected_split:
                raise PhotorealP2MotionPreparationAuthorityError("P2 motion input task role/split mismatch")
            source_key = _text(raw.get("source_key"), label="P2 motion task source key")
            if source_key in seen or source_key not in scan_by_key:
                raise PhotorealP2MotionPreparationAuthorityError(
                    "P2 motion task source is missing/duplicated in P0 scan authority"
                )
            seen.add(source_key)
            result.append(_binding(raw, scan_by_key[source_key]))
        result.sort(key=lambda item: item["source_ref"])
        return result

    drivers = collect(
        input_plan.get("motion_driver_tasks"),
        expected_role="motion-driver",
        expected_split="train",
    )
    heldout = collect(
        input_plan.get("held_out_motion_validation_tasks"),
        expected_role="held-out-motion-validation",
        expected_split="evaluation",
    )
    if {item["source_key"] for item in drivers} & {item["source_key"] for item in heldout}:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion preparation crosses train/evaluation source boundary"
        )
    return drivers, heldout


def build_motion_preparation_authority(
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    selection: Mapping[str, Any],
    input_plan: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    *,
    scan_plan_file_sha256: str,
) -> dict[str, Any]:
    try:
        validated_plan = validate_motion_input_plan(
            input_plan,
            handoff=handoff,
            private_index=private_index,
            selection=selection,
        )
    except PhotorealP2MotionInputPlanError as exc:
        raise PhotorealP2MotionPreparationAuthorityError(
            f"P2 motion input plan strict readback failed: {exc}"
        ) from exc

    if validated_plan.get("motion_input_preparation_execution_authorized") is not False:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion input plan unexpectedly pre-authorized execution"
        )
    if validated_plan.get("p2_animation_execution_authorized") is not False:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion input plan unexpectedly authorized animation execution"
        )

    scan_file_sha = _sha(scan_plan_file_sha256, label="P0 scan plan file SHA-256")
    drivers, heldout = _expected_bindings(validated_plan, scan_plan)
    all_bindings = drivers + heldout

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": _text(validated_plan.get("performer_id"), label="P2 motion performer", maximum=256),
        "selected_epoch_id": _text(validated_plan.get("selected_epoch_id"), label="P2 motion epoch", maximum=256),
        "teacher_input_sha256": _sha(validated_plan.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "p2_animation_plan_sha256": _sha(
            validated_plan.get("p2_animation_plan_sha256"),
            label="P2 animation plan SHA-256",
        ),
        "p2_motion_evidence_handoff_sha256": _sha(
            validated_plan.get("p2_motion_evidence_handoff_sha256"),
            label="P2 motion evidence handoff SHA-256",
        ),
        "p2_motion_private_index_sha256": _sha(
            validated_plan.get("p2_motion_private_index_sha256"),
            label="P2 motion private index SHA-256",
        ),
        "p2_motion_source_selection_sha256": _sha(
            validated_plan.get("p2_motion_source_selection_sha256"),
            label="P2 motion source selection SHA-256",
        ),
        "p2_motion_input_plan_sha256": _sha(
            validated_plan.get("p2_motion_input_plan_sha256"),
            label="P2 motion input plan SHA-256",
        ),
        "p0_scan_plan_file_sha256": scan_file_sha,
        "motion_driver_bindings": drivers,
        "held_out_motion_validation_bindings": heldout,
        "motion_driver_binding_count": len(drivers),
        "held_out_motion_validation_binding_count": len(heldout),
        "direct_flat_mono_binding_count": sum(
            1 for item in all_bindings if item["normalization_action"] == "preserve-flat-mono-video"
        ),
        "equirectangular_deprojection_binding_count": sum(
            1 for item in all_bindings if item["normalization_action"] == "exact-authorized-deprojection"
        ),
        "scan_plan_projection_authority_reused": True,
        "source_media_rehash_required": False,
        "source_media_rehash_performed": False,
        "motion_fitting_backend": "pinned-exavatar-fitting-v1",
        "motion_fitting_camera_mode": "virtual",
        "motion_input_preparation_execution_authorized": True,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p2_motion_preparation_authority_sha256"] = _digest(
        result,
        omit="p2_motion_preparation_authority_sha256",
    )
    return validate_motion_preparation_authority(
        result,
        handoff=handoff,
        private_index=private_index,
        selection=selection,
        input_plan=validated_plan,
        scan_plan=scan_plan,
        scan_plan_file_sha256=scan_file_sha,
    )


def validate_motion_preparation_authority(
    authority: Mapping[str, Any],
    *,
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    selection: Mapping[str, Any],
    input_plan: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    scan_plan_file_sha256: str,
) -> dict[str, Any]:
    try:
        validated_plan = validate_motion_input_plan(
            input_plan,
            handoff=handoff,
            private_index=private_index,
            selection=selection,
        )
    except PhotorealP2MotionInputPlanError as exc:
        raise PhotorealP2MotionPreparationAuthorityError(
            f"P2 motion input plan strict readback failed: {exc}"
        ) from exc

    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_evidence_handoff_sha256",
        "p2_motion_private_index_sha256",
        "p2_motion_source_selection_sha256",
        "p2_motion_input_plan_sha256",
        "p0_scan_plan_file_sha256",
        "motion_driver_bindings",
        "held_out_motion_validation_bindings",
        "motion_driver_binding_count",
        "held_out_motion_validation_binding_count",
        "direct_flat_mono_binding_count",
        "equirectangular_deprojection_binding_count",
        "scan_plan_projection_authority_reused",
        "source_media_rehash_required",
        "source_media_rehash_performed",
        "motion_fitting_backend",
        "motion_fitting_camera_mode",
        "motion_input_preparation_execution_authorized",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_motion_preparation_authority_sha256",
    }
    if set(authority) != expected_fields:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion preparation authority fields must match v1 exactly"
        )
    if authority.get("format") != FORMAT:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion preparation authority format/version mismatch"
        )
    _strict_v1(authority.get("version"), label="P2 motion preparation authority")
    claimed = _sha(
        authority.get("p2_motion_preparation_authority_sha256"),
        label="P2 motion preparation authority SHA-256",
    )
    if _digest(authority, omit="p2_motion_preparation_authority_sha256") != claimed:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion preparation authority digest mismatch"
        )

    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_evidence_handoff_sha256",
        "p2_motion_private_index_sha256",
        "p2_motion_source_selection_sha256",
        "p2_motion_input_plan_sha256",
    ):
        if authority.get(field) != validated_plan.get(field):
            raise PhotorealP2MotionPreparationAuthorityError(
                f"P2 motion preparation authority lineage mismatch: {field}"
            )
    scan_sha = _sha(scan_plan_file_sha256, label="P0 scan plan file SHA-256")
    if authority.get("p0_scan_plan_file_sha256") != scan_sha:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion preparation authority P0 scan file binding mismatch"
        )

    expected_drivers, expected_heldout = _expected_bindings(validated_plan, scan_plan)
    if authority.get("motion_driver_bindings") != expected_drivers:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion preparation driver bindings differ from canonical P0/P2 authority"
        )
    if authority.get("held_out_motion_validation_bindings") != expected_heldout:
        raise PhotorealP2MotionPreparationAuthorityError(
            "P2 motion preparation held-out bindings differ from canonical P0/P2 authority"
        )
    if authority.get("motion_driver_binding_count") != len(expected_drivers):
        raise PhotorealP2MotionPreparationAuthorityError("P2 motion preparation driver count mismatch")
    if authority.get("held_out_motion_validation_binding_count") != len(expected_heldout):
        raise PhotorealP2MotionPreparationAuthorityError("P2 motion preparation held-out count mismatch")

    all_bindings = expected_drivers + expected_heldout
    expected_direct = sum(
        1 for item in all_bindings if item["normalization_action"] == "preserve-flat-mono-video"
    )
    expected_spatial = sum(
        1 for item in all_bindings if item["normalization_action"] == "exact-authorized-deprojection"
    )
    if authority.get("direct_flat_mono_binding_count") != expected_direct:
        raise PhotorealP2MotionPreparationAuthorityError("P2 motion preparation direct count mismatch")
    if authority.get("equirectangular_deprojection_binding_count") != expected_spatial:
        raise PhotorealP2MotionPreparationAuthorityError("P2 motion preparation spatial count mismatch")

    if authority.get("motion_fitting_backend") != "pinned-exavatar-fitting-v1":
        raise PhotorealP2MotionPreparationAuthorityError("P2 motion preparation fitting backend mismatch")
    if authority.get("motion_fitting_camera_mode") != "virtual":
        raise PhotorealP2MotionPreparationAuthorityError("P2 motion preparation camera mode mismatch")

    for field, expected in (
        ("scan_plan_projection_authority_reused", True),
        ("source_media_rehash_required", False),
        ("source_media_rehash_performed", False),
        ("motion_input_preparation_execution_authorized", True),
        ("p2_animation_execution_authorized", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if authority.get(field) is not expected:
            raise PhotorealP2MotionPreparationAuthorityError(
                f"P2 motion preparation authority mismatch: {field}"
            )
    return dict(authority)


def build_motion_preparation_authority_files(
    handoff_path: str | Path,
    private_index_path: str | Path,
    selection_path: str | Path,
    input_plan_path: str | Path,
    scan_plan_path: str | Path,
    output_path: str | Path,
    *,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    handoff = _read_json(handoff_path, label="P2 motion evidence handoff")
    private_index = _read_json(private_index_path, label="private P2 motion source index")
    selection = _read_json(selection_path, label="P2 motion source selection")
    input_plan = _read_json(input_plan_path, label="P2 motion input plan")
    scan_plan = _read_json(scan_plan_path, label="P0 scan plan")
    scan_sha = _file_sha(scan_plan_path)
    authority = build_motion_preparation_authority(
        handoff,
        private_index,
        selection,
        input_plan,
        scan_plan,
        scan_plan_file_sha256=scan_sha,
    )

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP2MotionPreparationAuthorityError(
                f"P2 motion preparation authority already exists: {output}"
            )
        existing = _read_json(output, label="existing P2 motion preparation authority")
        if existing != authority:
            raise PhotorealP2MotionPreparationAuthorityError(
                f"existing P2 motion preparation authority differs from canonical current state: {output}"
            )
        return authority
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(authority, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        raise PhotorealP2MotionPreparationAuthorityError(
            f"failed to persist P2 motion preparation authority: {output}"
        ) from exc
    return authority


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind P2 motion-input preparation to exact P0 scan/projection authority."
    )
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--private-index", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--input-plan", type=Path, required=True)
    parser.add_argument("--scan-plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        authority = build_motion_preparation_authority_files(
            args.handoff,
            args.private_index,
            args.selection,
            args.input_plan,
            args.scan_plan,
            args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP2MotionPreparationAuthorityError as exc:
        print(f"BodyRig P2 motion preparation authority: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P2_MOTION_PREPARATION_EXECUTION_AUTHORIZED",
                "motion_driver_binding_count": authority["motion_driver_binding_count"],
                "held_out_motion_validation_binding_count": authority[
                    "held_out_motion_validation_binding_count"
                ],
                "equirectangular_deprojection_binding_count": authority[
                    "equirectangular_deprojection_binding_count"
                ],
                "source_media_rehash_required": False,
                "motion_input_preparation_execution_authorized": True,
                "p2_animation_execution_authorized": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
