from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.recovery_throughput_human_review as review


def _bundle(root: Path, *, machine_pass: bool = True) -> dict:
    root.mkdir(parents=True)
    (root / "review-bundle.json").write_text('{"bundle":1}\n', encoding="utf-8")
    machine = {
        "machine_evidence_pass": machine_pass,
        "decision": "eligible-for-human-ab-review" if machine_pass else "blocked",
        "promotion_authority": False,
        "production_activation": False,
    }
    (root / "machine-audit.json").write_text(json.dumps(machine) + "\n", encoding="utf-8")
    return {
        "person_id": "person-" + "a" * 32,
        "baseline_job_id": "job-" + "1" * 32,
        "candidate_job_id": "job-" + "2" * 32,
        "baseline_bodyrig_revision": "b" * 40,
        "candidate_bodyrig_revision": "c" * 40,
        "views": [
            {
                "view": name,
                "baseline_sha256": char * 64,
                "candidate_sha256": char.upper() * 64,
                "width": 1024,
                "height": 1024,
            }
            for name, char in (
                ("front-full", "a"),
                ("three-quarter-full", "b"),
                ("side-full", "c"),
                ("face-front", "d"),
            )
        ],
    }


def _criteria(**overrides: str) -> dict[str, str]:
    values = {
        "identity_shape": "pass",
        "face_identity": "pass",
        "skin_texture_alignment": "pass",
        "gross_anatomy": "pass",
    }
    values.update(overrides)
    return values


def test_all_pass_records_only_human_evidence_not_promotion_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_value = _bundle(bundle_root)
    monkeypatch.setattr(review, "verify_bundle", lambda path: bundle_value)
    out = tmp_path / "human-review.json"

    receipt = review.record_review(
        bundle_root,
        out_path=out,
        reviewer="operator-a",
        criteria=_criteria(),
        note="No material visual regression across all canonical views.",
    )

    assert receipt["human_visual_review_completed"] is True
    assert receipt["human_visual_review_passed"] is True
    assert receipt["decision"] == "no-material-regression"
    assert receipt["next_gate"] == "eligible-for-explicit-promotion-review"
    assert receipt["promotion_authority"] is False
    assert receipt["production_activation"] is False
    assert review.verify_review(out, bundle_dir=bundle_root) == receipt


def test_any_failed_criterion_blocks_next_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_value = _bundle(bundle_root)
    monkeypatch.setattr(review, "verify_bundle", lambda path: bundle_value)
    out = tmp_path / "human-review.json"

    receipt = review.record_review(
        bundle_root,
        out_path=out,
        reviewer="operator-a",
        criteria=_criteria(face_identity="fail"),
        note="Candidate face differs materially from baseline.",
    )

    assert receipt["human_visual_review_passed"] is False
    assert receipt["decision"] == "material-regression"
    assert receipt["next_gate"] == "blocked-material-regression"
    assert receipt["promotion_authority"] is False
    assert receipt["production_activation"] is False


def test_review_refuses_machine_block_and_creates_no_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_value = _bundle(bundle_root, machine_pass=False)
    monkeypatch.setattr(review, "verify_bundle", lambda path: bundle_value)
    out = tmp_path / "human-review.json"

    with pytest.raises(review.RecoveryThroughputHumanReviewError, match="not eligible"):
        review.record_review(
            bundle_root,
            out_path=out,
            reviewer="operator-a",
            criteria=_criteria(),
            note="Should never be recorded.",
        )
    assert not out.exists()


def test_review_must_live_outside_immutable_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_value = _bundle(bundle_root)
    monkeypatch.setattr(review, "verify_bundle", lambda path: bundle_value)

    with pytest.raises(review.RecoveryThroughputHumanReviewError, match="outside the immutable review bundle"):
        review.record_review(
            bundle_root,
            out_path=bundle_root / "human-review.json",
            reviewer="operator-a",
            criteria=_criteria(),
            note="No regression.",
        )


def test_review_is_create_only_and_requires_all_explicit_criteria(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_value = _bundle(bundle_root)
    monkeypatch.setattr(review, "verify_bundle", lambda path: bundle_value)
    out = tmp_path / "human-review.json"

    review.record_review(
        bundle_root,
        out_path=out,
        reviewer="operator-a",
        criteria=_criteria(),
        note="No regression.",
    )
    with pytest.raises(review.RecoveryThroughputHumanReviewError, match="refusing to overwrite"):
        review.record_review(
            bundle_root,
            out_path=out,
            reviewer="operator-a",
            criteria=_criteria(),
            note="No regression.",
        )

    other = tmp_path / "incomplete.json"
    with pytest.raises(review.RecoveryThroughputHumanReviewError, match="criteria set"):
        review.record_review(
            bundle_root,
            out_path=other,
            reviewer="operator-a",
            criteria={"identity_shape": "pass"},
            note="Incomplete review.",
        )
    assert not other.exists()


def test_verify_review_rejects_receipt_reinterpreted_as_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_value = _bundle(bundle_root)
    monkeypatch.setattr(review, "verify_bundle", lambda path: bundle_value)
    out = tmp_path / "human-review.json"
    review.record_review(
        bundle_root,
        out_path=out,
        reviewer="operator-a",
        criteria=_criteria(),
        note="No regression.",
    )
    value = json.loads(out.read_text(encoding="utf-8"))
    value["promotion_authority"] = True
    out.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(review.RecoveryThroughputHumanReviewError, match="cannot carry promotion/production authority"):
        review.verify_review(out, bundle_dir=bundle_root)
