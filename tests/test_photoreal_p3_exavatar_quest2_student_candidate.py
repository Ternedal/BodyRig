from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import tools.photoreal_p3_exavatar_quest2_student_candidate as candidate
from tools.photoreal_p3_exavatar_quest2_student_candidate import (
    Quest2StudentCandidateError,
)


def test_exavatar_joint_names_normalize_to_bodyrig_order() -> None:
    exavatar = (
        "Pelvis",
        "L_Hip",
        "R_Hip",
        "Spine_1",
        "L_Knee",
        "R_Knee",
        "Spine_2",
        "L_Ankle",
        "R_Ankle",
        "Spine_3",
        "L_Foot",
        "R_Foot",
        "Neck",
        "L_Collar",
        "R_Collar",
        "Head",
        "L_Shoulder",
        "R_Shoulder",
        "L_Elbow",
        "R_Elbow",
        "L_Wrist",
        "R_Wrist",
        "Jaw",
        "L_Eye",
        "R_Eye",
        "L_Index_1",
        "L_Index_2",
        "L_Index_3",
        "L_Middle_1",
        "L_Middle_2",
        "L_Middle_3",
        "L_Pinky_1",
        "L_Pinky_2",
        "L_Pinky_3",
        "L_Ring_1",
        "L_Ring_2",
        "L_Ring_3",
        "L_Thumb_1",
        "L_Thumb_2",
        "L_Thumb_3",
        "R_Index_1",
        "R_Index_2",
        "R_Index_3",
        "R_Middle_1",
        "R_Middle_2",
        "R_Middle_3",
        "R_Pinky_1",
        "R_Pinky_2",
        "R_Pinky_3",
        "R_Ring_1",
        "R_Ring_2",
        "R_Ring_3",
        "R_Thumb_1",
        "R_Thumb_2",
        "R_Thumb_3",
    )
    from bodyrig.bridges.sith_smplx_vrm_fitter import SMPLX_JOINT_NAMES

    candidate._validate_joint_semantics(
        exavatar,
        tuple(SMPLX_JOINT_NAMES),
    )


def test_exavatar_joint_semantic_drift_is_rejected() -> None:
    from bodyrig.bridges.sith_smplx_vrm_fitter import SMPLX_JOINT_NAMES

    exavatar = tuple(SMPLX_JOINT_NAMES)
    drifted = ("pelvis", "right_hip", *exavatar[2:])

    with pytest.raises(
        Quest2StudentCandidateError,
        match="joint semantic universe differs",
    ):
        candidate._validate_joint_semantics(
            drifted,
            tuple(SMPLX_JOINT_NAMES),
        )


def _request() -> dict[str, object]:
    value: dict[str, object] = {
        "format": candidate.REQUEST_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p3_device_distillation_plan_sha256": "2" * 64,
        "target_profile": {"target_model": "quest-2"},
        "adapter": "quest2-candidate",
        "adapter_revision": "a" * 64,
        "student_representation": "skinned-mesh-pbr",
        "student_components": [
            "specialized-eye-component",
            "teacher-derived-hair-component",
        ],
        "staged_teacher_sources": [],
        "staged_teacher_only": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value["p3_device_distillation_request_sha256"] = candidate._digest(value)
    return value


def _reseal(value: dict[str, object]) -> None:
    value["p3_device_distillation_request_sha256"] = candidate._digest(
        value,
        omit="p3_device_distillation_request_sha256",
    )


def test_validate_request_accepts_exact_quest2_candidate_binding() -> None:
    request = _request()

    candidate._validate_request(
        request,
        adapter="quest2-candidate",
        revision="a" * 64,
        representation="skinned-mesh-pbr",
        student_components=(
            "specialized-eye-component,"
            "teacher-derived-hair-component"
        ),
    )


def test_validate_request_rejects_resealed_runtime_authority() -> None:
    request = _request()
    request["runtime_acceptance_authority"] = True
    _reseal(request)

    with pytest.raises(
        Quest2StudentCandidateError,
        match="runtime_acceptance_authority",
    ):
        candidate._validate_request(
            request,
            adapter="quest2-candidate",
            revision="a" * 64,
            representation="skinned-mesh-pbr",
            student_components=(
                "specialized-eye-component,"
                "teacher-derived-hair-component"
            ),
        )


def test_validate_request_rejects_component_cli_drift() -> None:
    request = _request()

    with pytest.raises(
        Quest2StudentCandidateError,
        match="component CLI binding",
    ):
        candidate._validate_request(
            request,
            adapter="quest2-candidate",
            revision="a" * 64,
            representation="skinned-mesh-pbr",
            student_components="specialized-eye-component",
        )


def test_validate_request_rejects_digest_tamper() -> None:
    request = _request()
    request["performer_id"] = "different"

    with pytest.raises(
        Quest2StudentCandidateError,
        match="digest mismatch",
    ):
        candidate._validate_request(
            request,
            adapter="quest2-candidate",
            revision="a" * 64,
            representation="skinned-mesh-pbr",
            student_components=(
                "specialized-eye-component,"
                "teacher-derived-hair-component"
            ),
        )


def _workspace_request() -> dict[str, object]:
    return {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
    }


def _workspace(
    tmp_path: Path,
    *,
    asset_payload: bytes = b"model-asset",
) -> Path:
    root = tmp_path / "workspace"
    repo = root / "repos" / "ExAvatar_RELEASE"
    config = repo / "avatar" / "main" / "config.py"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"config")
    asset = (
        repo
        / "avatar"
        / "common"
        / "utils"
        / "human_model_files"
        / "smplx"
        / "model.npz"
    )
    asset.parent.mkdir(parents=True)
    asset.write_bytes(asset_payload)
    receipt = {
        "format": "bodyrig-photoreal-exavatar-workspace",
        "upstream_commit": candidate.PINNED_UPSTREAM_COMMIT,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "dataset": "Custom",
        "smplx_gender_explicit": True,
        "upstream_default_gender_accepted": False,
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "dependency_root_modified": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "repository_commits": {
            "exavatar": candidate.PINNED_UPSTREAM_COMMIT,
        },
        "avatar_config_patch": {
            "after_sha256": hashlib.sha256(b"config").hexdigest(),
        },
        "linked_assets": [
            {
                "destination": (
                    "repos/ExAvatar_RELEASE/avatar/common/utils/"
                    "human_model_files/smplx/model.npz"
                ),
                "sha256": hashlib.sha256(asset_payload).hexdigest(),
            }
        ],
    }
    import json

    (root / "workspace-receipt.json").write_text(
        json.dumps(receipt),
        encoding="utf-8",
    )
    return root


def test_workspace_verifies_linked_human_model_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)

    def fake_git(repo: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return candidate.PINNED_UPSTREAM_COMMIT
        if args[:2] == ("status", "--porcelain"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(candidate, "_git", fake_git)

    repo = candidate._verify_workspace(root, _workspace_request())

    assert repo == root / "repos" / "ExAvatar_RELEASE"


def test_workspace_rejects_linked_model_asset_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    asset = (
        root
        / "repos"
        / "ExAvatar_RELEASE"
        / "avatar"
        / "common"
        / "utils"
        / "human_model_files"
        / "smplx"
        / "model.npz"
    )
    asset.write_bytes(b"drift")

    monkeypatch.setattr(
        candidate,
        "_git",
        lambda repo, *args: (
            candidate.PINNED_UPSTREAM_COMMIT
            if args == ("rev-parse", "HEAD")
            else ""
        ),
    )

    with pytest.raises(
        Quest2StudentCandidateError,
        match="linked model asset bytes drifted",
    ):
        candidate._verify_workspace(root, _workspace_request())


def _write(root: Path, relative: str, payload: bytes) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "relative_path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _teacher_request(root: Path) -> dict[str, object]:
    records = []
    checkpoint = _write(
        root,
        "teacher-output/checkpoint/snapshot_4.pth",
        b"checkpoint",
    )
    records.append(
        {
            "kind": "teacher-checkpoint",
            "root_kind": "teacher-output",
            **checkpoint,
        }
    )
    for kind, filename, payload in (
        ("shape-param", "shape_param.json", b"shape"),
        ("face-offset", "face_offset.json", b"face"),
        ("joint-offset", "joint_offset.json", b"joint"),
        ("locator-offset", "locator_offset.json", b"locator"),
    ):
        record = _write(
            root,
            f"identity-export/identity/{filename}",
            payload,
        )
        records.append(
            {
                "kind": kind,
                "root_kind": "identity-export",
                **record,
            }
        )
    return {"staged_teacher_sources": records}


def test_verify_staged_teacher_requires_exact_five_source_files(
    tmp_path: Path,
) -> None:
    request = _teacher_request(tmp_path)

    result = candidate._verify_staged_teacher(request, tmp_path)

    assert set(result) == candidate.EXPECTED_SOURCE_KINDS


def test_verify_staged_teacher_rejects_extra_file(tmp_path: Path) -> None:
    request = _teacher_request(tmp_path)
    (tmp_path / "unexpected.bin").write_bytes(b"x")

    with pytest.raises(
        Quest2StudentCandidateError,
        match="filesystem universe differs",
    ):
        candidate._verify_staged_teacher(request, tmp_path)


def test_verify_staged_teacher_rejects_identity_root_substitution(
    tmp_path: Path,
) -> None:
    request = _teacher_request(tmp_path)
    request["staged_teacher_sources"][1]["root_kind"] = "teacher-output"

    with pytest.raises(
        Quest2StudentCandidateError,
        match="root-kind mismatch",
    ):
        candidate._verify_staged_teacher(request, tmp_path)


def test_zero_pose_teacher_uses_refined_exavatar_asset() -> None:
    import inspect

    source = inspect.getsource(candidate._load_zero_pose_teacher)

    assert "_base_teacher, refined_teacher" in source
    assert '"teacher_xyz": refined_teacher["mean_3d"]' in source
    assert '"teacher_rgb": refined_teacher["rgb"]' in source
    assert '"teacher_xyz": _base_teacher["mean_3d"]' not in source
    assert '"teacher_rgb": _base_teacher["rgb"]' not in source
