from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-appearance-epoch-review.ps1"


def test_operator_requires_clean_main_and_authorized_p0() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "rev-parse --abbrev-ref HEAD" in source
    assert "requires the main branch" in source
    assert "status --porcelain" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert '"teacher-training-authorized"' in source
    assert "teacher_training_authorized" in source
    assert "photoreal_acceptance_authority" in source
    assert "production_activation" in source


def test_operator_explicitly_avoids_source_media_rehash() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Source rehash:   NO" in source
    assert "source_media_rehash_performed" in source
    assert "Get-FileHash -LiteralPath $frameIndex" in source
    assert "Get-FileHash -LiteralPath $sourceReceipt" not in source
    assert "Get-FileHash -LiteralPath $datasetPlan" not in source


def test_operator_builds_private_path_map_then_exact_frame_review_pack() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "photoreal_appearance_epoch_visual_review path-map" in source
    assert "photoreal_appearance_epoch_visual_review" in source
    assert '"prepare"' in source
    assert '"--reuse-existing"' in source
    assert "EXACT P0 AUTHORIZED OBSERVATIONS ONLY" in source
    assert "appearance-epoch-visual-review-manifest.json" in source
    assert "private-review-index.json" in source
    assert "review-index.html" in source


def test_operator_never_auto_opens_or_approves_review() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'Write-Host (\'  Start-Process "\' + $reviewIndex + \'"\')' in source
    assert "& Start-Process" not in source
    assert "Teacher input:   FALSE" in source
    assert "Photoreal auth:  FALSE" in source
    assert "Production:      FALSE" in source


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
