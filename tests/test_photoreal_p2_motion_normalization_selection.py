from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bodyrig.photoreal_p2_motion_normalization_selection import (
    PhotorealP2MotionNormalizationSelectionError,
)
from bodyrig.photoreal_p2_motion_normalization_selection_cli import _parse_choices


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "record-photoreal-v2-p2-motion-normalization-selection.ps1"


def test_choice_parser_accepts_eye_and_optional_viewport() -> None:
    assert _parse_choices(["src-a=left@v00", "src-b=right"]) == {
        "src-a": {"eye": "left", "viewport_id": "v00"},
        "src-b": {"eye": "right", "viewport_id": None},
    }


def test_choice_parser_rejects_duplicate_source_ref() -> None:
    with pytest.raises(
        PhotorealP2MotionNormalizationSelectionError,
        match="empty or repeated",
    ):
        _parse_choices(["src-a=left@v00", "src-a=right@v01"])


def test_operator_requires_clean_main_and_original_scan_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert 'Join-Path $P0Root "scan-plan.json"' in source
    assert 'Join-Path $motionInputRoot "p2-motion-input-plan.json"' in source
    assert 'Join-Path $motionInputRoot "p2-motion-normalization-selection.json"' in source


def test_operator_describes_choices_before_recording_and_stops_at_human_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"--describe-only"' in source
    assert "allowed eyes:" in source
    assert "allowed viewports:" in source
    assert "HUMAN REVIEW REQUIRED." in source
    assert "src-...=left@v00" in source
    assert "exit 2" in source


def test_operator_is_metadata_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "No video was decoded, deprojected, fitted, or rehashed." in source
    assert "Get-FileHash" not in source
    assert "ffmpeg" not in source.lower()
    assert "Start-Process" not in source


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
