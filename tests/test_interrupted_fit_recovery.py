from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.interrupted_fit_recovery import (
    InterruptedFitRecoveryError,
    build_recovery_plan,
)
from bodyrig.physical_session import mark_fail, mark_readiness_pass, start_session
from bodyrig.portable_identity import build_portable_identity


REVISION = "1" * 40
BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "shape": {
        "shoulder_to_height": 0.24,
        "hip_to_height": 0.19,
        "arm_to_height": 0.44,
        "leg_to_height": 0.53,
    },
    "motion": {"energy": 0.42, "head_motion": 0.21},
}


def _proof() -> dict:
    return {
        "format": "bodyrig-recovery-proof",
        "version": 1,
        "source_count": 2,
        "adapter": "fixture-recovery",
        "revision": "recovery-v1",
        "track_id": "7",
        "observed_frames": 120,
        "bodyprint": BODYPRINT,
    }


def _identity() -> dict:
    return {
        "format": "bodyrig-visual-identity",
        "version": 1,
        "adapter": "fixture-capture",
        "revision": "capture-v1",
        "source_count": 2,
        "subject_track_id": "7",
        "capture": {
            "observed_frames": 120,
            "face_frames": 80,
            "full_body_frames": 100,
            "side_body_frames": 25,
            "rear_body_frames": 20,
        },
        "coverage": {
            "face": 0.9,
            "hair_or_scalp": 0.8,
            "skin": 0.75,
            "clothing": 0.85,
            "full_body": 0.95,
            "back": 0.6,
        },
        "quality": {"sharpness": 0.8, "lighting": 0.7, "visibility": 0.9},
        "privacy": {"contains_source_media": False, "contains_biometric_template": False},
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    outer = tmp_path / "clone-run"
    clone = outer / "clone"
    clone.mkdir(parents=True)
    workspace = tmp_path / "identity-workspace"
    reconstruction = workspace / "sith-input-v1" / "reconstruction.json"
    reconstruction.parent.mkdir(parents=True)
    reconstruction.write_text('{"authority":"fixture"}\n', encoding="utf-8")

    proof = _proof()
    identity = _identity()
    source_a = tmp_path / "a.mp4"
    source_b = tmp_path / "b.mp4"
    source_a.write_bytes(b"a-source")
    source_b.write_bytes(b"b-source")
    portable = build_portable_identity(
        proof=proof,
        visual_identity=identity,
        source_files=[source_a, source_b],
        requested_alias="fixture-person",
    )

    (clone / "bodyrig-recovery-proof.json").write_text(json.dumps(proof), encoding="utf-8")
    (clone / "bodyrig-visual-identity.json").write_text(json.dumps(identity), encoding="utf-8")
    (clone / "bodyrig-portable-identity.json").write_text(json.dumps(portable), encoding="utf-8")
    (outer / "bodyrig-sith-fitter-config.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-external-fitter-config",
                "version": 1,
                "adapter": "sith-smplx-vrm",
                "revision": "1",
                "command": ["python", "-m", "bodyrig.sith_fitter_orchestrator"],
                "capabilities": {
                    "visual_identity": True,
                    "textures": True,
                    "hair": False,
                    "clothing": False,
                },
                "timeout_seconds": 86400,
            }
        ),
        encoding="utf-8",
    )
    (outer / "bodyrig-stash-source-manifest.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "source_kind": "stash-local",
                "performer": {"id": "42", "name": "Fixture Person"},
                "selected": [],
            }
        ),
        encoding="utf-8",
    )

    failed = tmp_path / "failed-session.json"
    start_session(
        failed,
        performer_id="42",
        body_id="fixture-person",
        bodyrig_revision=REVISION,
        bodyrig_checkout_clean=True,
        rig_setup_sha256="a" * 64,
    )
    mark_readiness_pass(failed, readiness_sha256="b" * 64)
    mark_fail(failed, stage="clone", message="interrupted during expensive SiTH fit")
    return failed, outer, workspace


def test_interrupted_clone_plan_binds_completed_reconstruction_without_rerun(tmp_path: Path) -> None:
    failed, outer, workspace = _fixture(tmp_path)
    plan = build_recovery_plan(
        failed_session_path=failed,
        stash_clone_output=outer,
        identity_workspace=workspace,
        current_revision=REVISION,
    )
    assert plan["format"] == "bodyrig-interrupted-fit-recovery-plan"
    assert plan["performer_id"] == "42"
    assert plan["body_alias"] == "fixture-person"
    assert plan["display_name"] == "Fixture Person"
    assert plan["expensive_reconstruction_rerun"] is False
    assert plan["package_already_complete"] is False
    assert len(plan["authority"]["reconstruction_sha256"]) == 64


def test_recovery_refuses_session_from_another_revision(tmp_path: Path) -> None:
    failed, outer, workspace = _fixture(tmp_path)
    with pytest.raises(InterruptedFitRecoveryError, match="different BodyRig revision"):
        build_recovery_plan(
            failed_session_path=failed,
            stash_clone_output=outer,
            identity_workspace=workspace,
            current_revision="2" * 40,
        )


def test_recovery_refuses_missing_reconstruction_authority(tmp_path: Path) -> None:
    failed, outer, workspace = _fixture(tmp_path)
    (workspace / "sith-input-v1" / "reconstruction.json").unlink()
    with pytest.raises(InterruptedFitRecoveryError, match="no completed SiTH reconstruction authority"):
        build_recovery_plan(
            failed_session_path=failed,
            stash_clone_output=outer,
            identity_workspace=workspace,
            current_revision=REVISION,
        )


def test_recovery_refuses_non_sith_fitter(tmp_path: Path) -> None:
    failed, outer, workspace = _fixture(tmp_path)
    config_path = outer / "bodyrig-sith-fitter-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["adapter"] = "fixture-fitter"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(InterruptedFitRecoveryError, match="production SiTH"):
        build_recovery_plan(
            failed_session_path=failed,
            stash_clone_output=outer,
            identity_workspace=workspace,
            current_revision=REVISION,
        )
