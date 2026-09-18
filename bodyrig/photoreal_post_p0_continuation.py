from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_appearance_epoch import (
    PhotorealAppearanceEpochError,
    build_appearance_epoch_plan,
)
from .photoreal_appearance_epoch_handoff import (
    PhotorealAppearanceEpochHandoffError,
    build_appearance_epoch_review_handoff,
)
from .photoreal_appearance_epoch_review import (
    PhotorealAppearanceEpochReviewError,
    apply_appearance_epoch_review,
)
from .photoreal_appearance_epoch_review_recorder import (
    PhotorealAppearanceEpochReviewRecorderError,
    build_human_review_record,
)
from .photoreal_teacher_authority import (
    validate_teacher_input_document,
    validate_teacher_input_upstream_versions,
)
from .photoreal_teacher_input import PhotorealTeacherInputError, build_teacher_input
from .photoreal_teacher_input_p0_root import (
    PhotorealTeacherInputP0RootError,
    resolve_authorized_p0_root,
    resolve_authorized_p0_teacher_inputs,
)

READINESS_FORMAT = "bodyrig-photoreal-p0-downstream-readiness"
PHYSICAL_FORMAT = "bodyrig-photoreal-p0-physical-verification"
SUMMARY_FORMAT = "bodyrig-photoreal-v2-overnight-summary"
STATUS_FORMAT = "bodyrig-photoreal-post-p0-continuation-status"
VERSION = 1


class PhotorealPostP0ContinuationError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealPostP0ContinuationError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealPostP0ContinuationError(f"{label} must be a JSON object")
    return value


def _numeric_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealPostP0ContinuationError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealPostP0ContinuationError(f"{label} format/version mismatch")


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealPostP0ContinuationError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum:
        raise PhotorealPostP0ContinuationError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealPostP0ContinuationError(f"{label} is invalid")
    return result


def _git_sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=40).lower()
    if len(result) != 40 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealPostP0ContinuationError(f"{label} is invalid")
    return result


def _sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealPostP0ContinuationError(f"bound evidence file is missing or not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(left)))) == os.path.normcase(
        os.path.abspath(os.path.expanduser(str(right)))
    )


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PhotorealPostP0ContinuationError("continuation artifact cannot be canonically serialized") from exc


def _write_or_require_exact(path: Path, value: Mapping[str, Any], *, label: str) -> None:
    path = path.expanduser().resolve()
    if path.is_symlink():
        raise PhotorealPostP0ContinuationError(f"{label} may not be a symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise PhotorealPostP0ContinuationError(f"{label} is not a regular file: {path}")
        existing = _read_json(path, label=label)
        if _canonical_json(existing) != _canonical_json(value):
            raise PhotorealPostP0ContinuationError(f"{label} does not match canonical continuation state: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        raise PhotorealPostP0ContinuationError(f"failed to persist {label}: {path}") from exc


def _require_bool(value: Any, expected: bool, *, label: str) -> None:
    if not isinstance(value, bool) or value is not expected:
        raise PhotorealPostP0ContinuationError(f"{label} must be strict boolean {str(expected).lower()}")


def validate_downstream_readiness(
    readiness_path: str | Path,
    p0_root: str | Path,
    *,
    expected_performer_id: str | None = None,
) -> dict[str, Any]:
    try:
        status, status_path, _plan_path, _receipt_path, _frame_index_path = resolve_authorized_p0_root(p0_root)
    except PhotorealTeacherInputP0RootError as exc:
        raise PhotorealPostP0ContinuationError(f"P0 root authority is invalid: {exc}") from exc

    root = Path(p0_root).expanduser().resolve()
    readiness_file = Path(readiness_path).expanduser().resolve()
    if readiness_file.is_symlink() or not readiness_file.is_file():
        raise PhotorealPostP0ContinuationError(f"P0 downstream readiness receipt is missing: {readiness_file}")
    if readiness_file.parent != root:
        raise PhotorealPostP0ContinuationError("P0 downstream readiness receipt must live in the exact P0 output root")

    value = _read_json(readiness_file, label="P0 downstream readiness")
    if value.get("format") != READINESS_FORMAT:
        raise PhotorealPostP0ContinuationError("P0 downstream readiness format/version mismatch")
    _numeric_v1(value.get("version"), label="P0 downstream readiness")

    performer_id = _text(status.get("performer_id"), label="P0 performer id", maximum=256)
    if expected_performer_id is not None and performer_id != str(expected_performer_id):
        raise PhotorealPostP0ContinuationError("P0 performer does not match requested continuation")
    if _text(value.get("performer_id"), label="readiness performer id", maximum=256) != performer_id:
        raise PhotorealPostP0ContinuationError("P0 downstream readiness performer mismatch")

    revision = _git_sha(status.get("bodyrig_revision"), label="P0 BodyRig revision")
    if _git_sha(value.get("exact_bodyrig_revision"), label="readiness BodyRig revision") != revision:
        raise PhotorealPostP0ContinuationError("P0 downstream readiness revision mismatch")

    for field, expected in (
        ("verifier_software_qualification_complete", True),
        ("software_qualification_complete", True),
        ("physical_p0_verified", True),
        ("teacher_training_authorized", True),
        ("downstream_teacher_flow_ready", True),
        ("human_visual_acceptance_required", True),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        _require_bool(value.get(field), expected, label=f"readiness.{field}")

    declared_status_path = _text(value.get("p0_status"), label="readiness P0 status path")
    if not _same_path(declared_status_path, status_path):
        raise PhotorealPostP0ContinuationError("P0 downstream readiness binds a different P0 status path")
    if _sha(value.get("p0_status_sha256"), label="readiness P0 status SHA-256") != _sha256_file(status_path):
        raise PhotorealPostP0ContinuationError("P0 downstream readiness P0 status SHA-256 mismatch")

    physical_path = Path(_text(value.get("physical_verification"), label="physical verification path")).expanduser().resolve()
    if physical_path.parent != root:
        raise PhotorealPostP0ContinuationError("physical P0 verification must live in the exact P0 output root")
    physical_sha = _sha(value.get("physical_verification_sha256"), label="physical verification SHA-256")
    if physical_sha != _sha256_file(physical_path):
        raise PhotorealPostP0ContinuationError("physical P0 verification SHA-256 mismatch")
    physical = _read_json(physical_path, label="physical P0 verification")
    if physical.get("format") != PHYSICAL_FORMAT:
        raise PhotorealPostP0ContinuationError("physical P0 verification format/version mismatch")
    _numeric_v1(physical.get("version"), label="physical P0 verification")
    if _text(physical.get("performer_id"), label="physical performer id", maximum=256) != performer_id:
        raise PhotorealPostP0ContinuationError("physical P0 verification performer mismatch")
    if _git_sha(physical.get("exact_bodyrig_revision"), label="physical BodyRig revision") != revision:
        raise PhotorealPostP0ContinuationError("physical P0 verification revision mismatch")
    for field, expected in (
        ("physical_p0_verified", True),
        ("teacher_training_authorized", True),
        ("human_visual_acceptance_required", True),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        _require_bool(physical.get(field), expected, label=f"physical.{field}")

    summary_path = Path(_text(value.get("overnight_summary"), label="overnight summary path")).expanduser().resolve()
    if _sha(value.get("overnight_summary_sha256"), label="overnight summary SHA-256") != _sha256_file(summary_path):
        raise PhotorealPostP0ContinuationError("overnight summary SHA-256 mismatch")
    summary = _read_json(summary_path, label="overnight summary")
    if summary.get("format") != SUMMARY_FORMAT:
        raise PhotorealPostP0ContinuationError("overnight summary format/version mismatch")
    _numeric_v1(summary.get("version"), label="overnight summary")
    if _text(summary.get("performer_id"), label="summary performer id", maximum=256) != performer_id:
        raise PhotorealPostP0ContinuationError("overnight summary performer mismatch")
    if _git_sha(summary.get("bodyrig_revision"), label="summary BodyRig revision") != revision:
        raise PhotorealPostP0ContinuationError("overnight summary revision mismatch")
    if not _same_path(_text(summary.get("output_root"), label="summary output root"), root):
        raise PhotorealPostP0ContinuationError("overnight summary output root mismatch")
    if summary.get("status") != "completed" or summary.get("exit_code") != 0:
        raise PhotorealPostP0ContinuationError("overnight summary is not a completed P0 success")
    for field, expected in (
        ("teacher_training_authorized", True),
        ("human_visual_acceptance_required", True),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        _require_bool(summary.get(field), expected, label=f"summary.{field}")

    if _sha(physical.get("overnight_summary_sha256"), label="physical summary SHA-256") != _sha256_file(summary_path):
        raise PhotorealPostP0ContinuationError("physical verification summary binding mismatch")
    if _sha(physical.get("p0_status_sha256"), label="physical P0 status SHA-256") != _sha256_file(status_path):
        raise PhotorealPostP0ContinuationError("physical verification P0 status binding mismatch")

    verifier_sha = _sha(value.get("verifier_script_sha256"), label="verifier script SHA-256")
    verifier_script = Path(__file__).resolve().parents[1] / "review-tools" / "VERIFY_PHYSICAL_P0_READY.ps1"
    if not verifier_script.is_file() or verifier_script.is_symlink():
        raise PhotorealPostP0ContinuationError("tracked P0 readiness verifier is unavailable")
    if verifier_sha != _sha256_file(verifier_script):
        raise PhotorealPostP0ContinuationError(
            "P0 downstream readiness was not produced by the current tracked readiness verifier"
        )

    return value


def _read_mapping(path: Path, *, label: str) -> dict[str, Any]:
    return _read_json(path, label=label)


def _expected_teacher_input(
    p0_root: Path,
    selection_path: Path,
) -> dict[str, Any]:
    try:
        plan_path, receipt_path, frame_index_path, resolved_selection = resolve_authorized_p0_teacher_inputs(
            p0_root,
            selection_path,
        )
        plan = _read_mapping(plan_path, label="dataset plan")
        receipt = _read_mapping(receipt_path, label="source receipt")
        frame_index = _read_mapping(frame_index_path, label="frame index")
        selection = _read_mapping(resolved_selection, label="appearance epoch selection")
        validate_teacher_input_upstream_versions(plan, receipt, frame_index, selection)
        teacher_input = build_teacher_input(plan, receipt, frame_index, selection)
        validate_teacher_input_document(teacher_input)
        return teacher_input
    except (PhotorealTeacherInputP0RootError, PhotorealTeacherInputError) as exc:
        raise PhotorealPostP0ContinuationError(f"strict teacher input gate rejected continuation: {exc}") from exc


def advance_post_p0_teacher(
    *,
    p0_root: str | Path,
    readiness_path: str | Path,
    work_root: str | Path,
    expected_performer_id: str | None = None,
    selected_epoch_id: str | None = None,
    selected_source_group_ids: Sequence[str] | None = None,
    reviewed_by: str | None = None,
    review_notes: str | None = None,
    approve_human_review: bool = False,
) -> dict[str, Any]:
    root = Path(p0_root).expanduser().resolve()
    work = Path(work_root).expanduser().resolve()
    if work == root or root in work.parents:
        raise PhotorealPostP0ContinuationError("post-P0 continuation work root must be outside the immutable P0 root")

    readiness = validate_downstream_readiness(
        readiness_path,
        root,
        expected_performer_id=expected_performer_id,
    )
    try:
        status, _status_path, _dataset_plan_path, _source_receipt_path, frame_index_path = resolve_authorized_p0_root(root)
    except PhotorealTeacherInputP0RootError as exc:
        raise PhotorealPostP0ContinuationError(f"P0 root authority is invalid: {exc}") from exc

    performer_id = _text(status.get("performer_id"), label="P0 performer id", maximum=256)
    revision = _git_sha(status.get("bodyrig_revision"), label="P0 BodyRig revision")
    frame_index = _read_mapping(frame_index_path, label="frame index")

    try:
        plan = build_appearance_epoch_plan(frame_index)
    except PhotorealAppearanceEpochError as exc:
        raise PhotorealPostP0ContinuationError(f"appearance epoch planning failed: {exc}") from exc
    plan_path = work / "appearance-epoch-plan.json"
    _write_or_require_exact(plan_path, plan, label="appearance epoch plan")

    try:
        handoff, review_template = build_appearance_epoch_review_handoff(plan)
    except PhotorealAppearanceEpochHandoffError as exc:
        raise PhotorealPostP0ContinuationError(f"appearance epoch review handoff failed: {exc}") from exc
    handoff_path = work / "appearance-epoch-review-handoff.json"
    template_path = work / "appearance-epoch-review-template.json"
    _write_or_require_exact(handoff_path, handoff, label="appearance epoch review handoff")
    _write_or_require_exact(template_path, review_template, label="appearance epoch review template")

    review_path = work / "appearance-epoch-human-review.json"
    if review_path.exists():
        existing_review = _read_mapping(review_path, label="appearance epoch human review")
        try:
            canonical_review = build_human_review_record(
                plan,
                handoff,
                selected_epoch_id=_text(
                    existing_review.get("selected_epoch_id"),
                    label="existing review selected epoch id",
                    maximum=256,
                ),
                selected_source_group_ids=list(existing_review.get("selected_source_group_ids") or []),
                reviewed_by=_text(existing_review.get("reviewed_by"), label="existing review reviewer", maximum=256),
                review_notes=_text(existing_review.get("review_notes"), label="existing review notes", maximum=8192),
                approve_human_review=True,
            )
        except (PhotorealAppearanceEpochReviewRecorderError, PhotorealPostP0ContinuationError) as exc:
            raise PhotorealPostP0ContinuationError(f"existing appearance epoch human review is invalid: {exc}") from exc
        _write_or_require_exact(review_path, canonical_review, label="appearance epoch human review")
        review = canonical_review
    elif approve_human_review:
        if selected_epoch_id is None or reviewed_by is None or review_notes is None:
            raise PhotorealPostP0ContinuationError(
                "explicit human approval requires selected epoch id, reviewer and review notes"
            )
        groups = list(selected_source_group_ids or [])
        try:
            review = build_human_review_record(
                plan,
                handoff,
                selected_epoch_id=selected_epoch_id,
                selected_source_group_ids=groups,
                reviewed_by=reviewed_by,
                review_notes=review_notes,
                approve_human_review=True,
            )
        except PhotorealAppearanceEpochReviewRecorderError as exc:
            raise PhotorealPostP0ContinuationError(f"appearance epoch human review failed: {exc}") from exc
        _write_or_require_exact(review_path, review, label="appearance epoch human review")
    else:
        return {
            "format": STATUS_FORMAT,
            "version": VERSION,
            "state": "human-appearance-epoch-review-required",
            "performer_id": performer_id,
            "p0_bodyrig_revision": revision,
            "p0_root": str(root),
            "readiness_path": str(Path(readiness_path).expanduser().resolve()),
            "readiness_sha256": _sha256_file(Path(readiness_path).expanduser().resolve()),
            "work_root": str(work),
            "appearance_epoch_plan": str(plan_path),
            "appearance_epoch_review_handoff": str(handoff_path),
            "appearance_epoch_review_template": str(template_path),
            "candidate_source_groups": list(handoff["candidate_source_groups"]),
            "human_review_complete": False,
            "teacher_input_ready": False,
            "human_visual_acceptance_required": True,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }

    try:
        selection = apply_appearance_epoch_review(plan, review)
    except PhotorealAppearanceEpochReviewError as exc:
        raise PhotorealPostP0ContinuationError(f"appearance epoch selection failed: {exc}") from exc
    selection_path = work / "appearance-epoch-selection.json"
    _write_or_require_exact(selection_path, selection, label="appearance epoch selection")

    teacher_input = _expected_teacher_input(root, selection_path)
    teacher_input_path = work / "teacher-input.json"
    _write_or_require_exact(teacher_input_path, teacher_input, label="strict teacher input")

    return {
        "format": STATUS_FORMAT,
        "version": VERSION,
        "state": "teacher-input-ready",
        "performer_id": performer_id,
        "p0_bodyrig_revision": revision,
        "p0_root": str(root),
        "readiness_path": str(Path(readiness_path).expanduser().resolve()),
        "readiness_sha256": _sha256_file(Path(readiness_path).expanduser().resolve()),
        "work_root": str(work),
        "appearance_epoch_plan": str(plan_path),
        "appearance_epoch_review_handoff": str(handoff_path),
        "appearance_epoch_human_review": str(review_path),
        "appearance_epoch_selection": str(selection_path),
        "teacher_input": str(teacher_input_path),
        "selected_epoch_id": selection["selected_epoch_id"],
        "selected_source_group_ids": list(selection["selected_source_group_ids"]),
        "human_review_complete": True,
        "teacher_input_ready": True,
        "teacher_training_authorized": True,
        "human_visual_acceptance_required": True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "next_stage": "run-pinned-static-teacher-benchmark",
    }
