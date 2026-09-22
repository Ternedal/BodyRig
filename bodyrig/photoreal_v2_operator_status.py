from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .acceptance_status_cli import _git_checkout_state
from .photoreal_post_p0_continuation import (
    PhotorealPostP0ContinuationError,
    validate_downstream_readiness,
)
from .photoreal_p1_likeness_review import (
    PhotorealP1LikenessReviewError,
    validate_likeness_review_receipt,
)
from .photoreal_p2_animation_plan import (
    PhotorealP2AnimationPlanError,
    validate_p2_animation_plan,
)
from .photoreal_p2_exavatar_animation_execution_input import (
    PhotorealP2ExAvatarAnimationExecutionInputError,
    validate_exavatar_animation_execution_input,
)
from .photoreal_p2_exavatar_animation_identity import (
    PhotorealP2ExAvatarAnimationIdentityError,
    validate_exavatar_animation_identity,
)
from .photoreal_p2_exavatar_animation_runner import (
    PhotorealP2ExAvatarAnimationRunnerError,
    validate_animation_execution_receipt,
)
from .photoreal_p2_exavatar_heldout_evaluation_input import (
    PhotorealP2ExAvatarHeldoutEvaluationInputError,
    validate_heldout_evaluation_input,
)
from .photoreal_p2_exavatar_heldout_evaluation_runner import (
    PhotorealP2ExAvatarHeldoutEvaluationRunnerError,
    validate_heldout_evaluation_receipt,
)
from .photoreal_p2_heldout_animated_review_plan import (
    PhotorealP2HeldoutAnimatedReviewPlanError,
    validate_heldout_animated_review_plan,
)
from .photoreal_p2_heldout_animated_human_review import (
    PhotorealP2HeldoutAnimatedHumanReviewError,
    validate_animated_human_review_receipt,
)
from .photoreal_p2_motion_evidence import (
    PhotorealP2MotionEvidenceError,
    validate_motion_evidence_handoff,
    validate_private_motion_index,
)
from .photoreal_p2_motion_selection import (
    PhotorealP2MotionSelectionError,
    validate_motion_source_selection,
)
from .photoreal_p2_motion_preparation_runner import (
    PhotorealP2MotionPreparationRunnerError,
    validate_motion_preparation_receipt,
)
from .photoreal_p3_device_distillation_plan import (
    PhotorealP3DeviceDistillationPlanError,
    validate_p3_device_distillation_plan,
)
from .photoreal_p3_physical_runtime_review import (
    PhotorealP3PhysicalRuntimeReviewError,
    validate_physical_runtime_review_receipt,
)
from .photoreal_teacher_authority import validate_teacher_input_document
from .photoreal_teacher_runner import PhotorealTeacherRunnerError
from .photoreal_teacher_input_p0_root import (
    PhotorealTeacherInputP0RootError,
    resolve_authorized_p0_root,
)

FORMAT = "bodyrig-photoreal-v2-operator-status"
VERSION = 1

_REQUIRED_SCRIPTS = (
    "continue-photoreal-v2-teacher.ps1",
    "prepare-photoreal-v2-appearance-epoch-review.ps1",
    "run-photoreal-v2-exavatar-teacher.ps1",
    "run-photoreal-v2-p1-review.ps1",
    "prepare-photoreal-v2-p2-animation.ps1",
    "prepare-photoreal-v2-p2-motion-evidence.ps1",
    "record-photoreal-v2-p2-motion-selection.ps1",
    "prepare-photoreal-v2-p2-motion-input-plan.ps1",
    "record-photoreal-v2-p2-motion-normalization-selection.ps1",
    "record-photoreal-v2-p2-motion-window-selection.ps1",
    "run-photoreal-v2-p2-motion-preparation.ps1",
    "prepare-photoreal-v2-p2-exavatar-animation-identity.ps1",
    "prepare-photoreal-v2-p2-exavatar-animation-execution-input.ps1",
    "run-photoreal-v2-p2-exavatar-animation.ps1",
    "prepare-photoreal-v2-p2-exavatar-heldout-evaluation-input.ps1",
    "run-photoreal-v2-p2-exavatar-heldout-evaluation.ps1",
    "prepare-photoreal-v2-p2-heldout-animated-review-plan.ps1",
    "prepare-photoreal-v2-p2-heldout-animated-human-review.ps1",
    "record-photoreal-v2-p2-heldout-animated-human-review.ps1",
    "prepare-photoreal-v2-p3-device-distillation.ps1",
    "run-photoreal-v2-p3-quest2-full-software.ps1",
    "run-photoreal-v2-p3-quest2-physical-review-flow.ps1",
)


class PhotorealV2OperatorStatusError(RuntimeError):
    pass


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PhotorealV2OperatorStatusError(f"{label} is missing/not regular: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealV2OperatorStatusError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealV2OperatorStatusError(f"{label} must be a JSON object: {path}")
    return value


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _script(root: Path | None, name: str) -> str:
    if root is None:
        return f".\\{name}"
    return f"& {_ps_quote((root / name).resolve())}"


def _resolve_operator_root(explicit: str | Path | None) -> Path | None:
    if explicit is None:
        return None
    root = Path(explicit).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealV2OperatorStatusError(f"BodyRig operator root not found: {root}")
    missing = [name for name in _REQUIRED_SCRIPTS if not (root / name).is_file()]
    if missing:
        raise PhotorealV2OperatorStatusError(
            "BodyRig operator root is incomplete: " + ", ".join(missing)
        )
    return root


def _git_checkout_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise PhotorealV2OperatorStatusError(
            f"Could not inspect BodyRig operator branch: {exc}"
        ) from exc
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        raise PhotorealV2OperatorStatusError(
            "Could not resolve BodyRig operator branch"
        )
    return branch


def _authorized_command(
    *,
    root: Path | None,
    expected_revision: str,
    command: str,
    message: str,
    next_gate: str,
    state: str = "required",
) -> dict[str, Any]:
    if root is None:
        return {
            "state": state,
            "next_gate": next_gate,
            "next_command": None,
            "message": message + " Inspection-only: pass an operator root to authorize an executable command.",
        }
    try:
        head, clean = _git_checkout_state(root)
    except Exception as exc:
        raise PhotorealV2OperatorStatusError(
            f"Could not verify BodyRig operator checkout: {exc}"
        ) from exc
    if head != expected_revision:
        return {
            "state": "blocked",
            "next_gate": "operator-checkout",
            "next_command": None,
            "message": (
                f"Operator checkout {head} differs from P0 evidence revision "
                f"{expected_revision}. Use the exact evidence revision before continuing."
            ),
        }
    if not clean:
        return {
            "state": "blocked",
            "next_gate": "operator-checkout",
            "next_command": None,
            "message": f"Operator checkout {head} is dirty; Photoreal continuation is fail-closed.",
        }
    branch = _git_checkout_branch(root)
    if branch != "main":
        return {
            "state": "blocked",
            "next_gate": "operator-checkout",
            "next_command": None,
            "message": (
                f"Operator checkout must be on main for canonical Photoreal operators; "
                f"current branch is {branch!r}."
            ),
        }
    return {
        "state": state,
        "next_gate": next_gate,
        "next_command": command,
        "message": message,
    }


def _operator_input_required(
    *,
    next_gate: str,
    message: str,
    missing_inputs: list[str],
) -> dict[str, Any]:
    return {
        "state": "operator-input-required",
        "next_gate": next_gate,
        "next_command": None,
        "message": message,
        "missing_operator_inputs": missing_inputs,
    }


def _appearance_review_root(
    teacher_root: Path,
    explicit: str | Path | None,
) -> Path | None:
    if explicit is not None:
        root = Path(explicit).expanduser().resolve()
        if not (root / "appearance-epoch-visual-review-manifest.json").is_file():
            raise PhotorealV2OperatorStatusError(
                f"Appearance review root lacks canonical manifest: {root}"
            )
        return root
    matches = sorted(
        path
        for path in teacher_root.glob("appearance-epoch-visual-review-*")
        if path.is_dir()
        and (path / "appearance-epoch-visual-review-manifest.json").is_file()
    )
    if len(matches) > 1:
        raise PhotorealV2OperatorStatusError(
            "Multiple appearance review roots exist; pass the exact review root explicitly."
        )
    return matches[0] if matches else None


def _selected_motion_refs(
    selection_path: Path,
    *,
    handoff_path: Path,
    private_index_path: Path,
) -> tuple[list[str], list[str]]:
    try:
        handoff = validate_motion_evidence_handoff(
            _read_json(handoff_path, "P2 motion evidence handoff")
        )
        private_index = validate_private_motion_index(
            _read_json(private_index_path, "private P2 motion source index"),
            handoff=handoff,
        )
        selection = validate_motion_source_selection(
            _read_json(selection_path, "P2 motion source selection"),
            handoff=handoff,
            private_index=private_index,
        )
    except (
        PhotorealP2MotionEvidenceError,
        PhotorealP2MotionSelectionError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise PhotorealV2OperatorStatusError(
            f"P2 motion selection strict readback failed: {exc}"
        ) from exc
    drivers = [str(item["source_ref"]) for item in selection["motion_driver_sources"]]
    heldout = [
        str(item["source_ref"])
        for item in selection["held_out_motion_validation_sources"]
    ]
    return drivers, heldout


def inspect_photoreal_v2_status(
    *,
    p0_root: str | Path,
    operator_root: str | Path | None = None,
    teacher_work_root: str | Path | None = None,
    appearance_review_root: str | Path | None = None,
    asset_root: str | Path | None = None,
    reference_model_root: str | Path | None = None,
    smplx_gender: str | None = None,
    camera_mode: str | None = None,
    p2_motion_config: str | Path | None = None,
    p2_review_selection_input: str | Path | None = None,
    single_motion_driver_source_ref: str | None = None,
    reviewed_by: str | None = None,
    review_notes: str | None = None,
    p3_target_profile: str | Path | None = None,
    p3_machine_probe: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(p0_root).expanduser().resolve()
    try:
        p0_status, _status_path, _plan_path, _receipt_path, _frame_index = (
            resolve_authorized_p0_root(root)
        )
    except PhotorealTeacherInputP0RootError as exc:
        raise PhotorealV2OperatorStatusError(f"P0 authority is invalid: {exc}") from exc

    performer_id = str(p0_status.get("performer_id") or "").strip()
    revision = str(p0_status.get("bodyrig_revision") or "").strip().lower()
    if not performer_id or len(revision) != 40 or any(
        ch not in "0123456789abcdef" for ch in revision
    ):
        raise PhotorealV2OperatorStatusError("P0 authority lacks performer/revision identity")

    teacher = (
        Path(teacher_work_root).expanduser().resolve()
        if teacher_work_root is not None
        else Path(str(root) + "-teacher").resolve()
    )
    op_root = _resolve_operator_root(operator_root)

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "read_only": True,
        "performer_id": performer_id,
        "bodyrig_revision": revision,
        "p0_root": str(root),
        "teacher_work_root": str(teacher),
        "appearance_review_root": None,
        "p0_ready": True,
        "teacher_input_ready": False,
        "static_teacher_built": False,
        "p1_static_teacher_status": None,
        "p2_animated_teacher_status": None,
        "p3_runtime_review_status": None,
        "p3_photoreal_acceptance_authority": False,
        "production_activation": False,
        "missing_operator_inputs": [],
        "state": "required",
        "next_gate": "",
        "next_command": None,
        "message": "",
    }

    readiness = root / "P0_DOWNSTREAM_READINESS.json"
    if not readiness.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p0_downstream_readiness",
            command=(
                f"{_script(op_root, 'continue-photoreal-v2-teacher.ps1')} "
                f"-P0Root {_ps_quote(root)} -PerformerId {_ps_quote(performer_id)} "
                f"-WorkRoot {_ps_quote(teacher)}"
            ),
            message=(
                "P0 is teacher-training-authorized but downstream readiness has not "
                "been materialized/revalidated."
            ),
        )
        result.update(action)
        return result
    try:
        validate_downstream_readiness(
            readiness,
            root,
            expected_performer_id=performer_id,
        )
    except PhotorealPostP0ContinuationError as exc:
        raise PhotorealV2OperatorStatusError(
            f"P0 downstream readiness strict readback failed: {exc}"
        ) from exc

    appearance = _appearance_review_root(teacher, appearance_review_root)
    if appearance is None:
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="appearance_epoch_visual_review",
            command=(
                f"{_script(op_root, 'prepare-photoreal-v2-appearance-epoch-review.ps1')} "
                f"-P0Root {_ps_quote(root)} -WorkRoot {_ps_quote(teacher)}"
            ),
            message=(
                "Prepare the exact-P0 appearance-epoch review pack before human "
                "appearance selection."
            ),
        )
        result.update(action)
        return result
    result["appearance_review_root"] = str(appearance)

    teacher_input_path = teacher / "teacher-input.json"
    if not teacher_input_path.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="appearance_epoch_human_review",
            state="human-review-required",
            command=(
                f"{_script(op_root, 'continue-photoreal-v2-teacher.ps1')} "
                f"-P0Root {_ps_quote(root)} -PerformerId {_ps_quote(performer_id)} "
                f"-WorkRoot {_ps_quote(teacher)}"
            ),
            message=(
                "Appearance epoch still requires explicit human selection. The emitted "
                "command is review-only unless the operator reruns it with explicit "
                "approval inputs."
            ),
        )
        result.update(action)
        return result
    try:
        validate_teacher_input_document(
            _read_json(teacher_input_path, "strict teacher input")
        )
    except (PhotorealTeacherRunnerError, ValueError, KeyError, TypeError) as exc:
        raise PhotorealV2OperatorStatusError(
            f"Teacher input strict readback failed: {exc}"
        ) from exc
    result["teacher_input_ready"] = True

    teacher_manifest = teacher / "exavatar-teacher-output" / "output" / "teacher-manifest.json"
    if not teacher_manifest.is_file():
        missing: list[str] = []
        if asset_root is None:
            missing.append("asset_root")
        if reference_model_root is None:
            missing.append("reference_model_root")
        if smplx_gender not in {"female", "male", "neutral"}:
            missing.append("smplx_gender")
        if camera_mode not in {"colmap", "virtual"}:
            missing.append("camera_mode")
        if missing:
            action = _operator_input_required(
                next_gate="static_teacher_benchmark",
                message=(
                    "Static teacher build needs explicit environment/model inputs; "
                    "BodyRig will not infer them."
                ),
                missing_inputs=missing,
            )
            result.update(action)
            return result
        command = (
            f"{_script(op_root, 'run-photoreal-v2-exavatar-teacher.ps1')} "
            f"-TeacherWorkRoot {_ps_quote(teacher)} "
            f"-AssetRoot {_ps_quote(Path(asset_root).expanduser().resolve())} "
            f"-ReferenceModelRoot {_ps_quote(Path(reference_model_root).expanduser().resolve())} "
            f"-SmplxGender {_ps_quote(smplx_gender or '')} "
            f"-CameraMode {_ps_quote(camera_mode or '')} -RunTeacher"
        )
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="static_teacher_benchmark",
            command=command,
            message="Run the pinned ExAvatar static-teacher benchmark from exact P0 authority.",
        )
        result.update(action)
        return result
    result["static_teacher_built"] = True

    p1_root = teacher / "p1-static-teacher-review"
    p1_receipt_path = p1_root / "p1-likeness-review.json"
    p1_manifest_path = p1_root / "likeness-review" / "p1-likeness-review-manifest.json"
    if not p1_receipt_path.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p1_static_teacher_review",
            state="human-review-required",
            command=(
                f"{_script(op_root, 'run-photoreal-v2-p1-review.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)} "
                f"-AppearanceReviewRoot {_ps_quote(appearance)}"
            ),
            message=(
                "P1 requires semantic alignment, held-out pairing and explicit human "
                "likeness decisions. The operator cannot infer PASS."
            ),
        )
        result.update(action)
        return result
    if not p1_manifest_path.is_file():
        raise PhotorealV2OperatorStatusError(
            "P1 likeness receipt exists without its canonical review manifest"
        )
    try:
        p1 = validate_likeness_review_receipt(
            _read_json(p1_receipt_path, "P1 likeness receipt"),
            review_manifest=_read_json(p1_manifest_path, "P1 likeness manifest"),
        )
    except (PhotorealP1LikenessReviewError, ValueError, KeyError, TypeError) as exc:
        raise PhotorealV2OperatorStatusError(f"P1 strict readback failed: {exc}") from exc
    result["p1_static_teacher_status"] = p1.get("p1_static_teacher_status")
    if (
        p1.get("p1_static_teacher_status") != "pass"
        or p1.get("p2_animation_authorized") is not True
    ):
        result.update(
            {
                "state": "blocked",
                "next_gate": "p1_static_teacher_review",
                "next_command": None,
                "message": "Persisted P1 human review did not PASS; P2 remains blocked.",
            }
        )
        return result

    p2 = teacher / "p2-animated-teacher"
    p2_plan_path = p2 / "p2-animation-plan.json"
    if not p2_plan_path.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_animation_plan",
            command=(
                f"{_script(op_root, 'prepare-photoreal-v2-p2-animation.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)}"
            ),
            message="P1 PASS authorizes creation of the frozen P2 animation plan.",
        )
        result.update(action)
        return result
    try:
        p2_plan = validate_p2_animation_plan(
            _read_json(p2_plan_path, "P2 animation plan")
        )
    except (PhotorealP2AnimationPlanError, ValueError, KeyError, TypeError) as exc:
        raise PhotorealV2OperatorStatusError(f"P2 plan strict readback failed: {exc}") from exc

    handoff_path = p2 / "motion-evidence" / "p2-motion-evidence-handoff.json"
    private_index_path = p2 / "motion-evidence" / "private-motion-source-index.json"
    if not handoff_path.is_file() or not private_index_path.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_motion_evidence",
            command=(
                f"{_script(op_root, 'prepare-photoreal-v2-p2-motion-evidence.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)}"
            ),
            message="Prepare the hash-bound TRAIN/HELD-OUT motion candidate handoff.",
        )
        result.update(action)
        return result

    selection_path = p2 / "p2-motion-source-selection.json"
    if not selection_path.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_motion_source_selection",
            state="human-review-required",
            command=(
                f"{_script(op_root, 'record-photoreal-v2-p2-motion-selection.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)}"
            ),
            message=(
                "Explicit human selection of TRAIN drivers and HELD-OUT validation "
                "sources is required. The emitted command only lists candidates."
            ),
        )
        result.update(action)
        return result

    driver_refs, heldout_refs = _selected_motion_refs(
        selection_path,
        handoff_path=handoff_path,
        private_index_path=private_index_path,
    )
    result["motion_driver_source_refs"] = driver_refs
    result["held_out_validation_source_refs"] = heldout_refs

    motion_input = p2 / "motion-input"
    input_plan = motion_input / "p2-motion-input-plan.json"
    if not input_plan.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_motion_input_plan",
            command=(
                f"{_script(op_root, 'prepare-photoreal-v2-p2-motion-input-plan.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)}"
            ),
            message="Materialize the private motion-input plan from the accepted source selection.",
        )
        result.update(action)
        return result

    normalization = motion_input / "p2-motion-normalization-selection.json"
    if not normalization.is_file():
        missing = []
        if not reviewed_by:
            missing.append("reviewed_by")
        if not review_notes:
            missing.append("review_notes")
        if missing:
            action = _operator_input_required(
                next_gate="p2_motion_normalization_selection",
                message=(
                    "Normalization choice discovery/recording requires an explicit "
                    "reviewer and review note; no eye/view choice will be guessed."
                ),
                missing_inputs=missing,
            )
            result.update(action)
            return result
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_motion_normalization_selection",
            state="human-review-required",
            command=(
                f"{_script(op_root, 'record-photoreal-v2-p2-motion-normalization-selection.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)} -P0Root {_ps_quote(root)} "
                f"-ReviewedBy {_ps_quote(reviewed_by or '')} "
                f"-ReviewNotes {_ps_quote(review_notes or '')}"
            ),
            message=(
                "Review projection/stereo normalization choices. The command describes "
                "choices and cannot approve them without explicit -Choice/-ApproveHumanSelection."
            ),
        )
        result.update(action)
        return result

    window_selection = motion_input / "p2-motion-window-selection.json"
    if not window_selection.is_file():
        missing = []
        if not reviewed_by:
            missing.append("reviewed_by")
        if not review_notes:
            missing.append("review_notes")
        if missing:
            action = _operator_input_required(
                next_gate="p2_motion_window_selection",
                message=(
                    "Motion-window discovery/recording requires an explicit reviewer "
                    "and review note; BodyRig will not choose a window."
                ),
                missing_inputs=missing,
            )
            result.update(action)
            return result
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_motion_window_selection",
            state="human-review-required",
            command=(
                f"{_script(op_root, 'record-photoreal-v2-p2-motion-window-selection.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)} -P0Root {_ps_quote(root)} "
                f"-ReviewedBy {_ps_quote(reviewed_by or '')} "
                f"-ReviewNotes {_ps_quote(review_notes or '')}"
            ),
            message=(
                "Review one motion window per selected source. The command only "
                "describes candidates unless explicit windows are approved."
            ),
        )
        result.update(action)
        return result

    motion_receipt = p2 / "motion-preparation" / "motion-preparation-receipt.json"
    if not motion_receipt.is_file():
        if p2_motion_config is None:
            action = _operator_input_required(
                next_gate="p2_motion_preparation",
                message="P2 motion preparation needs an explicit pinned adapter config.",
                missing_inputs=["p2_motion_config"],
            )
            result.update(action)
            return result
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_motion_preparation",
            command=(
                f"{_script(op_root, 'run-photoreal-v2-p2-motion-preparation.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)} -P0Root {_ps_quote(root)} "
                f"-Config {_ps_quote(Path(p2_motion_config).expanduser().resolve())}"
            ),
            message="Decode/deproject only the human-selected windows and run pinned motion fitting.",
        )
        result.update(action)
        return result

    try:
        motion_authority = validate_motion_preparation_receipt(
            _read_json(motion_receipt, "P2 motion preparation receipt")
        )
    except (
        PhotorealP2MotionPreparationRunnerError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise PhotorealV2OperatorStatusError(
            f"P2 motion preparation strict readback failed: {exc}"
        ) from exc

    identity_receipt = (
        p2 / "animation-input" / "exavatar-identity" / "p2-exavatar-animation-identity.json"
    )
    if not identity_receipt.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_exavatar_identity",
            command=(
                f"{_script(op_root, 'prepare-photoreal-v2-p2-exavatar-animation-identity.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)}"
            ),
            message="Export the exact frozen teacher identity payload for P2 animation.",
        )
        result.update(action)
        return result

    try:
        identity_authority = validate_exavatar_animation_identity(
            _read_json(identity_receipt, "P2 ExAvatar animation identity"),
            output_root=identity_receipt.parent,
        )
    except (
        PhotorealP2ExAvatarAnimationIdentityError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise PhotorealV2OperatorStatusError(
            f"P2 ExAvatar identity strict readback failed: {exc}"
        ) from exc

    execution_input = (
        p2
        / "animation-input"
        / "exavatar-execution"
        / "p2-exavatar-animation-execution-input.json"
    )
    if not execution_input.is_file():
        chosen_driver = (
            single_motion_driver_source_ref.strip()
            if isinstance(single_motion_driver_source_ref, str)
            and single_motion_driver_source_ref.strip()
            else None
        )
        if chosen_driver is not None and chosen_driver not in driver_refs:
            raise PhotorealV2OperatorStatusError(
                "single_motion_driver_source_ref is not one of the human-approved TRAIN drivers"
            )
        if chosen_driver is None:
            if len(driver_refs) == 1:
                chosen_driver = driver_refs[0]
            else:
                action = _operator_input_required(
                    next_gate="p2_animation_execution_input",
                    message=(
                        "More than one TRAIN driver was human-selected. Pass one exact "
                        "approved driver through single_motion_driver_source_ref; the "
                        "router will not choose among them."
                    ),
                    missing_inputs=["single_motion_driver_source_ref"],
                )
                result.update(action)
                return result
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_animation_execution_input",
            command=(
                f"{_script(op_root, 'prepare-photoreal-v2-p2-exavatar-animation-execution-input.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)} "
                f"-MotionDriverSourceRef {_ps_quote(chosen_driver)}"
            ),
            message="Bind the explicit human-approved TRAIN driver to the frozen teacher.",
        )
        result.update(action)
        return result

    try:
        execution_authority = validate_exavatar_animation_execution_input(
            _read_json(execution_input, "P2 ExAvatar animation execution input")
        )
    except (
        PhotorealP2ExAvatarAnimationExecutionInputError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise PhotorealV2OperatorStatusError(
            f"P2 ExAvatar execution-input strict readback failed: {exc}"
        ) from exc
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
    ):
        if (
            execution_authority.get(field) != motion_authority.get(field)
            or execution_authority.get(field) != identity_authority.get(field)
        ):
            raise PhotorealV2OperatorStatusError(
                f"P2 execution-input lineage mismatch: {field}"
            )
    if (
        execution_authority.get("p2_exavatar_animation_identity_sha256")
        != identity_authority.get("p2_exavatar_animation_identity_sha256")
    ):
        raise PhotorealV2OperatorStatusError(
            "P2 execution input targets a different identity receipt"
        )
    if (
        execution_authority.get("p2_motion_preparation_receipt_sha256")
        != motion_authority.get("p2_motion_preparation_receipt_sha256")
    ):
        raise PhotorealV2OperatorStatusError(
            "P2 execution input targets a different motion-preparation receipt"
        )

    animation_receipt = p2 / "animation-execution" / "animation-execution-receipt.json"
    if not animation_receipt.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_animation_execution",
            command=(
                f"{_script(op_root, 'run-photoreal-v2-p2-exavatar-animation.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)}"
            ),
            message=(
                "Run frozen-teacher animation on TRAIN motion. Execution success is "
                "not human visual acceptance."
            ),
        )
        result.update(action)
        return result

    try:
        animation_authority = validate_animation_execution_receipt(
            _read_json(animation_receipt, "P2 animation execution receipt")
        )
    except (
        PhotorealP2ExAvatarAnimationRunnerError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise PhotorealV2OperatorStatusError(
            f"P2 animation execution strict readback failed: {exc}"
        ) from exc
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
    ):
        if animation_authority.get(field) != execution_authority.get(field):
            raise PhotorealV2OperatorStatusError(
                f"P2 animation receipt lineage mismatch: {field}"
            )
    if (
        animation_authority.get("p2_exavatar_animation_execution_input_sha256")
        != execution_authority.get("p2_exavatar_animation_execution_input_sha256")
    ):
        raise PhotorealV2OperatorStatusError(
            "P2 animation receipt targets a different execution input"
        )

    for source_ref in heldout_refs:
        heldout_input = (
            p2
            / "animation-evaluation"
            / "heldout-input"
            / source_ref
            / "p2-exavatar-heldout-evaluation-input.json"
        )
        if not heldout_input.is_file():
            action = _authorized_command(
                root=op_root,
                expected_revision=revision,
                next_gate="p2_heldout_evaluation_input",
                command=(
                    f"{_script(op_root, 'prepare-photoreal-v2-p2-exavatar-heldout-evaluation-input.ps1')} "
                    f"-TeacherWorkRoot {_ps_quote(teacher)} "
                    f"-HeldOutSourceRef {_ps_quote(source_ref)}"
                ),
                message=f"Prepare frozen-teacher HELD-OUT evaluation input for {source_ref}.",
            )
            result.update(action)
            return result
        try:
            heldout_input_authority = validate_heldout_evaluation_input(
                _read_json(heldout_input, "P2 held-out evaluation input")
            )
        except (
            PhotorealP2ExAvatarHeldoutEvaluationInputError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            raise PhotorealV2OperatorStatusError(
                f"P2 held-out evaluation input strict readback failed: {exc}"
            ) from exc
        for field in (
            "performer_id",
            "selected_epoch_id",
            "teacher_input_sha256",
            "p2_animation_plan_sha256",
        ):
            if heldout_input_authority.get(field) != animation_authority.get(field):
                raise PhotorealV2OperatorStatusError(
                    f"P2 held-out input lineage mismatch: {field}"
                )
        if (
            heldout_input_authority.get("p2_exavatar_animation_execution_input_sha256")
            != execution_authority.get("p2_exavatar_animation_execution_input_sha256")
        ):
            raise PhotorealV2OperatorStatusError(
                "P2 held-out input targets a different animation execution input"
            )
        if (
            heldout_input_authority.get("train_animation_execution_receipt_sha256")
            != animation_authority.get("p2_exavatar_animation_execution_receipt_sha256")
        ):
            raise PhotorealV2OperatorStatusError(
                "P2 held-out input targets a different TRAIN animation receipt"
            )

        heldout_receipt = (
            p2
            / "animation-evaluation"
            / "heldout-execution"
            / source_ref
            / "heldout-evaluation-execution-receipt.json"
        )
        if not heldout_receipt.is_file():
            action = _authorized_command(
                root=op_root,
                expected_revision=revision,
                next_gate="p2_heldout_evaluation",
                command=(
                    f"{_script(op_root, 'run-photoreal-v2-p2-exavatar-heldout-evaluation.ps1')} "
                    f"-TeacherWorkRoot {_ps_quote(teacher)} "
                    f"-HeldOutSourceRef {_ps_quote(source_ref)}"
                ),
                message=(
                    f"Run inference-only HELD-OUT evaluation for {source_ref}; "
                    "no training/checkpoint mutation is authorized."
                ),
            )
            result.update(action)
            return result

        try:
            heldout_receipt_authority = validate_heldout_evaluation_receipt(
                _read_json(heldout_receipt, "P2 held-out evaluation execution receipt")
            )
        except (
            PhotorealP2ExAvatarHeldoutEvaluationRunnerError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            raise PhotorealV2OperatorStatusError(
                f"P2 held-out evaluation receipt strict readback failed: {exc}"
            ) from exc
        for field in (
            "performer_id",
            "selected_epoch_id",
            "teacher_input_sha256",
            "p2_animation_plan_sha256",
        ):
            if heldout_receipt_authority.get(field) != heldout_input_authority.get(field):
                raise PhotorealV2OperatorStatusError(
                    f"P2 held-out receipt lineage mismatch: {field}"
                )
        if heldout_receipt_authority.get("held_out_source_ref") != source_ref:
            raise PhotorealV2OperatorStatusError(
                "P2 held-out receipt source reference does not match its workspace"
            )
        if (
            heldout_receipt_authority.get("p2_exavatar_heldout_evaluation_input_sha256")
            != heldout_input_authority.get("p2_exavatar_heldout_evaluation_input_sha256")
        ):
            raise PhotorealV2OperatorStatusError(
                "P2 held-out receipt targets a different held-out input"
            )
        if (
            heldout_receipt_authority.get("train_animation_execution_receipt_sha256")
            != animation_authority.get("p2_exavatar_animation_execution_receipt_sha256")
        ):
            raise PhotorealV2OperatorStatusError(
                "P2 held-out receipt targets a different TRAIN animation receipt"
            )

    animated_review = p2 / "animated-review"
    review_plan = animated_review / "p2-heldout-animated-review-plan.json"
    if not review_plan.is_file():
        if p2_review_selection_input is None:
            action = _operator_input_required(
                next_gate="p2_heldout_review_mapping",
                message=(
                    "Map every P2 review dimension to an already-evaluated HELD-OUT "
                    "source using the canonical operator-supplied selection JSON."
                ),
                missing_inputs=["p2_review_selection_input"],
            )
            result.update(action)
            return result
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_heldout_review_plan",
            command=(
                f"{_script(op_root, 'prepare-photoreal-v2-p2-heldout-animated-review-plan.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)} "
                f"-SelectionInput {_ps_quote(Path(p2_review_selection_input).expanduser().resolve())}"
            ),
            message="Bind exact HELD-OUT videos to the six required human review dimensions.",
        )
        result.update(action)
        return result

    try:
        review_plan_authority = validate_heldout_animated_review_plan(
            _read_json(review_plan, "P2 held-out animated review plan")
        )
    except (
        PhotorealP2HeldoutAnimatedReviewPlanError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise PhotorealV2OperatorStatusError(
            f"P2 held-out review plan strict readback failed: {exc}"
        ) from exc

    human_manifest = (
        animated_review
        / "human-review"
        / "p2-heldout-animated-human-review-manifest.json"
    )
    if not human_manifest.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p2_animated_human_review_pack",
            state="human-review-required",
            command=(
                f"{_script(op_root, 'prepare-photoreal-v2-p2-heldout-animated-human-review.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)}"
            ),
            message=(
                "Prepare the private HELD-OUT animated review pack. This records no "
                "PASS/FAIL decision."
            ),
        )
        result.update(action)
        return result

    p2_receipt_path = animated_review / "p2-heldout-animated-human-review.json"
    if not p2_receipt_path.is_file():
        result.update(
            {
                "state": "human-review-required",
                "next_gate": "p2_animated_human_review",
                "next_command": None,
                "message": (
                    "Review every motion dimension and quality check, then use "
                    "record-photoreal-v2-p2-heldout-animated-human-review.ps1 with "
                    "explicit PASS/FAIL decisions. The status router never fills them in."
                ),
            }
        )
        return result
    try:
        p2_review = validate_animated_human_review_receipt(
            _read_json(p2_receipt_path, "P2 animated human review receipt"),
            review_manifest=_read_json(human_manifest, "P2 animated human review manifest"),
        )
    except (
        PhotorealP2HeldoutAnimatedHumanReviewError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise PhotorealV2OperatorStatusError(
            f"P2 human review strict readback failed: {exc}"
        ) from exc
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
    ):
        if p2_review.get(field) != animation_authority.get(field):
            raise PhotorealV2OperatorStatusError(
                f"P2 human-review lineage mismatch: {field}"
            )
    if (
        p2_review.get("p2_heldout_animated_review_plan_sha256")
        != review_plan_authority.get("p2_heldout_animated_review_plan_sha256")
    ):
        raise PhotorealV2OperatorStatusError(
            "P2 human review targets a different held-out review plan"
        )
    result["p2_animated_teacher_status"] = p2_review.get("human_animated_review_status")
    if (
        p2_review.get("human_animated_review_status") != "pass"
        or p2_review.get("p3_device_distillation_authorized") is not True
    ):
        result.update(
            {
                "state": "blocked",
                "next_gate": "p2_animated_human_review",
                "next_command": None,
                "message": "Persisted P2 human review did not PASS; P3 remains blocked.",
            }
        )
        return result

    p3 = teacher / "p3-device-distillation"
    p3_plan = p3 / "p3-device-distillation-plan.json"
    if not p3_plan.is_file():
        if p3_target_profile is None:
            action = _operator_input_required(
                next_gate="p3_device_distillation_plan",
                message="P3 planning requires an explicit device target profile.",
                missing_inputs=["p3_target_profile"],
            )
            result.update(action)
            return result
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p3_device_distillation_plan",
            command=(
                f"{_script(op_root, 'prepare-photoreal-v2-p3-device-distillation.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)} "
                f"-TargetProfile {_ps_quote(Path(p3_target_profile).expanduser().resolve())}"
            ),
            message="Bind the P2 PASS teacher to an explicit device target profile.",
        )
        result.update(action)
        return result

    try:
        current_p3_plan = validate_p3_device_distillation_plan(
            _read_json(p3_plan, "P3 device distillation plan")
        )
    except (
        PhotorealP3DeviceDistillationPlanError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise PhotorealV2OperatorStatusError(
            f"P3 device distillation plan strict readback failed: {exc}"
        ) from exc

    current_p3_expected = {
        "performer_id": p2_review.get("performer_id"),
        "selected_epoch_id": p2_review.get("selected_epoch_id"),
        "teacher_input_sha256": p2_review.get("teacher_input_sha256"),
        "p2_animation_plan_sha256": p2_review.get("p2_animation_plan_sha256"),
        "p2_exavatar_animation_execution_input_sha256": p2_review.get(
            "p2_exavatar_animation_execution_input_sha256"
        ),
        "p2_animated_human_review_sha256": p2_review.get(
            "p2_heldout_animated_human_review_sha256"
        ),
    }
    stale_p3_fields = [
        field
        for field, expected in current_p3_expected.items()
        if current_p3_plan.get(field) != expected
    ]
    if stale_p3_fields:
        result.update(
            {
                "state": "blocked",
                "next_gate": "p3_lineage",
                "next_command": None,
                "message": (
                    "Persisted P3 distillation plan does not target the current P2 "
                    "accepted evidence: " + ", ".join(stale_p3_fields)
                ),
            }
        )
        return result

    p3_work = p3 / "quest2-full-software"
    p3_software_summary = p3_work / "p3-quest2-full-software.json"
    runtime_review_workspace = p3_work / "continuation" / "runtime-review"
    physical_review = runtime_review_workspace / "p3-physical-runtime-review.json"
    if physical_review.is_file():
        try:
            p3_review = validate_physical_runtime_review_receipt(
                _read_json(physical_review, "P3 physical runtime review")
            )
        except (
            PhotorealP3PhysicalRuntimeReviewError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            raise PhotorealV2OperatorStatusError(
                f"P3 physical review strict readback failed: {exc}"
            ) from exc
        status = str(
            p3_review.get("physical_runtime_review_status")
            or p3_review.get("runtime_review_status")
            or ""
        ).lower()
        result["p3_runtime_review_status"] = status or None
        lineage_fields = (
            "performer_id",
            "selected_epoch_id",
            "teacher_input_sha256",
            "p2_animation_plan_sha256",
            "p2_exavatar_animation_execution_input_sha256",
            "p2_animated_human_review_sha256",
            "p3_device_distillation_plan_sha256",
            "target_profile_sha256",
        )
        mismatched = [
            field
            for field in lineage_fields
            if p3_review.get(field) != current_p3_plan.get(field)
        ]
        if mismatched:
            result.update(
                {
                    "state": "blocked",
                    "next_gate": "p3_lineage",
                    "next_command": None,
                    "message": (
                        "Persisted P3 physical review is stale or targets a different "
                        "current distillation plan: " + ", ".join(mismatched)
                    ),
                }
            )
            return result
        accepted = (
            p3_review.get("runtime_acceptance_authority") is True
            and p3_review.get("photoreal_acceptance_authority") is True
        )
        result["p3_photoreal_acceptance_authority"] = accepted
        if not accepted:
            result.update(
                {
                    "state": "blocked",
                    "next_gate": "p3_physical_runtime_review",
                    "next_command": None,
                    "message": "Persisted P3 physical review does not grant runtime/photoreal acceptance.",
                }
            )
            return result
        result.update(
            {
                "state": "p3-complete",
                "next_gate": "photoreal_person_binding",
                "next_command": None,
                "message": (
                    "P3 physical runtime/photoreal acceptance is valid. Bind this exact "
                    "receipt to the canonical Person before using photoreal-digital-twin-status.ps1. "
                    "Production activation is still false at this boundary."
                ),
            }
        )
        return result

    if not p3_software_summary.is_file():
        action = _authorized_command(
            root=op_root,
            expected_revision=revision,
            next_gate="p3_quest2_full_software",
            command=(
                f"{_script(op_root, 'run-photoreal-v2-p3-quest2-full-software.ps1')} "
                f"-TeacherWorkRoot {_ps_quote(teacher)} "
                f"-DistillationPlan {_ps_quote(p3_plan)}"
            ),
            message=(
                "Run the complete software-only Quest 2 P3 continuation. It stops "
                "before physical PASS/FAIL authority."
            ),
        )
        result.update(action)
        return result

    if p3_machine_probe is None:
        action = _operator_input_required(
            next_gate="p3_physical_runtime_review",
            message=(
                "Quest 2 software handoff is complete. Physical review requires an "
                "actual machine probe from the target device."
            ),
            missing_inputs=["p3_machine_probe"],
        )
        result.update(action)
        return result

    action = _authorized_command(
        root=op_root,
        expected_revision=revision,
        next_gate="p3_physical_runtime_review",
        state="physical-review-required",
        command=(
            f"{_script(op_root, 'run-photoreal-v2-p3-quest2-physical-review-flow.ps1')} "
            f"-RuntimeReviewWorkspace {_ps_quote(runtime_review_workspace)} "
            f"-MachineProbe {_ps_quote(Path(p3_machine_probe).expanduser().resolve())}"
        ),
        message=(
            "Run the guided Quest 2 physical review flow. Human/device PASS is "
            "operator-supplied; the status router cannot synthesize it."
        ),
    )
    result.update(action)
    return result
