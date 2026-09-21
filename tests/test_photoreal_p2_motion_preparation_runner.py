from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_motion_evidence as evidence
import bodyrig.photoreal_p2_motion_preparation_runner as runner
from bodyrig.photoreal_p2_motion_input_plan import build_motion_input_plan
from bodyrig.photoreal_p2_motion_normalization_selection import (
    PhotorealP2MotionNormalizationSelectionError,
    build_normalization_selection,
    validate_normalization_selection,
)
from bodyrig.photoreal_p2_motion_preparation_runner import (
    PhotorealP2MotionPreparationRunnerError,
    build_motion_preparation_request,
    run_motion_preparation_files,
    validate_motion_preparation_receipt,
)
from bodyrig.photoreal_p2_motion_selection import build_motion_source_selection


def _candidate(
    *,
    ref: str,
    group: str,
    split: str,
    sha: str,
    size: int,
    spatial: bool = False,
) -> dict[str, object]:
    return {
        "source_ref": ref,
        "group_ref": group,
        "split": split,
        "kind": "video",
        "source_sha256": sha * 64,
        "size_bytes": size,
        "information_score": 100.0,
        "width": 3840,
        "height": 2160,
        "projection": "equi" if spatial else "flat",
        "stereo_layout": "side-by-side" if spatial else "mono",
        "preparation_mode": (
            "exact-authorized-deprojection-required"
            if spatial
            else "direct-exavatar-video"
        ),
        "authorized_observation_count": 2,
        "timestamped_observation_count": 2,
        "view_bins": ["front"],
        "coverage": ["face-front", "full-body-front"],
    }


def _projection_authority() -> dict[str, object]:
    return {
        "format": "bodyrig-explicit-projection-authority",
        "version": 1,
        "projection_type": "equi",
        "stereo_layout": "side-by-side",
        "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "equirectangular_bounds_fraction": {
            "top": 0.0,
            "bottom": 0.0,
            "left": 0.0,
            "right": 0.0,
        },
        "deprojection_authority": False,
    }


def _artifacts(
    tmp_path: Path,
    *,
    spatial_driver: bool = False,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    train_path = tmp_path / "train.mp4"
    eval_path = tmp_path / "eval.mp4"
    train_path.write_bytes(b"train-source")
    eval_path.write_bytes(b"eval-source")

    private: dict[str, object] = {
        "format": evidence.PRIVATE_INDEX_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "p2_animation_plan_sha256": "b" * 64,
        "entries": [
            {
                "source_ref": "src-driver",
                "group_ref": "grp-train",
                "split": "train",
                "source_key": "scene:train",
                "group_id": "scene:train",
                "resolved_path": str(train_path),
                "source_sha256": "c" * 64,
                "size_bytes": train_path.stat().st_size,
            },
            {
                "source_ref": "src-heldout",
                "group_ref": "grp-eval",
                "split": "evaluation",
                "source_key": "scene:eval",
                "group_id": "scene:eval",
                "resolved_path": str(eval_path),
                "source_sha256": "d" * 64,
                "size_bytes": eval_path.stat().st_size,
            },
        ],
        "entry_count": 2,
        "build_private": True,
        "source_media_rehash_performed": False,
        "production_activation": False,
    }
    private["p2_motion_private_index_sha256"] = evidence._digest(
        private,
        omit="p2_motion_private_index_sha256",
    )

    handoff: dict[str, object] = {
        "format": evidence.HANDOFF_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "p2_animation_plan_sha256": "b" * 64,
        "p2_motion_private_index_sha256": private[
            "p2_motion_private_index_sha256"
        ],
        "motion_driver_candidates": [
            _candidate(
                ref="src-driver",
                group="grp-train",
                split="train",
                sha="c",
                size=train_path.stat().st_size,
                spatial=spatial_driver,
            )
        ],
        "held_out_motion_validation_candidates": [
            _candidate(
                ref="src-heldout",
                group="grp-eval",
                split="evaluation",
                sha="d",
                size=eval_path.stat().st_size,
            )
        ],
        "motion_driver_candidate_count": 1,
        "held_out_motion_validation_candidate_count": 1,
        "operator_requirements": {
            "select_at_least_one_training_split_motion_driver": True,
            "select_at_least_one_evaluation_split_validation_source": True,
            "preserve_train_evaluation_group_disjointness": True,
            "never_use_evaluation_bytes_for_appearance_training": True,
            "require_exact_deprojection_before_fit_when_flagged": True,
            "record_human_selection": True,
        },
        "source_media_rehash_performed": False,
        "human_motion_source_selection_required": True,
        "human_motion_source_selection_complete": False,
        "p2_motion_input_authorized": False,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    handoff["p2_motion_evidence_handoff_sha256"] = evidence._digest(
        handoff,
        omit="p2_motion_evidence_handoff_sha256",
    )

    selection = build_motion_source_selection(
        handoff,
        private,
        motion_driver_source_refs=["src-driver"],
        held_out_validation_source_refs=["src-heldout"],
        reviewed_by="operator",
        review_notes="Selected exact P2 motion sources.",
        approve_human_selection=True,
    )
    input_plan = build_motion_input_plan(handoff, private, selection)

    scan_plan: dict[str, object] = {
        "format": "bodyrig-photoreal-scan-plan",
        "version": 1,
        "performer_id": "42",
        "sources": [
            {
                "source_key": "scene:train",
                "source_sha256": "c" * 64,
                "resolved_path": str(train_path),
                "kind": "video",
                "split": "train",
                "group_id": "scene:train",
                "projection": "equi" if spatial_driver else "flat",
                "projection_authority": (
                    _projection_authority() if spatial_driver else None
                ),
                "stereo_layout": "side-by-side" if spatial_driver else "mono",
            },
            {
                "source_key": "scene:eval",
                "source_sha256": "d" * 64,
                "resolved_path": str(eval_path),
                "kind": "video",
                "split": "evaluation",
                "group_id": "scene:eval",
                "projection": "flat",
                "projection_authority": None,
                "stereo_layout": "mono",
            },
        ],
        "all_sources_sha256_bound": True,
        "train_evaluation_assignment_inherited": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    normalization = build_normalization_selection(
        handoff,
        private,
        selection,
        input_plan,
        scan_plan,
        choices=(
            {"src-driver": {"eye": "left", "viewport_id": "v00"}}
            if spatial_driver
            else None
        ),
        reviewed_by="operator",
        review_notes="Confirmed exact motion normalization.",
        approve_human_selection=True,
    )
    return handoff, private, selection, input_plan, normalization, scan_plan


def _config(command: list[str]) -> dict[str, object]:
    return {
        "format": runner.CONFIG_FORMAT,
        "version": 1,
        "adapter": runner.PINNED_ADAPTER,
        "revision": "adapter-rev-1",
        "command": command,
        "timeout_seconds": 30,
        "motion_fitting_backend": runner.PINNED_FITTING_BACKEND,
        "motion_fitting_camera_mode": runner.PINNED_CAMERA_MODE,
        "supported_normalization_actions": list(
            runner.SUPPORTED_NORMALIZATION_ACTIONS
        ),
        "reports_exact_motion_path_contract": True,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _fake_adapter(path: Path) -> None:
    path.write_text(
        r"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--bodyrig-request", required=True)
parser.add_argument("--bodyrig-output", required=True)
parser.add_argument("--bodyrig-adapter", required=True)
parser.add_argument("--bodyrig-revision", required=True)
args = parser.parse_args()

request = json.loads(Path(args.bodyrig_request).read_text(encoding="utf-8"))
out = Path(args.bodyrig_output)
results = []
for task in request["tasks"]:
    ref = task["source_ref"]
    motion = out / "tasks" / ref / "motion"
    frames = motion / "frames"
    cams = motion / "cam_params"
    smplx = motion / "smplx_optimized" / "smplx_params_smoothed"
    frames.mkdir(parents=True)
    cams.mkdir(parents=True)
    smplx.mkdir(parents=True)
    frame = frames / "0.png"
    camera = cams / "0.json"
    params = smplx / "0.json"
    frame.write_bytes(b"png")
    camera.write_text(json.dumps({"R": [], "t": [], "focal": [], "princpt": [], "extra": 1}) + "\n", encoding="utf-8")
    params.write_text(
        json.dumps(
            {
                "root_pose": [],
                "body_pose": [],
                "jaw_pose": [],
                "leye_pose": [],
                "reye_pose": [],
                "lhand_pose": [],
                "rhand_pose": [],
                "expr": [],
                "trans": [],
                "extra": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = []
    for file in (frame, camera, params):
        relative = file.relative_to(out).as_posix()
        artifacts.append(
            {
                "relative_path": relative,
                "size_bytes": file.stat().st_size,
                "sha256": sha(file),
            }
        )
    results.append(
        {
            "source_ref": ref,
            "split": task["split"],
            "role": task["role"],
            "normalization_action": task["normalization_action"],
            "motion_path_relative": f"tasks/{ref}/motion",
            "frame_count": 1,
            "source_media_rehash_performed": False,
            "artifacts": artifacts,
        }
    )

manifest = {
    "format": "bodyrig-photoreal-p2-motion-preparation-manifest",
    "version": 1,
    "performer_id": request["performer_id"],
    "selected_epoch_id": request["selected_epoch_id"],
    "teacher_input_sha256": request["teacher_input_sha256"],
    "p2_animation_plan_sha256": request["p2_animation_plan_sha256"],
    "p2_motion_input_plan_sha256": request["p2_motion_input_plan_sha256"],
    "p2_motion_normalization_selection_sha256": request["p2_motion_normalization_selection_sha256"],
    "p0_scan_plan_file_sha256": request["p0_scan_plan_file_sha256"],
    "adapter": request["adapter"],
    "adapter_revision": request["adapter_revision"],
    "motion_fitting_backend": request["motion_fitting_backend"],
    "motion_fitting_camera_mode": request["motion_fitting_camera_mode"],
    "task_results": results,
    "task_count": len(results),
    "source_media_rehash_performed": False,
    "evaluation_appearance_training_authorized": False,
    "motion_input_preparation_complete": True,
    "p2_animation_execution_authorized": False,
    "p2_animated_teacher_acceptance_authority": False,
    "quest_distillation_authorized": False,
    "photoreal_acceptance_authority": False,
    "production_activation": False,
}
(out / "motion-preparation-manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
""".lstrip(),
        encoding="utf-8",
    )


def test_request_binds_selected_sources_to_original_p0_projection_authority(
    tmp_path: Path,
) -> None:
    handoff, private, selection, input_plan, normalization, scan_plan = _artifacts(
        tmp_path,
        spatial_driver=True,
    )
    request = build_motion_preparation_request(
        _config(["python"]),
        handoff,
        private,
        selection,
        input_plan,
        normalization,
        scan_plan,
        scan_plan_file_sha256="e" * 64,
    )

    driver = next(item for item in request["tasks"] if item["role"] == "motion-driver")
    assert driver["normalization_action"] == "exact-authorized-deprojection"
    assert driver["projection"] == "equi"
    assert driver["stereo_layout"] == "side-by-side"
    assert driver["projection_authority"] == _projection_authority()
    assert driver["normalization_strategy"] == "equirectangular-deprojection"
    assert driver["selected_eye"] == "left"
    assert driver["selected_viewport_id"] == "v00"
    assert request["p2_motion_normalization_selection_sha256"] == normalization["p2_motion_normalization_selection_sha256"]
    assert request["source_media_rehash_performed"] is False
    assert request["p2_animation_execution_authorized"] is False


def test_request_rejects_missing_spatial_projection_authority(tmp_path: Path) -> None:
    handoff, private, selection, input_plan, normalization, scan_plan = _artifacts(
        tmp_path,
        spatial_driver=True,
    )
    scan_plan["sources"][0]["projection_authority"] = None

    with pytest.raises(
        PhotorealP2MotionPreparationRunnerError,
        match="not execution-authoritative equi geometry",
    ):
        build_motion_preparation_request(
            _config(["python"]),
            handoff,
            private,
            selection,
            input_plan,
            normalization,
            scan_plan,
            scan_plan_file_sha256="e" * 64,
        )


def test_request_rejects_source_size_drift_without_rehashing(tmp_path: Path) -> None:
    handoff, private, selection, input_plan, normalization, scan_plan = _artifacts(tmp_path)
    Path(private["entries"][0]["resolved_path"]).write_bytes(b"size-drift")

    with pytest.raises(
        PhotorealP2MotionPreparationRunnerError,
        match="size drifted before preparation",
    ):
        build_motion_preparation_request(
            _config(["python"]),
            handoff,
            private,
            selection,
            input_plan,
            normalization,
            scan_plan,
            scan_plan_file_sha256="e" * 64,
        )


def test_runner_emits_core_verified_receipt_and_opens_animation_execution(
    tmp_path: Path,
) -> None:
    handoff, private, selection, input_plan, normalization, scan_plan = _artifacts(tmp_path)
    adapter = tmp_path / "fake_adapter.py"
    _fake_adapter(adapter)

    config_path = tmp_path / "config.json"
    handoff_path = tmp_path / "handoff.json"
    private_path = tmp_path / "private.json"
    selection_path = tmp_path / "selection.json"
    input_plan_path = tmp_path / "input-plan.json"
    normalization_path = tmp_path / "normalization.json"
    scan_path = tmp_path / "scan-plan.json"
    workspace = tmp_path / "workspace"
    _write_json(config_path, _config([sys.executable, str(adapter)]))
    _write_json(handoff_path, handoff)
    _write_json(private_path, private)
    _write_json(selection_path, selection)
    _write_json(input_plan_path, input_plan)
    _write_json(normalization_path, normalization)
    _write_json(scan_path, scan_plan)

    receipt = run_motion_preparation_files(
        config_path,
        handoff_path,
        private_path,
        selection_path,
        input_plan_path,
        normalization_path,
        scan_path,
        workspace,
    )

    assert receipt["generated_artifact_bytes_verified_by_core"] is True
    assert receipt["source_media_rehash_performed"] is False
    assert receipt["evaluation_appearance_training_authorized"] is False
    assert receipt["motion_input_preparation_complete"] is True
    assert receipt["p2_animation_execution_authorized"] is True
    assert receipt["p2_animated_teacher_acceptance_authority"] is False
    assert receipt["quest_distillation_authorized"] is False
    assert receipt["photoreal_acceptance_authority"] is False
    assert receipt["production_activation"] is False
    assert receipt["task_count"] == 2
    assert (workspace / "motion-preparation-receipt.json").is_file()


def test_receipt_rejects_resealed_downstream_authority_escalation(
    tmp_path: Path,
) -> None:
    handoff, private, selection, input_plan, normalization, scan_plan = _artifacts(tmp_path)
    adapter = tmp_path / "fake_adapter.py"
    _fake_adapter(adapter)

    paths = {
        "config": tmp_path / "config.json",
        "handoff": tmp_path / "handoff.json",
        "private": tmp_path / "private.json",
        "selection": tmp_path / "selection.json",
        "input": tmp_path / "input-plan.json",
        "normalization": tmp_path / "normalization.json",
        "scan": tmp_path / "scan-plan.json",
    }
    _write_json(paths["config"], _config([sys.executable, str(adapter)]))
    _write_json(paths["handoff"], handoff)
    _write_json(paths["private"], private)
    _write_json(paths["selection"], selection)
    _write_json(paths["input"], input_plan)
    _write_json(paths["normalization"], normalization)
    _write_json(paths["scan"], scan_plan)

    receipt = run_motion_preparation_files(
        paths["config"],
        paths["handoff"],
        paths["private"],
        paths["selection"],
        paths["input"],
        paths["normalization"],
        paths["scan"],
        tmp_path / "workspace",
    )
    tampered = copy.deepcopy(receipt)
    tampered["quest_distillation_authorized"] = True
    tampered["p2_motion_preparation_receipt_sha256"] = runner._digest(
        tampered,
        omit="p2_motion_preparation_receipt_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionPreparationRunnerError,
        match="authority mismatch: quest_distillation_authorized",
    ):
        validate_motion_preparation_receipt(tampered)


def test_normalization_selection_requires_human_approval_for_spatial_choice(
    tmp_path: Path,
) -> None:
    handoff, private, selection, input_plan, _normalization, scan_plan = _artifacts(
        tmp_path,
        spatial_driver=True,
    )

    with pytest.raises(
        PhotorealP2MotionNormalizationSelectionError,
        match="requires explicit human eye/viewport approval",
    ):
        build_normalization_selection(
            handoff,
            private,
            selection,
            input_plan,
            scan_plan,
            choices={"src-driver": {"eye": "left", "viewport_id": "v00"}},
            reviewed_by="operator",
            review_notes="Review attempted without approval.",
            approve_human_selection=False,
        )


def test_normalization_selection_rejects_viewport_outside_authority(
    tmp_path: Path,
) -> None:
    handoff, private, selection, input_plan, _normalization, scan_plan = _artifacts(
        tmp_path,
        spatial_driver=True,
    )

    with pytest.raises(
        PhotorealP2MotionNormalizationSelectionError,
        match="viewport is outside authorized universe",
    ):
        build_normalization_selection(
            handoff,
            private,
            selection,
            input_plan,
            scan_plan,
            choices={"src-driver": {"eye": "left", "viewport_id": "v99"}},
            reviewed_by="operator",
            review_notes="Invalid viewport should fail closed.",
            approve_human_selection=True,
        )


def test_normalization_selection_auto_resolves_flat_mono_without_human_choice(
    tmp_path: Path,
) -> None:
    handoff, private, selection, input_plan, normalization, _scan_plan = _artifacts(
        tmp_path,
    )

    assert normalization["human_normalization_selection_required"] is False
    assert normalization["human_normalization_selection_complete"] is True
    by_ref = {item["source_ref"]: item for item in normalization["selections"]}
    assert by_ref["src-driver"]["normalization_strategy"] == "direct-flat-mono"
    assert by_ref["src-driver"]["selected_eye"] == "mono"
    assert by_ref["src-driver"]["selected_viewport_id"] is None
    assert by_ref["src-driver"]["human_selected"] is False


def test_normalization_selection_rejects_resealed_animation_authority(
    tmp_path: Path,
) -> None:
    handoff, private, selection, input_plan, normalization, _scan_plan = _artifacts(
        tmp_path,
    )
    tampered = copy.deepcopy(normalization)
    tampered["p2_animation_execution_authorized"] = True
    from bodyrig import photoreal_p2_motion_normalization_selection as norm_module

    tampered["p2_motion_normalization_selection_sha256"] = norm_module._digest(
        tampered,
        omit="p2_motion_normalization_selection_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionNormalizationSelectionError,
        match="authority mismatch: p2_animation_execution_authorized",
    ):
        validate_normalization_selection(tampered, input_plan=input_plan)
