from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_all_renderer_and_release_entrypoints_require_visual_authority() -> None:
    files = (
        "run-reference-windows-renderer-probe.ps1",
        "run-windows-renderer-probe.ps1",
        "run-reference-quest-renderer-probe.ps1",
        "run-quest-renderer-probe.ps1",
        "record-reference-renderer-acceptance.ps1",
        "record-renderer-acceptance.ps1",
        "complete-reference-acceptance.ps1",
        "complete-acceptance.ps1",
    )
    for name in files:
        source = _text(name)
        assert "assert-runtime-visual-authority.ps1" in source, name
        assert "AcceptanceDir" in source or "reportDir" in source or "$dir" in source, name


def test_visual_authority_guard_runs_before_windows_player_launch() -> None:
    outer = _text("run-reference-windows-renderer-probe.ps1")
    inner = _text("run-windows-renderer-probe.ps1")
    assert outer.index("assert-runtime-visual-authority.ps1") < outer.index("& $inner @args")
    assert inner.index("assert-runtime-visual-authority.ps1") < inner.index("Invoke-NativeProcessWait")


def test_visual_authority_promotion_is_p3_only_and_non_activating() -> None:
    source = _text("promote-photoreal-runtime-visual-authority.ps1")
    assert "bodyrig.runtime_visual_authority promote" in source
    assert "--p3-receipt" in source
    assert "Production activation: FALSE" in source
