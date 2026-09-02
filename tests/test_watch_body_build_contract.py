from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "watch-body-build.ps1").read_text(encoding="utf-8")


def test_monitor_is_read_only_and_never_controls_processes() -> None:
    forbidden = (
        "Stop-Process",
        "Start-Process",
        "Remove-Item",
        "Move-Item",
        "Set-Content",
        "Add-Content",
        "git checkout",
        "git reset",
    )
    for token in forbidden:
        assert token not in SCRIPT


def test_monitor_can_select_exact_or_latest_body_job() -> None:
    assert '[string]$JobId = ""' in SCRIPT
    assert "^job-[0-9a-f]{32}$" in SCRIPT
    assert '[string]$job.kind -ne "body-build"' in SCRIPT
    assert '@("queued", "running")' in SCRIPT


def test_monitor_binds_recovery_staging_to_person_source_paths() -> None:
    assert '"bodyrig-wsl-recovery-*"' in SCRIPT
    assert 'Join-Path $candidate.FullName "request.json"' in SCRIPT
    assert '$_ -like "*$personId*"' in SCRIPT
    assert 'Join-Path $candidate.FullName "stderr.log"' in SCRIPT
    assert 'Join-Path $candidate.FullName "status.json"' in SCRIPT


def test_monitor_prefers_live_checkpoint_status_and_segment_log() -> None:
    assert '"bodyrig-recovery-checkpoints"' in SCRIPT
    assert '"segment-*.status.json"' in SCRIPT
    assert '"bodyrig-recovery-segment-status"' in SCRIPT
    assert 'State -eq "running"' in SCRIPT
    assert '"segment-{0:D2}"' in SCRIPT
    assert 'ProgressSource = $progressSource' in SCRIPT
    assert '"checkpoint"' in SCRIPT


def test_monitor_translates_checkpoint_sources_without_shelling_out() -> None:
    assert "function Convert-WslMountPathToWindows" in SCRIPT
    assert "^/mnt/([A-Za-z])/(.+)$" in SCRIPT
    assert ".Replace('/', '\\\\')" in SCRIPT


def test_monitor_surfaces_segment_and_gpu_progress_without_fake_eta() -> None:
    assert "CurrentSegment" in SCRIPT
    assert "CompletedSegments" in SCRIPT
    assert "SourceCount" in SCRIPT
    assert "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu" in SCRIPT
    assert "ETA" not in SCRIPT
    assert "remaining" not in SCRIPT.lower()


def test_monitor_has_once_mode_for_operator_checks() -> None:
    assert "[switch]$Once" in SCRIPT
    assert 'if ($Once -or @("succeeded", "failed", "canceled", "interrupted")' in SCRIPT
