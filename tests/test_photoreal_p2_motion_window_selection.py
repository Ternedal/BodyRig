from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bodyrig.photoreal_p2_motion_window_selection import (
    PhotorealP2MotionWindowSelectionError,
    _duration_from_scan_source,
)
from bodyrig.photoreal_p2_motion_window_selection_cli import _parse_windows


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "record-photoreal-v2-p2-motion-window-selection.ps1"


def test_scan_midpoints_reconstruct_source_duration() -> None:
    source = {
        "kind": "video",
        "samples": [
            {"timestamp_seconds": 2.5, "eye": "mono"},
            {"timestamp_seconds": 7.5, "eye": "mono"},
        ],
    }
    assert _duration_from_scan_source(source) == 10.0


def test_window_parser_accepts_bounded_selection_syntax() -> None:
    assert _parse_windows(["src-a=obs-abc,2.0,1.5"]) == {
        "src-a": {
            "observation_ref": "obs-abc",
            "before_seconds": 2.0,
            "after_seconds": 1.5,
        }
    }


def test_window_parser_rejects_duplicate_source() -> None:
    with pytest.raises(
        PhotorealP2MotionWindowSelectionError,
        match="empty/repeated",
    ):
        _parse_windows(
            [
                "src-a=obs-a,1.0,1.0",
                "src-a=obs-b,1.0,1.0",
            ]
        )


def test_operator_requires_strict_p0_artifact_universe() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for filename in (
        "scan-plan.json",
        "dataset-plan.json",
        "source-receipt.json",
        "frame-authorized-observations.json",
        "frame-index.json",
    ):
        assert filename in source
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source


def test_operator_stops_before_physical_work() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "HUMAN REVIEW REQUIRED." in source
    assert "No video was decoded, deprojected, fitted, or rehashed." in source
    assert "maximum_total_window_seconds" in source
    assert "exit 2" in source
    assert "Get-FileHash" not in source
    assert "ffmpeg" not in source.lower()


def test_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
