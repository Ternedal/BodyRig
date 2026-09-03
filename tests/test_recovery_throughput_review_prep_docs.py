from __future__ import annotations

from pathlib import Path


DOC = (Path(__file__).resolve().parents[1] / "docs" / "RECOVERY_THROUGHPUT_REVIEW_PREP.md").read_text(encoding="utf-8")


def test_review_prep_doc_uses_only_existing_canonical_machine_and_bundle_gates() -> None:
    assert "prepare-recovery-throughput-review.ps1" in DOC
    assert "compare-recovery-throughput-auto.ps1" in DOC
    assert "newest-candidate + exact-parent-baseline" in DOC
    assert "build-recovery-throughput-review-bundle.ps1" in DOC
    assert "independently re-runs the full machine evidence gate" in DOC


def test_review_prep_doc_keeps_human_restore_and_authority_boundaries_explicit() -> None:
    assert "does **not**" in DOC
    assert "record a human visual PASS or FAIL" in DOC
    assert "switch Git branches or update BodyRig" in DOC
    assert "restore Person Studio authority" in DOC
    assert "merge PR #60" in DOC
    assert "move physical authority" in DOC
    assert "grant promotion or production authority" in DOC
    assert "record-recovery-throughput-human-review.ps1" in DOC
    assert "RECOVERY_THROUGHPUT_AB.md" in DOC
