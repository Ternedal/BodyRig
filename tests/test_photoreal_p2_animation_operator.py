from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p2-animation.ps1"


def test_p2_operator_requires_clean_main_and_existing_p1_pass_artifacts() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert 'Join-Path $teacherWorkspace "output"' in source
    assert 'Join-Path $p1Root "p1-likeness-review.json"' in source
    assert 'Join-Path $p1ReviewRoot "p1-likeness-review-manifest.json"' in source


def test_p2_operator_builds_contract_without_running_animation_or_rehashing_sources() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "bodyrig.photoreal_p2_animation_plan" in source
    assert '"--reuse-existing"' in source
    assert "Source rehash:      NO" in source
    assert "Animation run:      NOT STARTED" in source
    assert "Animation execution remains NOT STARTED." in source
    assert "animate.py --" not in source
    assert "Get-FileHash" not in source


def test_p2_operator_preserves_downstream_authority_boundaries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "p2_animation_build_authorized" in source
    assert "p2_animated_teacher_acceptance_authority" in source
    assert "quest_distillation_authorized" in source
    assert "photoreal_acceptance_authority" in source
    assert "production_activation" in source
    assert "Next authority boundary: provide hash-bound motion evidence" in source


def test_p2_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return

    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
