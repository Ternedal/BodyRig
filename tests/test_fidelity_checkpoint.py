from __future__ import annotations

import copy
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
SNAPSHOTS = (
    "front-full.png",
    "three-quarter-full.png",
    "side-full.png",
    "face-front.png",
    "fidelity-render-set.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def artifact(work: Path, path: Path, *, scope: str = "work-root") -> dict[str, str]:
    if scope == "work-root":
        name = path.relative_to(work).as_posix()
    else:
        name = str(path.resolve())
    return {"path": name, "sha256": digest(path), "scope": scope}


def fixture(tmp_path: Path, *, stage: str = "post-candidate", sequence: int = 1) -> tuple[Path, Path, dict]:
    work = tmp_path / "work"
    checkpoints = work / "checkpoints"
    checkpoints.mkdir(parents=True)

    reference_manifest = write(work / "references" / "reference-set.json", b'{"reference":"fixture"}\n')
    frozen = write(work / "references" / "private-body-reference-rgba.png", b"png-fixture")

    rebuild = work / "rebuild-01"
    clone_run = rebuild / "clone-run"
    clone = clone_run / "clone"
    package = write(clone / "fixture.mrbody", b"mrbody-fixture")
    recovery_proof = write(clone / "bodyrig-recovery-proof.json", b'{"proof":"fixture"}\n')
    visual_identity = write(clone / "bodyrig-visual-identity.json", b'{"visual":"fixture"}\n')
    portable_identity = write(clone / "bodyrig-portable-identity.json", b'{"portable":"fixture"}\n')
    fitter_config = write(clone_run / "bodyrig-sith-fitter-config.json", b'{"fitter":"fixture"}\n')
    session = write(rebuild / "physical-session.json", b'{"session":"pass"}\n')

    private = tmp_path / "private-identity"
    reconstruction = write(private / "sith-input-v1" / "reconstruction.json", b'{"authority":"fixture"}\n')
    reconstruction_authority = write(
        private / "sith-input-v1" / "reconstruction-authority.json",
        b'{"format":"bodyrig-sith-reconstruction-authority","version":1}\n',
    )

    base_artifacts = [
        artifact(work, reference_manifest),
        artifact(work, frozen),
        artifact(work, package),
        artifact(work, recovery_proof),
        artifact(work, visual_identity),
        artifact(work, portable_identity),
        artifact(work, fitter_config),
        artifact(work, session),
        artifact(work, reconstruction, scope="private"),
        artifact(work, reconstruction_authority, scope="private"),
    ]

    latest = None
    evaluations: list[str] = []
    records: list[dict] = []
    latest_scores = None
    best_scores = None
    best_candidate = None
    strategy = None
    next_focus = None
    artifacts = list(base_artifacts)

    if stage == "post-candidate":
        full = rebuild / "full"
        render = full / "comparison-render"
        snapshots = render / "snapshots"
        evaluation = write(full / "fidelity-evaluation.json", b'{"evaluation":"fixture"}\n')
        decision = write(full / "convergence-decision.json", b'{"decision":"iterate"}\n')
        plan = write(full / "next-adjustment-plan.json", b'{"applicable":false}\n')
        for name in SNAPSHOTS:
            payload = b'{"render":"fixture"}\n' if name.endswith(".json") else f"png:{name}".encode()
            artifacts.append(artifact(work, write(snapshots / name, payload)))
        artifacts.extend([artifact(work, evaluation), artifact(work, decision), artifact(work, plan)])
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
            "current_identity_workspace": str(private.resolve()),
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


def test_checkpoint_refuses_one_byte_private_reconstruction_mutation(tmp_path: Path) -> None:
    work, _, raw = fixture(tmp_path)
    checkpoint = validate_checkpoint(raw)
    reconstruction = Path(checkpoint["state"]["current_identity_workspace"]) / "sith-input-v1" / "reconstruction.json"
    reconstruction.write_bytes(reconstruction.read_bytes() + b" ")
    with pytest.raises(FidelityCheckpointError, match="artifact hash mismatch"):
        verify_checkpoint_artifacts(checkpoint, work_root=work)


def test_checkpoint_refuses_one_byte_private_reconstruction_authority_mutation(tmp_path: Path) -> None:
    work, _, raw = fixture(tmp_path)
    checkpoint = validate_checkpoint(raw)
    authority = (
        Path(checkpoint["state"]["current_identity_workspace"])
        / "sith-input-v1"
        / "reconstruction-authority.json"
    )
    authority.write_bytes(authority.read_bytes() + b" ")
    with pytest.raises(FidelityCheckpointError, match="artifact hash mismatch"):
        verify_checkpoint_artifacts(checkpoint, work_root=work)


def test_checkpoint_refuses_unhashed_private_reconstruction_authority(tmp_path: Path) -> None:
    _, _, raw = fixture(tmp_path)
    tampered = copy.deepcopy(raw)
    tampered["artifacts"] = [
        item for item in tampered["artifacts"] if not item["path"].endswith("reconstruction-authority.json")
    ]
    with pytest.raises(FidelityCheckpointError, match="unhashed artifacts"):
        validate_checkpoint(tampered)


def test_checkpoint_refuses_state_path_not_covered_by_hashes(tmp_path: Path) -> None:
    _, _, raw = fixture(tmp_path)
    tampered = copy.deepcopy(raw)
    tampered["state"]["latest_candidate"]["decision_path"] = "rebuild-01/full/other-decision.json"
    with pytest.raises(FidelityCheckpointError, match="unhashed artifacts"):
        validate_checkpoint(tampered)


def test_checkpoint_refuses_candidate_history_reordering(tmp_path: Path) -> None:
    _, _, raw = fixture(tmp_path)
    tampered = copy.deepcopy(raw)
    tampered["state"]["evaluation_paths"] = ["rebuild-01/full/other-evaluation.json"]
    with pytest.raises(FidelityCheckpointError, match="exactly match candidate record order"):
        validate_checkpoint(tampered)


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
    with pytest.raises(FidelityCheckpointError, match="policy differs"):
        load_latest_checkpoint(
            path.parent,
            work_root=work,
            expected_revision=REVISION,
            expected_performer_id="42",
            expected_body_alias="fixture",
            expected_policy=changed,
            expected_rig_setup_sha256=RIG_SHA,
        )
    with pytest.raises(FidelityCheckpointError, match="rig setup bytes differ"):
        load_latest_checkpoint(
            path.parent,
            work_root=work,
            expected_revision=REVISION,
            expected_performer_id="42",
            expected_body_alias="fixture",
            expected_policy=POLICY,
            expected_rig_setup_sha256="9" * 64,
        )


def test_latest_checkpoint_rejects_sequence_gap_and_filename_mismatch(tmp_path: Path) -> None:
    work, path, raw = fixture(tmp_path)
    path.unlink()
    gap = path.parent / "checkpoint-000009.json"
    gap.write_text(json.dumps(raw | {"sequence": 9}), encoding="utf-8")
    with pytest.raises(FidelityCheckpointError, match="sequence contains a gap"):
        load_latest_checkpoint(
            gap.parent,
            work_root=work,
            expected_revision=REVISION,
            expected_performer_id="42",
            expected_body_alias="fixture",
            expected_policy=POLICY,
            expected_rig_setup_sha256=RIG_SHA,
        )

    gap.unlink()
    mismatch = path.parent / "checkpoint-000001.json"
    mismatch.write_text(json.dumps(raw | {"sequence": 2}), encoding="utf-8")
    with pytest.raises(FidelityCheckpointError, match="filename sequence does not match content"):
        load_latest_checkpoint(
            mismatch.parent,
            work_root=work,
            expected_revision=REVISION,
            expected_performer_id="42",
            expected_body_alias="fixture",
            expected_policy=POLICY,
            expected_rig_setup_sha256=RIG_SHA,
        )
