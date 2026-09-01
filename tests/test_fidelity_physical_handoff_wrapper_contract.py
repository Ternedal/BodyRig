from pathlib import Path


def test_pr40_physical_handoff_wrapper_is_fail_closed_and_exact_head_bound() -> None:
    text = Path("invoke-pr40-physical-handoff.ps1").read_text(encoding="utf-8")
    assert "c9dc066ef40f95a6004499a895b22a9cb3ff26c7" in text
    assert "lauren-phillips-pr40-physical01" in text
    assert "$expectedPerformer = '42'" in text
    assert "max_full_rebuilds\":1" in text
    assert "max_refinements_per_rebuild\":0" in text
    assert "-ApproveGeometry" in text or "$ApproveGeometry" in text
    assert "--human-geometry-approved" in text
    assert "fidelity_physical_handoff_cli seal" in text
    assert "fidelity_physical_handoff_cli verify" in text
    assert "$env:PYTHONPATH = $repoRoot" in text
    assert "Physical-handoff module resolved from a different checkout" in text
    assert "production activation remains false" in text
