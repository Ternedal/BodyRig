from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.fidelity_physical_status as status

SNAPSHOTS = ("front-full.png", "three-quarter-full.png", "side-full.png", "face-front.png")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshots(path: Path, *, package_sha: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    entries = []
    for name in SNAPSHOTS:
        image = path / name
        image.write_bytes(("fixture:" + name).encode("utf-8"))
        entries.append(
            {
                "view": name.removesuffix(".png"),
                "file": name,
                "width": 1024,
                "height": 1024,
                "sha256": _sha(image),
            }
        )
    (path / "fidelity-render-set.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-fidelity-render-set",
                "version": 1,
                "semantics": "visual-fidelity-not-identity-verification",
                "body_id": "fixture",
                "package_sha256": package_sha,
                "snapshots": entries,
            }
        ),
        encoding="utf-8",
    )
    return path


def _base(tmp_path: Path) -> tuple[Path, Path, Path]:
    work = tmp_path / "work"
    baseline = tmp_path / "baseline"
    rig = tmp_path / "rig.json"
    rig.write_text("{}", encoding="utf-8")
    return work, baseline, rig


def _baseline(path: Path) -> Path:
    return _snapshots(path / "snapshots", package_sha=status.KNOWN_BAD_PACKAGE_SHA256)


def _checkpoint(work: Path, *, stage: str) -> tuple[Path, dict]:
    path = work / "checkpoints" / "checkpoint-000001.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    records = []
    if stage == "post-candidate":
        candidate_dir = work / "rebuild-01" / "full"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        package = candidate_dir / "candidate.mrbody"
        package.write_bytes(b"candidate-package")
        render = candidate_dir / "comparison-render"
        _snapshots(render / "snapshots", package_sha=_sha(package))
        records = [
            {
                "mode": "full-reconstruction",
                "package_path": "rebuild-01/full/candidate.mrbody",
                "render_dir": "rebuild-01/full/comparison-render",
                "evaluation_path": "rebuild-01/full/evaluation.json",
                "acceptance_dir": "rebuild-01/full/acceptance",
            }
        ]
    value = {
        "stage": stage,
        "state": {
            "candidate_records": records,
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
    _baseline(baseline)
    work.mkdir()
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "pr40-awaiting-checkpoint"
    assert value["next_action"] == "watch-pr40"
    assert value["next_action"] != "run-pr40-reconstruction"


def test_status_reports_verified_post_reconstruction_without_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig = _base(tmp_path)
    _baseline(baseline)
    checkpoint_path, checkpoint = _checkpoint(work, stage="post-reconstruction")
    monkeypatch.setattr(status, "load_latest_checkpoint", lambda *args, **kwargs: (checkpoint_path, checkpoint))
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "pr40-reconstruction-checkpointed"
    assert value["next_action"] == "continue-pr40-gate-render-evaluation"


def test_status_requires_human_geometry_seal_before_pr41(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig = _base(tmp_path)
    _baseline(baseline)
    checkpoint_path, checkpoint = _checkpoint(work, stage="post-candidate")
    monkeypatch.setattr(status, "load_latest_checkpoint", lambda *args, **kwargs: (checkpoint_path, checkpoint))
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "pr40-awaiting-human-geometry-review"
    assert value["next_action"] == "review-and-seal-pr40-geometry"


def _sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path, dict]:
    work, baseline, rig = _base(tmp_path)
    _baseline(baseline)
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
    package = pr41 / "lauren-phillips-pr41-ab.mrbody"
    package.write_bytes(b"fixture")
    _snapshots(pr41 / "comparison-render" / "snapshots", package_sha=_sha(package))
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "pr41-render-ready"
    assert value["next_action"] == "finalize-pr40-pr41-review"


def _final_review_fixture(work: Path) -> tuple[Path, Path]:
    final = work / "pr40-pr41-review"
    final.mkdir()
    evidence_path = final / "pr40-pr41-ab-evidence.json"
    evidence_path.write_text(
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
    (review / "review-bundle-receipt.json").write_text("{}", encoding="utf-8")
    return evidence_path, review


def test_status_finishes_only_at_human_appearance_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig, _ = _sealed(tmp_path, monkeypatch)
    pr41 = work / "pr41-clean-ab"
    pr41.mkdir()
    package = pr41 / "lauren-phillips-pr41-ab.mrbody"
    package.write_bytes(b"fixture")
    _snapshots(pr41 / "comparison-render" / "snapshots", package_sha=_sha(package))
    _, review = _final_review_fixture(work)
    monkeypatch.setattr(status, "verify_review_bundle", lambda *args, **kwargs: {"fixture": True})
    value = status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
    assert value["phase"] == "awaiting-human-appearance-review"
    assert value["next_action"] == "review-pr40-pr41-appearance"
    assert value["human_visual_authority_required"] is True
    assert value["production_activation"] is False
    assert value["paths"]["review_receipt"] == str(review / "review-bundle-receipt.json")


def test_status_refuses_unverified_final_review_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig, _ = _sealed(tmp_path, monkeypatch)
    pr41 = work / "pr41-clean-ab"
    pr41.mkdir()
    package = pr41 / "lauren-phillips-pr41-ab.mrbody"
    package.write_bytes(b"fixture")
    _snapshots(pr41 / "comparison-render" / "snapshots", package_sha=_sha(package))
    _final_review_fixture(work)

    def reject(*args, **kwargs):
        raise status.FidelityReviewReceiptError("fixture tamper")

    monkeypatch.setattr(status, "verify_review_bundle", reject)
    with pytest.raises(status.FidelityPhysicalStatusError, match="final review bundle authority is invalid"):
        status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)


def test_status_refuses_incomplete_existing_baseline(tmp_path: Path) -> None:
    work, baseline, rig = _base(tmp_path)
    baseline.mkdir()
    (baseline / "front-full.png").write_bytes(b"fixture")
    with pytest.raises(status.FidelityPhysicalStatusError, match="historical baseline render authority is invalid"):
        status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)


def test_status_refuses_render_pixel_tamper_before_geometry_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, baseline, rig = _base(tmp_path)
    _baseline(baseline)
    checkpoint_path, checkpoint = _checkpoint(work, stage="post-candidate")
    monkeypatch.setattr(status, "load_latest_checkpoint", lambda *args, **kwargs: (checkpoint_path, checkpoint))
    image = work / "rebuild-01" / "full" / "comparison-render" / "snapshots" / "front-full.png"
    image.write_bytes(image.read_bytes() + b"tamper")
    with pytest.raises(status.FidelityPhysicalStatusError, match="#40 render authority is invalid"):
        status.physical_status(work_root=work, baseline_snapshots=baseline, rig_setup=rig)
