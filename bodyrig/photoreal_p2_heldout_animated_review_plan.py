from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_p2_exavatar_heldout_evaluation_runner import (
    PhotorealP2ExAvatarHeldoutEvaluationRunnerError,
    validate_heldout_evaluation_receipt,
)


FORMAT = "bodyrig-photoreal-p2-heldout-animated-review-plan"
VERSION = 1
SELECTION_FORMAT = "bodyrig-photoreal-p2-heldout-animated-review-selection"
SELECTION_VERSION = 1

REVIEW_DIMENSIONS = (
    "head_turn_validation",
    "eye_motion_validation",
    "mouth_motion_validation",
    "hand_motion_validation",
    "full_body_pose_validation",
    "identity_appearance_motion_preservation",
)


class PhotorealP2HeldoutAnimatedReviewPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
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
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review plan cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            f"required review artifact is missing/not regular: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _selection_map(selection: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    expected_fields = {
        "format",
        "version",
        "reviewer",
        "operator_supplied",
        "selections",
    }
    if set(selection) != expected_fields:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review selection fields must match v1 exactly"
        )
    if selection.get("format") != SELECTION_FORMAT:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review selection format/version mismatch"
        )
    _strict_v1(
        selection.get("version"),
        label="P2 held-out animated review selection",
    )
    reviewer = _text(
        selection.get("reviewer"),
        label="P2 held-out animated review reviewer",
        maximum=256,
    )
    if selection.get("operator_supplied") is not True:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review evidence selection must be human/operator supplied"
        )
    raw_values = selection.get("selections")
    if not isinstance(raw_values, list) or len(raw_values) != len(REVIEW_DIMENSIONS):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review selection must cover every review dimension exactly"
        )
    result: dict[str, str] = {}
    for raw in raw_values:
        if not isinstance(raw, Mapping) or set(raw) != {
            "dimension",
            "held_out_source_ref",
        }:
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                "P2 held-out animated review selection entry fields must match v1 exactly"
            )
        dimension = _text(
            raw.get("dimension"),
            label="P2 held-out animated review dimension",
            maximum=80,
        )
        if dimension not in REVIEW_DIMENSIONS:
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                f"unsupported P2 held-out animated review dimension: {dimension}"
            )
        if dimension in result:
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                "P2 held-out animated review selection repeats a dimension"
            )
        source_ref = _text(
            raw.get("held_out_source_ref"),
            label="P2 held-out animated review source ref",
            maximum=64,
        )
        result[dimension] = source_ref
    if set(result) != set(REVIEW_DIMENSIONS):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review selection dimension universe mismatch"
        )
    return reviewer, result


def _evaluation_evidence(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            f"P2 held-out evaluation workspace is missing/not regular: {root}"
        )
    receipt_path = root / "heldout-evaluation-execution-receipt.json"
    receipt_raw = _read_json(
        receipt_path,
        label="P2 held-out evaluation execution receipt",
    )
    try:
        receipt = validate_heldout_evaluation_receipt(receipt_raw)
    except PhotorealP2ExAvatarHeldoutEvaluationRunnerError as exc:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            f"P2 held-out evaluation receipt strict readback failed: {exc}"
        ) from exc

    artifacts = receipt.get("evaluation_artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out evaluation receipt must contain exactly one review artifact"
        )
    artifact = artifacts[0]
    if not isinstance(artifact, Mapping):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out evaluation review artifact is invalid"
        )
    if (
        artifact.get("kind") != "heldout-animation-review-video"
        or artifact.get("relative_path") != "review/heldout-animation.mp4"
    ):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out evaluation review artifact contract mismatch"
        )
    video = root / "output" / "review" / "heldout-animation.mp4"
    size = artifact.get("size_bytes")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or not video.is_file()
        or video.is_symlink()
        or video.stat().st_size != size
    ):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out evaluation review artifact size/path drifted"
        )
    expected_sha = _sha(
        artifact.get("sha256"),
        label="P2 held-out evaluation review artifact SHA-256",
    )
    observed_sha = _file_sha(video)
    if observed_sha != expected_sha:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out evaluation review artifact bytes drifted"
        )

    return {
        "performer_id": _text(
            receipt.get("performer_id"),
            label="P2 held-out evaluation performer",
            maximum=256,
        ),
        "selected_epoch_id": _text(
            receipt.get("selected_epoch_id"),
            label="P2 held-out evaluation epoch",
            maximum=256,
        ),
        "teacher_input_sha256": _sha(
            receipt.get("teacher_input_sha256"),
            label="P2 held-out evaluation teacher input SHA-256",
        ),
        "p2_animation_plan_sha256": _sha(
            receipt.get("p2_animation_plan_sha256"),
            label="P2 held-out evaluation animation plan SHA-256",
        ),
        "p2_exavatar_animation_execution_input_sha256": _sha(
            receipt.get("p2_exavatar_animation_execution_input_sha256"),
            label="P2 ExAvatar execution input SHA-256",
        ),
        "train_animation_execution_receipt_sha256": _sha(
            receipt.get("train_animation_execution_receipt_sha256"),
            label="TRAIN animation execution receipt SHA-256",
        ),
        "consumed_checkpoint_sha256": _sha(
            receipt.get("consumed_checkpoint_sha256"),
            label="P2 held-out evaluation checkpoint SHA-256",
        ),
        "held_out_source_ref": _text(
            receipt.get("held_out_source_ref"),
            label="P2 held-out evaluation source ref",
            maximum=64,
        ),
        "held_out_frame_count": receipt["held_out_frame_count"],
        "held_out_frame_ids": list(receipt["held_out_frame_ids"]),
        "heldout_evaluation_execution_receipt_sha256": _sha(
            receipt.get(
                "p2_exavatar_heldout_evaluation_execution_receipt_sha256"
            ),
            label="P2 held-out evaluation execution receipt SHA-256",
        ),
        "review_artifact_kind": "heldout-animation-review-video",
        "review_artifact_relative_path": "review/heldout-animation.mp4",
        "review_artifact_size_bytes": size,
        "review_artifact_sha256": observed_sha,
    }


def _evidence_map(
    evaluation_workspaces: Sequence[str | Path],
) -> dict[str, dict[str, Any]]:
    if not evaluation_workspaces:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review requires at least one evaluation workspace"
        )
    result: dict[str, dict[str, Any]] = {}
    for workspace in evaluation_workspaces:
        evidence = _evaluation_evidence(workspace)
        source_ref = evidence["held_out_source_ref"]
        if source_ref in result:
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                "P2 held-out animated review repeats an evaluation source ref"
            )
        result[source_ref] = evidence
    return result


def build_heldout_animated_review_plan(
    selection_input: Mapping[str, Any],
    *,
    evaluation_workspaces: Sequence[str | Path],
) -> dict[str, Any]:
    reviewer, selections = _selection_map(selection_input)
    evidence_by_ref = _evidence_map(evaluation_workspaces)

    missing = sorted(set(selections.values()) - set(evidence_by_ref))
    if missing:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review selection references unavailable evaluation evidence"
        )

    selected_evidence = [evidence_by_ref[ref] for ref in sorted(set(selections.values()))]
    first = selected_evidence[0]
    lineage_fields = (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "consumed_checkpoint_sha256",
    )
    for evidence in selected_evidence[1:]:
        for field in lineage_fields:
            if evidence[field] != first[field]:
                raise PhotorealP2HeldoutAnimatedReviewPlanError(
                    f"P2 held-out evaluation evidence lineage mismatch: {field}"
                )

    records: list[dict[str, Any]] = []
    for dimension in REVIEW_DIMENSIONS:
        source_ref = selections[dimension]
        evidence = evidence_by_ref[source_ref]
        records.append(
            {
                "dimension": dimension,
                "held_out_source_ref": source_ref,
                "held_out_frame_count": evidence["held_out_frame_count"],
                "held_out_frame_ids": evidence["held_out_frame_ids"],
                "heldout_evaluation_execution_receipt_sha256": evidence[
                    "heldout_evaluation_execution_receipt_sha256"
                ],
                "review_artifact_kind": evidence["review_artifact_kind"],
                "review_artifact_relative_path": evidence[
                    "review_artifact_relative_path"
                ],
                "review_artifact_size_bytes": evidence[
                    "review_artifact_size_bytes"
                ],
                "review_artifact_sha256": evidence["review_artifact_sha256"],
            }
        )

    plan: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": first["performer_id"],
        "selected_epoch_id": first["selected_epoch_id"],
        "teacher_input_sha256": first["teacher_input_sha256"],
        "p2_animation_plan_sha256": first["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": first[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "train_animation_execution_receipt_sha256": first[
            "train_animation_execution_receipt_sha256"
        ],
        "consumed_checkpoint_sha256": first["consumed_checkpoint_sha256"],
        "reviewer": reviewer,
        "review_dimensions": list(REVIEW_DIMENSIONS),
        "selections": records,
        "selection_count": len(records),
        "evidence_source_count": len(set(selections.values())),
        "held_out_evaluation_only": True,
        "evaluation_artifact_bytes_reverified": True,
        "human_animated_visual_acceptance_required": True,
        "human_animated_review_complete": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    plan["p2_heldout_animated_review_plan_sha256"] = _digest(
        plan,
        omit="p2_heldout_animated_review_plan_sha256",
    )
    return validate_heldout_animated_review_plan(plan)


def validate_heldout_animated_review_plan(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "consumed_checkpoint_sha256",
        "reviewer",
        "review_dimensions",
        "selections",
        "selection_count",
        "evidence_source_count",
        "held_out_evaluation_only",
        "evaluation_artifact_bytes_reverified",
        "human_animated_visual_acceptance_required",
        "human_animated_review_complete",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_heldout_animated_review_plan_sha256",
    }
    if set(value) != expected:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review plan fields must match v1 exactly"
        )
    if value.get("format") != FORMAT:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review plan format/version mismatch"
        )
    _strict_v1(value.get("version"), label="P2 held-out animated review plan")
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "consumed_checkpoint_sha256",
    ):
        _sha(value.get(field), label=f"P2 held-out animated review plan {field}")
    _text(value.get("performer_id"), label="P2 held-out animated review performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P2 held-out animated review epoch", maximum=256)
    _text(value.get("reviewer"), label="P2 held-out animated review reviewer", maximum=256)

    if value.get("review_dimensions") != list(REVIEW_DIMENSIONS):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review dimension universe mismatch"
        )
    selections = value.get("selections")
    if not isinstance(selections, list) or len(selections) != len(REVIEW_DIMENSIONS):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review plan selection count is invalid"
        )
    expected_selection_fields = {
        "dimension",
        "held_out_source_ref",
        "held_out_frame_count",
        "held_out_frame_ids",
        "heldout_evaluation_execution_receipt_sha256",
        "review_artifact_kind",
        "review_artifact_relative_path",
        "review_artifact_size_bytes",
        "review_artifact_sha256",
    }
    dimensions: list[str] = []
    refs: set[str] = set()
    for raw in selections:
        if not isinstance(raw, Mapping) or set(raw) != expected_selection_fields:
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                "P2 held-out animated review plan selection fields must match v1 exactly"
            )
        dimension = _text(
            raw.get("dimension"),
            label="P2 held-out animated review dimension",
            maximum=80,
        )
        dimensions.append(dimension)
        source_ref = _text(
            raw.get("held_out_source_ref"),
            label="P2 held-out animated review source ref",
            maximum=64,
        )
        refs.add(source_ref)
        frame_count = raw.get("held_out_frame_count")
        frame_ids = raw.get("held_out_frame_ids")
        if (
            isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
            or frame_count < 1
            or not isinstance(frame_ids, list)
            or len(frame_ids) != frame_count
            or frame_ids != sorted(set(frame_ids))
            or any(
                isinstance(item, bool) or not isinstance(item, int) or item < 0
                for item in frame_ids
            )
        ):
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                "P2 held-out animated review frame universe is invalid"
            )
        _sha(
            raw.get("heldout_evaluation_execution_receipt_sha256"),
            label="P2 held-out evaluation execution receipt SHA-256",
        )
        if (
            raw.get("review_artifact_kind") != "heldout-animation-review-video"
            or raw.get("review_artifact_relative_path")
            != "review/heldout-animation.mp4"
        ):
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                "P2 held-out animated review artifact contract mismatch"
            )
        size = raw.get("review_artifact_size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                "P2 held-out animated review artifact size is invalid"
            )
        _sha(
            raw.get("review_artifact_sha256"),
            label="P2 held-out animated review artifact SHA-256",
        )
    if dimensions != list(REVIEW_DIMENSIONS):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review selections are not canonical/complete"
        )
    if value.get("selection_count") != len(REVIEW_DIMENSIONS):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review selection_count mismatch"
        )
    evidence_count = value.get("evidence_source_count")
    if (
        isinstance(evidence_count, bool)
        or not isinstance(evidence_count, int)
        or evidence_count < 1
        or evidence_count != len(refs)
    ):
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review evidence source count mismatch"
        )

    for field, expected_value in (
        ("held_out_evaluation_only", True),
        ("evaluation_artifact_bytes_reverified", True),
        ("human_animated_visual_acceptance_required", True),
        ("human_animated_review_complete", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected_value:
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                f"P2 held-out animated review plan authority mismatch: {field}"
            )

    claimed = _sha(
        value.get("p2_heldout_animated_review_plan_sha256"),
        label="P2 held-out animated review plan SHA-256",
    )
    if _digest(value, omit="p2_heldout_animated_review_plan_sha256") != claimed:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "P2 held-out animated review plan digest mismatch"
        )
    return dict(value)


def revalidate_heldout_animated_review_plan(
    value: Mapping[str, Any],
    *,
    evaluation_workspaces: Sequence[str | Path],
) -> dict[str, Any]:
    plan = validate_heldout_animated_review_plan(value)
    selection = {
        "format": SELECTION_FORMAT,
        "version": SELECTION_VERSION,
        "reviewer": plan["reviewer"],
        "operator_supplied": True,
        "selections": [
            {
                "dimension": item["dimension"],
                "held_out_source_ref": item["held_out_source_ref"],
            }
            for item in plan["selections"]
        ],
    }
    rebuilt = build_heldout_animated_review_plan(
        selection,
        evaluation_workspaces=evaluation_workspaces,
    )
    if rebuilt != plan:
        raise PhotorealP2HeldoutAnimatedReviewPlanError(
            "persisted P2 held-out animated review plan differs from current evidence bytes"
        )
    return plan


def build_heldout_animated_review_plan_files(
    selection_input_path: str | Path,
    *,
    evaluation_workspaces: Sequence[str | Path],
    output_path: str | Path,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    selection = _read_json(
        selection_input_path,
        label="P2 held-out animated review selection",
    )
    plan = build_heldout_animated_review_plan(
        selection,
        evaluation_workspaces=evaluation_workspaces,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                f"P2 held-out animated review plan already exists: {output}"
            )
        existing = _read_json(
            output,
            label="existing P2 held-out animated review plan",
        )
        revalidate_heldout_animated_review_plan(
            existing,
            evaluation_workspaces=evaluation_workspaces,
        )
        if existing != plan:
            raise PhotorealP2HeldoutAnimatedReviewPlanError(
                "existing P2 held-out animated review plan differs from requested selection"
            )
        return existing
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(
            plan,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        stream.write("\n")
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind human-selected P2 review dimensions to exact HELD-OUT "
            "ExAvatar evaluation receipts and review-video bytes."
        )
    )
    parser.add_argument("--selection-input", type=Path, required=True)
    parser.add_argument(
        "--evaluation-workspace",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = build_heldout_animated_review_plan_files(
            args.selection_input,
            evaluation_workspaces=args.evaluation_workspace,
            output_path=args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP2HeldoutAnimatedReviewPlanError as exc:
        print(f"BodyRig P2 held-out animated review plan: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "P2_HELDOUT_ANIMATED_REVIEW_PLAN_READY",
                "review_dimension_count": plan["selection_count"],
                "evidence_source_count": plan["evidence_source_count"],
                "evaluation_artifact_bytes_reverified": True,
                "human_animated_review_complete": False,
                "p2_animated_teacher_acceptance_authority": False,
                "quest_distillation_authorized": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
