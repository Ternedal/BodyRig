from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "complete-photoreal-v2-p3-quest2-physical-evidence-review.ps1"


def test_interactive_review_requires_untouched_machine_prefill() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "operator_supplied=false" in source
    assert "unconfirmed machine prefill" in source
    assert "reviewed_by=REVIEW_REQUIRED" in source
    assert "already contains a human decision" in source


def test_interactive_review_never_auto_selects_visual_pass_fail() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'Read-Host "[$Criterion] pass/fail"' in source
    assert '$value -in @("pass", "fail")' in source
    assert "does not infer or auto-fill any visual PASS/FAIL result" in source
    assert "Type REVIEW COMPLETE" in source


def test_interactive_review_is_create_only_and_requires_final_recorder() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "human review evidence already exists" in source
    assert "No runtime/photoreal acceptance authority has been granted yet." in source
    assert "record-photoreal-v2-p3-quest2-physical-runtime-review.ps1" in source


def test_interactive_review_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
