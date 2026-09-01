from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.fidelity_physical_status as status


def _snapshots(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in status.SNAPSHOT_NAMES:
        (path / name).write_bytes(("fixture:" + name).encode("utf-8"))
    return path


def _base(tmp_path: Path) -> tuple[Path, Path, Path]:
    work = tmp_path / "work"
    baseline = tmp_path / "baseline"
    rig = tmp_path / "rig.json"
    rig.write_text("{}", encoding="utf-8")
    return work, baseline, rig


def _checkpoint(work: Path, *, stage: str) -> tuple[Path, dict]:
    path = work / "checkpoints" / "checkpoint-000001.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    render = work / "rebuild-01" / "full" / "comparison-render"
    _snapshots(render / "snapshots")
    value = {
        "stage": stage,
        "state": {
            "candidate_records": (
                [
                    {
                        "mode": "full-reconstruction",
                        "package_path": "rebuild-01/full/candidate.mrbody",
                        "render_dir": "rebuild-01/full/comparison-render",
                        "evaluation_path": "rebuild-01/full/evaluation.json",
                        "acceptance_dir": "rebuild-01/full/acceptance",
                    }
                ]
                if stage == "post-candidate"
                else []
            )
        },
    }
    return path, value


def test_status_starts_with_historical_baseline(tmp_path: Path) -> None:
    work, baseline, rig = _base(tmp_path)
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "historical-baseline-missing"
    assert value["next_action"] == "render-historical-baseline"
    assert value["production_activation"] is False


def test_status_never_suggests_second_reconstruction_when_work_root_exists(tmp_path: Path) -> None:
    work, baseline, rig = _base(tmp_path)
    _snapshots(baseline)
    work.mkdir()
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "pr40-awaiting-checkpoint"
    assert value["next_action"] == "watch-pr40"
    assert value["next_action"] != "run-pr40-reconstruction"


def test_status_reports_verified_post_reconstruction_without_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig = _base(tmp_path)
    _snapshots(baseline)
    checkpoint_path, checkpoint = _checkpoint(work, stage="post-reconstruction")
    monkeypatch.setattr(status, "load_latest_checkpoint", lambda *args, **kwargs: (checkpoint_path, checkpoint))
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "pr40-reconstruction-checkpointed"
    assert value["next_action"] == "continue-pr40-gate-render-evaluation"


def test_status_requires_human_geometry_seal_before_pr41(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig = _base(tmp_path)
    _snapshots(baseline)
    checkpoint_path, checkpoint = _checkpoint(work, stage="post-candidate")
    monkeypatch.setattr(status, "load_latest_checkpoint", lambda *args, **kwargs: (checkpoint_path, checkpoint))
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "pr40-awaiting-human-geometry-review"
    assert value["next_action"] == "review-and-seal-pr40-geometry"


def _sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path, dict]:
    work, baseline, rig = _base(tmp_path)
    _snapshots(baseline)
    checkpoint_path, checkpoint = _checkpoint(work, stage="post-candidate")
    monkeypatch.setattr(status, "load_latest_checkpoint", lambda *args, **kwargs: (checkpoint_path, checkpoint))
    receipt = {"fixture": True}
    handoff = work / "handoff" / "pr40-physical-handoff.json"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(status, "verify_physical_handoff", lambda *args, **kwargs: receipt)
    return work, baseline, rig, checkpoint


def test_status_allows_pr41_only_after_verified_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig, _ = _sealed(tmp_path, monkeypatch)
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "pr40-handoff-sealed"
    assert value["next_action"] == "run-pr41-fit-only"


def test_status_requests_finalizer_after_pr41_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig, _ = _sealed(tmp_path, monkeypatch)
    pr41 = work / "pr41-clean-ab"
    pr41.mkdir()
    (pr41 / "lauren-phillips-pr41-ab.mrbody").write_bytes(b"fixture")
    _snapshots(pr41 / "comparison-render" / "snapshots")
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "pr41-render-ready"
    assert value["next_action"] == "finalize-pr40-pr41-review"


def test_status_finishes_only_at_human_appearance_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig, _ = _sealed(tmp_path, monkeypatch)
    pr41 = work / "pr41-clean-ab"
    pr41.mkdir()
    (pr41 / "lauren-phillips-pr41-ab.mrbody").write_bytes(b"fixture")
    _snapshots(pr41 / "comparison-render" / "snapshots")
    final = work / "pr40-pr41-review"
    final.mkdir()
    (final / "pr40-pr41-ab-evidence.json").write_text(
        json.dumps(
            {
                "format": status.AB_FORMAT,
                "version": status.AB_VERSION,
                "invariants": {"clean_appearance_ab": True},
                "human_visual_authority_required": True,
                "production_activation": False,
            }
        ),
        encoding="utf-8",
    )
    review = final / "review-bundle"
    review.mkdir()
    (review / "index.html").write_text("<html></html>", encoding="utf-8")
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "awaiting-human-appearance-review"
    assert value["next_action"] == "review-pr40-pr41-appearance"
    assert value["human_visual_authority_required"] is True
    assert value["production_activation"] is False


def test_status_refuses_incomplete_existing_baseline(tmp_path: Path) -> None:
    work, baseline, rig = _base(tmp_path)
    baseline.mkdir()
    (baseline / "front-full.png").write_bytes(b"fixture")
    with pytest.raises(status.FidelityPhysicalStatusError, match="historical baseline snapshots is incomplete"):
        status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
