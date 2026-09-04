from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "diagnose-failed-body-build.ps1").read_text(encoding="utf-8")


def test_probe_can_auto_select_latest_terminal_body_job() -> None:
    assert '[string]$JobId = ""' in SCRIPT
    assert '"failed", "interrupted", "canceled"' in SCRIPT
    assert 'latest failed body-build' in SCRIPT
    assert 'BODYRIG_DATA_DIR' in SCRIPT
    assert 'LOCALAPPDATA' in SCRIPT


def test_probe_invokes_only_read_only_python_inspector() -> None:
    assert '-m bodyrig.recovery_rescue_probe --job-id $JobId' in SCRIPT
    forbidden = (
        "Remove-Item",
        "Set-Content",
        "Stop-Process",
        "git checkout",
        "git reset",
        "Start-Process",
    )
    for token in forbidden:
        assert token not in SCRIPT
