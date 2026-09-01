from pathlib import Path


def test_physical_session_status_is_read_only_and_emits_only_allowed_next_steps() -> None:
    text = Path("fidelity-physical-session-status.ps1").read_text(encoding="utf-8")
    assert "fidelity_physical_status_cli" in text
    assert "$env:PYTHONPATH = $helper" in text
    assert "Fidelity status module resolved from a different checkout" in text
    assert "render-historical-baseline" in text
    assert "run-pr40-reconstruction" in text
    assert "watch-pr40" in text
    assert "continue-pr40-gate-render-evaluation" in text
    assert "review-and-seal-pr40-geometry" in text
    assert "run-pr41-fit-only" in text
    assert "finalize-pr40-pr41-review" in text
    assert "review-pr40-pr41-appearance" in text
    assert "-ApproveGeometry" in text
    assert "Do not start another reconstruction" in text
    assert "production activation: FALSE" in text
    assert "Remove-Item -LiteralPath" not in text
    assert "Move-Item" not in text
    assert "Set-Content" not in text
