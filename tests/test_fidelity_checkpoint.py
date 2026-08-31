from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.fidelity_checkpoint import (
    FidelityCheckpointError,
    load_latest_checkpoint,
    validate_checkpoint,
    verify_checkpoint_artifacts,
)


REVISION = "1" * 40
RIG_SHA = "2" * 64
POLICY = {
    "max_full_rebuilds": 2,
    "max_refinements_per_rebuild": 3,
    "max_wall_clock_hours": 8.0,
    "base_sith_seed": 1337,
    "reference_limit": 24,
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path: Path, *, stage: str = "post-candidate", sequence: int = 1) -> tuple[Path, Path, dict]:
    work = tmp_path / "work"
    checkpoints = work / "checkpoints"
    checkpoints.mkdir(parents=True)
    references = work / "references"
    references.mkdir()
    reference_manifest = references / "reference-set.json"
    reference_manifest.write_text('{"reference":"fixture"}\n', encoding="utf-8")
    frozen = references / "private-body-reference-rgba.png"
    frozen.write_bytes(b"png-fixture")

    rebuild = work / "rebuild-01"
    full = rebuild / "full"
    render = full / "comparison-render"
    render.mkdir(parents=True)
    package = rebuild / "clone-run" / "clone" / "fixture.mrbody"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"mrbody-fixture")
    evaluation = full / "fidelity-evaluation.json"
    evaluation.write_text('{"evaluation":"fixture"}\n', encoding="utf-8")
    decision = full / "convergence-decision.json"
    decision.write_text('{"decision":"iterate"}\n', encoding="utf-8")
    plan = full / "next-adjustment-plan.json"
    plan.write_text('{"applicable":false}\n', encoding="utf-8")

    private = tmp_path / "private-identity"
    reconstruction = private / "sith-input-v1" / "reconstruction.json"
    reconstruction.parent.mkdir(parents=True)
    reconstruction.write_text('{"authority":"fixture"}\n', encoding="utf-8")

    artifacts = [
        {"path": "references/reference-set.json", "sha256": digest(reference_manifest), "scope": "work-root"},
        {"path": "references/private-body-reference-rgba.png", "sha256": digest(frozen), "scope": "work-root"},
        {"path": "rebuild-01/clone-run/clone/fixture.mrbody", "sha256": digest(package), "scope": "work-root"},
        {"path": str(reconstruction), "sha256": digest(reconstruction), "scope": "private"},
    ]
    latest = None
    evaluations: list[str] = []
    records: list[dict] = []
    latest_scores = None
    best_scores = None
    best_candidate = None
    strategy = None
    next_focus = None
    if stage == "post-candidate":
        artifacts.extend(
            [
                {"path": "rebuild-01/full/fidelity-evaluation.json", "sha256": digest(evaluation), "scope": "work-root"},
                {"path": "rebuild-01/full/convergence-decision.json", "sha256": digest(decision), "scope": "work-root"},
                {"path": "rebuild-01/full/next-adjustment-plan.json", "sha256": digest(plan), "scope": "work-root"},
            ]
        )
        latest = {
            "decision_path": "rebuild-01/full/convergence-decision.json",
            "evaluation_path": "rebuild-01/full/fidelity-evaluation.json",
            "adjustment_plan_path": "rebuild-01/full/next-adjustment-plan.json",
            "adjustment_request_path": "",
            "adjustment_sha256": "",
        }
        evaluations = ["rebuild-01/full/fidelity-evaluation.json"]
        records = [
            {
                "relative_name": "rebuild-01/full",
                "mode": "full-reconstruction",
                "package_path": "rebuild-01/clone-run/clone/fixture.mrbody",
                "render_dir": "rebuild-01/full/comparison-render",
                "evaluation_path": "rebuild-01/full/fidelity-evaluation.json",
                "acceptance_dir": "rebuild-01/full/acceptance",
            }
        ]
        latest_scores = {"overall": 0.72}
        best_scores = {"overall": 0.72}
        best_candidate = "rebuild-01/full"
        strategy = "geometry-search"
        next_focus = "body_silhouette"

    checkpoint = {
        "format": "bodyrig-fidelity-convergence-checkpoint",
        "version": 1,
        "sequence": sequence,
        "stage": stage,
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "body_alias": "fixture",
        "policy": POLICY,
        "rig_setup_sha256": RIG_SHA,
        "active_elapsed_seconds": 18_123.5,
        "state": {
            "full_rebuilds_completed": 1,
            "refinements_completed": 0,
            "current_rebuild_refinements": 0,
            "current_seed": 1337,
            "full_durations": [18_000.0],
            "refinement_durations": [],
            "phase_timings": {
                "full-rebuild": [18_000.0],
                "resume-refinement": [],
                "gate-a": [40.0] if stage == "post-candidate" else [],
                "render": [70.0] if stage == "post-candidate" else [],
                "evaluate": [13.5] if stage == "post-candidate" else [],
            },
            "latest_scores": latest_scores,
            "best_scores": best_scores,
            "best_candidate": best_candidate,
            "strategy": strategy,
            "next_focus": next_focus,
            "evaluation_paths": evaluations,
            "candidate_records": records,
            "used_adjustment_hashes": [],
            "frozen_body_reference_sha256": digest(frozen),
            "current_baseline_clone_output": "rebuild-01/clone-run",
            "current_identity_workspace": str(private),
            "effective_name": "Fixture Person",
            "first_renderer_build": False if stage == "post-candidate" else True,
            "latest_candidate": latest,
        },
        "artifacts": artifacts,
        "human_visual_authority_required": True,
        "production_activation": False,
    }
    path = checkpoints / f"checkpoint-{sequence:06d}.json"
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    return work, path, checkpoint


def test_post_candidate_checkpoint_validates_and_verifies_exact_artifacts(tmp_path: Path) -> None:
    work, _, raw = fixture(tmp_path)
    checkpoint = validate_checkpoint(raw)
    verify_checkpoint_artifacts(checkpoint, work_root=work)
    assert checkpoint["stage"] == "post-candidate"
    assert checkpoint["active_elapsed_seconds"] == 18_123.5
    assert checkpoint["production_activation"] is False


def test_post_reconstruction_checkpoint_has_no_fake_candidate(tmp_path: Path) -> None:
    work, _, raw = fixture(tmp_path, stage="post-reconstruction")
    checkpoint = validate_checkpoint(raw)
    verify_checkpoint_artifacts(checkpoint, work_root=work)
    assert checkpoint["state"]["latest_candidate"] is None
    assert checkpoint["state"]["candidate_records"] == []


def test_checkpoint_refuses_one_byte_artifact_mutation(tmp_path: Path) -> None:
    work, _, raw = fixture(tmp_path)
    checkpoint = validate_checkpoint(raw)
    reconstruction = Path(checkpoint["state"]["current_identity_workspace"]) / "sith-input-v1" / "reconstruction.json"
    reconstruction.write_bytes(reconstruction.read_bytes() + b" ")
    with pytest.raises(FidelityCheckpointError, match="artifact hash mismatch"):
        verify_checkpoint_artifacts(checkpoint, work_root=work)


def test_latest_checkpoint_requires_exact_revision_policy_and_rig_setup(tmp_path: Path) -> None:
    work, path, _ = fixture(tmp_path)
    loaded_path, checkpoint = load_latest_checkpoint(
        path.parent,
        work_root=work,
        expected_revision=REVISION,
        expected_performer_id="42",
        expected_body_alias="fixture",
        expected_policy=POLICY,
        expected_rig_setup_sha256=RIG_SHA,
    )
    assert loaded_path == path
    assert checkpoint["sequence"] == 1

    with pytest.raises(FidelityCheckpointError, match="different BodyRig revision"):
        load_latest_checkpoint(
            path.parent,
            work_root=work,
            expected_revision="3" * 40,
            expected_performer_id="42",
            expected_body_alias="fixture",
            expected_policy=POLICY,
            expected_rig_setup_sha256=RIG_SHA,
        )
    changed = dict(POLICY)
    changed["max_wall_clock_hours"] = 12.0
    with pytest.raises(FidelityCheckpointError, match="cost policy differs"):
        load_latest_checkpoint(
            path.parent,
            work_root=work,
            expected_revision=REVISION,
            expected_performer_id="42",
            expected_body_alias="fixture",
            expected_policy=changed,
            expected_rig_setup_sha256=RIG_SHA,
        )


def test_latest_checkpoint_rejects_sequence_filename_mismatch(tmp_path: Path) -> None:
    work, path, raw = fixture(tmp_path)
    path.unlink()
    bad = path.parent / "checkpoint-000009.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(FidelityCheckpointError, match="filename does not match"):
        load_latest_checkpoint(
            bad.parent,
            work_root=work,
            expected_revision=REVISION,
            expected_performer_id="42",
            expected_body_alias="fixture",
            expected_policy=POLICY,
            expected_rig_setup_sha256=RIG_SHA,
        )
