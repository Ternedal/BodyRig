from __future__ import annotations

from pathlib import Path


def test_package_bound_human_review_is_copied_and_revalidated_for_gate_a_package() -> None:
    source = (Path(__file__).resolve().parents[1] / "bodyrig" / "high_fidelity_physical_acceptance.py").read_text(encoding="utf-8")
    assert 'review_source = human_review_path(package, package_sha256=package_sha)' in source
    assert 'review_copy = human_review_path(accepted, package_sha256=package_sha)' in source
    assert '_copy(review_source, review_copy, "high-fidelity human review")' in source
    assert 'read_human_review(accepted)' in source
