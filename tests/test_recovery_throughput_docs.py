from pathlib import Path


DOC = (Path(__file__).resolve().parents[1] / "docs" / "RECOVERY_THROUGHPUT_CANDIDATE.md").read_text(encoding="utf-8")


def test_throughput_candidate_requires_physical_promotion_evidence() -> None:
    assert "must not become physical authority from CI alone" in DOC
    assert "Spatial resolution is not scaled" in DOC
    assert "Gate A" in DOC
    assert "canonical fidelity review images" in DOC
    assert "baseline versus candidate" in DOC


def test_throughput_doc_does_not_promise_wall_clock_speedup() -> None:
    assert "not promised wall-clock speedups" in DOC
