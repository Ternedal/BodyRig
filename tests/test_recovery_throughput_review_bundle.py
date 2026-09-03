from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.recovery_throughput_review_bundle as bundle
from bodyrig.person_body_review import CANONICAL_VIEWS
from bodyrig.recovery_throughput_sampling_audit import RunEvidence


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _run(root: Path, *, job_id: str, revision: str, package_byte: bytes) -> RunEvidence:
    review_root = root / job_id
    review_root.mkdir(parents=True)
    views = []
    for view in CANONICAL_VIEWS:
        raw = f"{job_id}:{view}".encode()
        path = review_root / f"{view}.png"
        path.write_bytes(raw)
        views.append(
            {
                "view": view,
                "file": f"{view}.png",
                "sha256": _sha(raw),
                "width": 1024,
                "height": 1024,
            }
        )
    return RunEvidence(
        job={
            "job_id": job_id,
            "person_id": "person-" + "a" * 32,
            "bodyrig_revision": revision,
        },
        binding={},
        selection={},
        segments={},
        recovery={},
        identity={},
        acceptance={},
        fidelity={},
        review={"root": str(review_root), "views": views},
        package_sha256=_sha(package_byte),
        total_seconds=100.0,
        clone_pipeline_seconds=80.0,
    )


def _machine(*, passed: bool = True) -> dict:
    return {
        "machine_evidence_pass": passed,
        "decision": "eligible-for-human-ab-review" if passed else "blocked",
        "blockers": [] if passed else ["source authority differs"],
        "frames": {"baseline": 1000, "candidate": 500},
        "timing": {"baseline_clone_pipeline_seconds": 7200.0, "candidate_clone_pipeline_seconds": 3600.0},
        "promotion_authority": False,
        "production_activation": False,
        "human_visual_review_required": True,
    }


def test_bundle_is_create_only_hash_bound_and_non_authoritative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _run(tmp_path / "sources", job_id="job-" + "1" * 32, revision="b" * 40, package_byte=b"baseline")
    candidate = _run(tmp_path / "sources", job_id="job-" + "2" * 32, revision="c" * 40, package_byte=b"candidate")
    runs = iter((baseline, candidate))
    monkeypatch.setattr(bundle, "audit", lambda *args, **kwargs: _machine())
    monkeypatch.setattr(bundle, "collect_run", lambda *args, **kwargs: next(runs))

    out = tmp_path / "bundle"
    receipt = bundle.build_bundle(
        "baseline",
        "candidate",
        expected_candidate_bodyrig_revision="c" * 40,
        out_dir=out,
    )

    assert receipt["format"] == bundle.FORMAT
    assert receipt["semantics"] == bundle.SEMANTICS
    assert receipt["human_visual_review_required"] is True
    assert receipt["promotion_authority"] is False
    assert receipt["production_activation"] is False
    assert receipt["baseline_job_id"] == baseline.job["job_id"]
    assert receipt["candidate_job_id"] == candidate.job["job_id"]
    assert (out / "index.html").is_file()
    assert (out / "machine-audit.json").is_file()
    for view in CANONICAL_VIEWS:
        assert (out / "baseline" / f"{view}.png").is_file()
        assert (out / "candidate" / f"{view}.png").is_file()
    assert bundle.verify_bundle(out) == receipt

    with pytest.raises(bundle.RecoveryThroughputReviewBundleError, match="refusing to overwrite"):
        bundle.build_bundle(
            "baseline",
            "candidate",
            expected_candidate_bodyrig_revision="c" * 40,
            out_dir=out,
        )


def test_bundle_refuses_to_copy_any_review_bytes_until_machine_gate_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundle, "audit", lambda *args, **kwargs: _machine(passed=False))
    monkeypatch.setattr(bundle, "collect_run", lambda *args, **kwargs: pytest.fail("collect_run must not run after blocked machine gate"))
    out = tmp_path / "blocked"
    with pytest.raises(bundle.RecoveryThroughputReviewBundleError, match="machine A/B gate did not pass"):
        bundle.build_bundle(
            "baseline",
            "candidate",
            expected_candidate_bodyrig_revision="c" * 40,
            out_dir=out,
        )
    assert not out.exists()


def test_verify_bundle_rejects_changed_review_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _run(tmp_path / "sources", job_id="job-" + "3" * 32, revision="b" * 40, package_byte=b"baseline")
    candidate = _run(tmp_path / "sources", job_id="job-" + "4" * 32, revision="c" * 40, package_byte=b"candidate")
    runs = iter((baseline, candidate))
    monkeypatch.setattr(bundle, "audit", lambda *args, **kwargs: _machine())
    monkeypatch.setattr(bundle, "collect_run", lambda *args, **kwargs: next(runs))
    out = tmp_path / "bundle"
    bundle.build_bundle(
        "baseline",
        "candidate",
        expected_candidate_bodyrig_revision="c" * 40,
        out_dir=out,
    )
    (out / "candidate" / "face-front.png").write_bytes(b"tampered")
    with pytest.raises(bundle.RecoveryThroughputReviewBundleError, match="has changed"):
        bundle.verify_bundle(out)


def test_bundle_receipt_cannot_be_reinterpreted_as_a_human_decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _run(tmp_path / "sources", job_id="job-" + "5" * 32, revision="b" * 40, package_byte=b"baseline")
    candidate = _run(tmp_path / "sources", job_id="job-" + "6" * 32, revision="c" * 40, package_byte=b"candidate")
    runs = iter((baseline, candidate))
    monkeypatch.setattr(bundle, "audit", lambda *args, **kwargs: _machine())
    monkeypatch.setattr(bundle, "collect_run", lambda *args, **kwargs: next(runs))
    out = tmp_path / "bundle"
    receipt = bundle.build_bundle(
        "baseline",
        "candidate",
        expected_candidate_bodyrig_revision="c" * 40,
        out_dir=out,
    )
    forbidden = {"approved", "accepted", "human_pass", "production_ready", "decision"}
    assert forbidden.isdisjoint(receipt)
