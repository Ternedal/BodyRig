from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.appearance_boundary import provenance_stage as appearance_boundary_stage
from bodyrig.avatar import ProceduralAvatarFitter
from bodyrig.physical_session import mark_fail, mark_pass, mark_readiness_pass, start_session
from bodyrig.portable_identity import build_portable_identity, provenance_identity_stage
from bodyrig.post_clone_continuation import PostCloneContinuationError, build_post_clone_plan
from bodyrig.package import build_package


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
        "source_count": 1,
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
        "source_count": 1,
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


def _fixture(tmp_path: Path, *, pass_session: bool = True) -> tuple[Path, Path, Path]:
    alias = "fixture-person"
    outer = tmp_path / "clone-output"
    clone = outer / "clone"
    clone.mkdir(parents=True)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture-source")
    proof = _proof()
    identity = _identity()
    portable = build_portable_identity(
        proof=proof,
        visual_identity=identity,
        source_files=[source],
        requested_alias=alias,
    )
    (clone / "bodyrig-recovery-preflight.json").write_text('{"ok":true}\n', encoding="utf-8")
    (clone / "bodyrig-recovery-proof.json").write_text(json.dumps(proof), encoding="utf-8")
    (clone / "bodyrig-visual-identity.json").write_text(json.dumps(identity), encoding="utf-8")
    (clone / "bodyrig-portable-identity.json").write_text(json.dumps(portable), encoding="utf-8")
    (outer / "bodyrig-stash-source-manifest.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "source_kind": "stash-local",
                "performer": {"id": "42", "name": "Fixture Person"},
                "selected": [{"scene_id": "1", "path": str(source)}],
            }
        ),
        encoding="utf-8",
    )

    fitted = ProceduralAvatarFitter().fit(BODYPRINT, name="Fixture Person")
    build_package(
        clone / f"{alias}.mrbody",
        body_id=portable["body_id"],
        name="Fixture Person",
        avatar_vrm=fitted.avatar_vrm,
        bodyprint=BODYPRINT,
        provenance={
            "format": "modelrig-body-provenance",
            "version": 1,
            "created_at": "2026-09-03T12:00:00Z",
            "source": {"kind": "user-supplied-local-media", "count": 1},
            "synthetic_avatar": True,
            "pipeline": [
                {"stage": "body-recovery", "adapter": "fixture-recovery", "revision": "recovery-v1"},
                {"stage": "visual-identity-capture", "adapter": "fixture-capture", "revision": "capture-v1"},
                provenance_identity_stage(portable),
                appearance_boundary_stage(),
                {"stage": "avatar-fitting", "adapter": "sith-smplx-vrm", "revision": "1"},
            ],
        },
        thumbnail_png=fitted.thumbnail_png,
    )

    session = tmp_path / "physical-session.json"
    start_session(
        session,
        performer_id="42",
        body_id=alias,
        bodyrig_revision=REVISION,
        bodyrig_checkout_clean=True,
        rig_setup_sha256="a" * 64,
    )
    readiness = session.with_suffix(".readiness.json")
    readiness.write_text('{"format":"fixture-readiness","ok":true}\n', encoding="utf-8")
    readiness_sha = hashlib.sha256(readiness.read_bytes()).hexdigest()
    mark_readiness_pass(session, readiness_sha256=readiness_sha)
    if pass_session:
        mark_pass(session, clone_output=str(outer.resolve()))
    else:
        mark_fail(session, stage="clone", message="fixture clone failure")
    return session, outer, clone / f"{alias}.mrbody"


def test_post_clone_plan_reuses_completed_clone_without_recovery_or_fitter(tmp_path: Path) -> None:
    session, outer, _package = _fixture(tmp_path)
    plan = build_post_clone_plan(
        session_report=session,
        clone_output=outer,
        current_revision=REVISION,
    )
    assert plan["format"] == "bodyrig-post-clone-continuation-plan"
    assert plan["performer_id"] == "42"
    assert plan["body_alias"] == "fixture-person"
    assert plan["canonical_body_id"].startswith("bodyid-")
    assert len(plan["package_sha256"]) == 64
    assert plan["source_count"] == 1
    assert plan["recovery_rerun"] is False
    assert plan["fitter_rerun"] is False
    assert plan["gate_a_rerun"] is True
    assert plan["fidelity_rerun"] is True


def test_post_clone_plan_refuses_non_pass_session(tmp_path: Path) -> None:
    session, outer, _package = _fixture(tmp_path, pass_session=False)
    with pytest.raises(PostCloneContinuationError, match="completed PASS"):
        build_post_clone_plan(session_report=session, clone_output=outer, current_revision=REVISION)


def test_post_clone_plan_refuses_other_revision(tmp_path: Path) -> None:
    session, outer, _package = _fixture(tmp_path)
    with pytest.raises(PostCloneContinuationError, match="different BodyRig revision"):
        build_post_clone_plan(session_report=session, clone_output=outer, current_revision="2" * 40)


def test_post_clone_plan_refuses_job_clone_output_mismatch(tmp_path: Path) -> None:
    session, _outer, _package = _fixture(tmp_path)
    other = tmp_path / "other-clone-output"
    other.mkdir()
    with pytest.raises(PostCloneContinuationError, match="clone output differs"):
        build_post_clone_plan(session_report=session, clone_output=other, current_revision=REVISION)


def test_post_clone_plan_refuses_tampered_readiness(tmp_path: Path) -> None:
    session, outer, _package = _fixture(tmp_path)
    readiness = session.with_suffix(".readiness.json")
    readiness.write_bytes(readiness.read_bytes() + b" ")
    with pytest.raises(PostCloneContinuationError, match="readiness bytes no longer match"):
        build_post_clone_plan(session_report=session, clone_output=outer, current_revision=REVISION)


def test_post_clone_plan_normalizes_corrupt_package_failure(tmp_path: Path) -> None:
    session, outer, package = _fixture(tmp_path)
    package.write_bytes(b"not-an-mrbody")
    with pytest.raises(PostCloneContinuationError, match="package is invalid"):
        build_post_clone_plan(session_report=session, clone_output=outer, current_revision=REVISION)
