from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.fidelity_physical_handoff as handoff

REVISION = "c9dc066ef40f95a6004499a895b22a9cb3ff26c7"
POLICY = {
    "max_full_rebuilds": 1,
    "max_refinements_per_rebuild": 0,
    "max_wall_clock_hours": 8.0,
    "base_sith_seed": 1337,
    "reference_limit": 24,
}


def _json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, dict]:
    root = tmp_path / "work"
    root.mkdir()
    rig = tmp_path / "rig.json"
    rig.write_text("{}", encoding="utf-8")
    checkpoint_path = _json(root / "checkpoints" / "checkpoint-000002.json", {"fixture": True})

    candidate = root / "rebuild-01" / "full" / "candidate.mrbody"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate-package")
    evaluation = _json(root / "rebuild-01" / "full" / "evaluation.json", {"ok": True})
    render = root / "rebuild-01" / "full" / "comparison-render"
    snapshots = render / "snapshots"
    snapshots.mkdir(parents=True)
    for name in handoff.SNAPSHOT_NAMES:
        (snapshots / name).write_bytes(("snapshot:" + name).encode("utf-8"))

    acceptance_dir = root / "rebuild-01" / "full" / "acceptance"
    acceptance_dir.mkdir(parents=True)
    accepted_package = acceptance_dir / "bodyid-0123456789abcdef01234567.mrbody"
    accepted_package.write_bytes(candidate.read_bytes())
    package_sha = handoff.sha256_file(candidate)

    skin = {
        "format": "bodyrig-skin-qa",
        "version": 1,
        "body_id": "bodyid-0123456789abcdef01234567",
        "package_sha256": package_sha,
        "structural_pass": True,
        "automated_assessment": "review",
        "manual_review_required": True,
    }
    topology = {
        "format": "bodyrig-mesh-topology-qa",
        "version": 1,
        "body_id": "bodyid-0123456789abcdef01234567",
        "package_sha256": package_sha,
        "structural_pass": True,
        "automated_assessment": "pass",
        "manual_review_required": True,
    }
    skin_path = _json(acceptance_dir / "bodyrig-skin-qa.json", skin)
    topology_path = _json(acceptance_dir / "bodyrig-mesh-topology-qa.json", topology)
    acceptance = {
        "format": "bodyrig-rig-acceptance",
        "version": 1,
        "bodyrig_revision": REVISION,
        "bodyrig_checkout_clean": True,
        "checks": {"fixture": True},
        "skin_qa": {
            "report_sha256": handoff.sha256_file(skin_path),
            "structural_pass": True,
            "automated_assessment": "review",
            "manual_review_required": True,
        },
        "mesh_topology_qa": {
            "report_sha256": handoff.sha256_file(topology_path),
            "structural_pass": True,
            "automated_assessment": "pass",
            "manual_review_required": True,
        },
        "automated_pass": True,
        "physical_renderer_acceptance": "pending",
        "production_activation": False,
    }
    _json(acceptance_dir / "bodyrig-acceptance.json", acceptance)

    workspace = tmp_path / "private-workspace"
    reconstruction = _json(workspace / "sith-input-v1" / "reconstruction.json", {"mesh": "fixture"})
    _json(
        workspace / "sith-input-v1" / "reconstruction-authority.json",
        {
            "format": "bodyrig-sith-reconstruction-authority",
            "version": 1,
            "reconstruction_sha256": handoff.sha256_file(reconstruction),
            "smplx_fit_profile": "gender-aware-final-params-canonical-obj-v1",
            "body_model_gender": "female",
        },
    )

    checkpoint = {
        "sequence": 2,
        "stage": "post-candidate",
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "body_alias": "lauren-phillips-pr40-physical01",
        "policy": dict(POLICY),
        "state": {
            "full_rebuilds_completed": 1,
            "refinements_completed": 0,
            "current_rebuild_refinements": 0,
            "candidate_records": [
                {
                    "relative_name": "rebuild-01/full",
                    "mode": "full-reconstruction",
                    "package_path": candidate.relative_to(root).as_posix(),
                    "render_dir": render.relative_to(root).as_posix(),
                    "evaluation_path": evaluation.relative_to(root).as_posix(),
                    "acceptance_dir": acceptance_dir.relative_to(root).as_posix(),
                }
            ],
            "current_identity_workspace": str(workspace),
        },
    }

    def fake_latest(*args, **kwargs):
        assert kwargs["expected_revision"] == REVISION
        assert kwargs["expected_performer_id"] == "42"
        assert kwargs["expected_body_alias"] == "lauren-phillips-pr40-physical01"
        assert kwargs["expected_policy"] == POLICY
        assert kwargs["expected_rig_setup_sha256"] == handoff.sha256_file(rig)
        return checkpoint_path, checkpoint

    monkeypatch.setattr(handoff, "load_latest_checkpoint", fake_latest)
    monkeypatch.setattr(
        handoff,
        "validate_package",
        lambda path: SimpleNamespace(manifest={"id": "bodyid-0123456789abcdef01234567"}),
    )
    return root, rig, checkpoint


def test_seal_requires_explicit_human_geometry_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, rig, _ = _fixture(tmp_path, monkeypatch)
    with pytest.raises(handoff.FidelityPhysicalHandoffError, match="explicit human geometry approval"):
        handoff.seal_physical_handoff(
            work_root=root,
            rig_setup=rig,
            expected_revision=REVISION,
            expected_performer_id="42",
            expected_body_alias="lauren-phillips-pr40-physical01",
            expected_policy=POLICY,
            human_geometry_approved=False,
        )


def test_seal_binds_gate_a_reconstruction_and_human_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, rig, _ = _fixture(tmp_path, monkeypatch)
    receipt = handoff.seal_physical_handoff(
        work_root=root,
        rig_setup=rig,
        expected_revision=REVISION,
        expected_performer_id="42",
        expected_body_alias="lauren-phillips-pr40-physical01",
        expected_policy=POLICY,
        human_geometry_approved=True,
    )
    assert receipt["checkpoint"]["stage"] == "post-candidate"
    assert receipt["gate_a"] == {
        "acceptance_dir": "rebuild-01/full/acceptance",
        "automated_pass": True,
        "skin_assessment": "review",
        "topology_assessment": "pass",
    }
    assert receipt["reconstruction"]["body_model_gender"] == "female"
    assert receipt["human_review"]["geometry_approved"] is True
    assert receipt["human_visual_authority_required"] is True
    assert receipt["production_activation"] is False
    artifact_paths = {item["path"] for item in receipt["artifacts"]}
    assert "rebuild-01/full/acceptance/bodyrig-acceptance.json" in artifact_paths
    assert "rebuild-01/full/acceptance/bodyrig-skin-qa.json" in artifact_paths
    assert "rebuild-01/full/acceptance/bodyrig-mesh-topology-qa.json" in artifact_paths


def test_seal_rejects_high_risk_skin_even_with_human_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, rig, _ = _fixture(tmp_path, monkeypatch)
    skin_path = root / "rebuild-01" / "full" / "acceptance" / "bodyrig-skin-qa.json"
    skin = json.loads(skin_path.read_text(encoding="utf-8"))
    skin["automated_assessment"] = "high-risk"
    _json(skin_path, skin)
    acceptance_path = skin_path.parent / "bodyrig-acceptance.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["skin_qa"]["report_sha256"] = handoff.sha256_file(skin_path)
    acceptance["skin_qa"]["automated_assessment"] = "high-risk"
    _json(acceptance_path, acceptance)
    with pytest.raises(handoff.FidelityPhysicalHandoffError, match="skin QA is not acceptable"):
        handoff.seal_physical_handoff(
            work_root=root,
            rig_setup=rig,
            expected_revision=REVISION,
            expected_performer_id="42",
            expected_body_alias="lauren-phillips-pr40-physical01",
            expected_policy=POLICY,
            human_geometry_approved=True,
        )


def test_verify_rejects_any_sealed_artifact_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, rig, _ = _fixture(tmp_path, monkeypatch)
    receipt = handoff.seal_physical_handoff(
        work_root=root,
        rig_setup=rig,
        expected_revision=REVISION,
        expected_performer_id="42",
        expected_body_alias="lauren-phillips-pr40-physical01",
        expected_policy=POLICY,
        human_geometry_approved=True,
    )
    skin_path = root / "rebuild-01" / "full" / "acceptance" / "bodyrig-skin-qa.json"
    skin_path.write_text(skin_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(handoff.FidelityPhysicalHandoffError, match="handoff artifact hash mismatch"):
        handoff.verify_physical_handoff(
            receipt,
            work_root=root,
            rig_setup=rig,
            expected_revision=REVISION,
            expected_performer_id="42",
            expected_body_alias="lauren-phillips-pr40-physical01",
        )
