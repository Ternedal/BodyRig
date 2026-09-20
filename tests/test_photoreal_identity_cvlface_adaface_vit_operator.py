from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "diagnose-photoreal-v2-identity-cvlface-adaface-vit.ps1"
SETUP = ROOT / "setup-photoreal-v2-cvlface-adaface-vit-diagnostic.ps1"


def test_cvlface_operator_is_fail_closed_and_avoids_source_rehash() -> None:
    source = OPERATOR.read_text(encoding="utf-8")

    assert "CVLFACE ADAFACE VIT DIAGNOSTIC" in source
    assert "CVLFace / AdaFace / ViT-Base@WebFace4M" in source
    assert "Source rehash:  NO" in source
    assert "DIAGNOSTIC ONLY / FALSE" in source
    assert "--cvlface-root" in source
    assert "photoreal_identity_cvlface_adaface_vit_diagnostic.py" in source
    assert "AcceptTrainingDatasetTerms" in source
    assert "identity-extractor\\request.json" in source
    assert "identity-calibration-extractor\\request.json" in source
    assert (
        "identity-calibration-extractor\\output\\negative-observations.json"
        in source
    )
    assert "BODYRIG_REVISION=$head" in source
    assert "no identity matching, training, photoreal or production authority" in source


def test_cvlface_setup_pins_revision_model_sha_and_authority() -> None:
    source = SETUP.read_text(encoding="utf-8")

    assert "minchul/cvlface_adaface_vit_base_webface4m" in source
    assert "b95848ffb6cfbcdba67a4e24adf3c0b91518d7e3" in source
    assert (
        "5fafd6b7d599a3ede5fac5bd1d01ad05"
        "e9e93e89b39b7687d4a3bc93ff2aebc0"
    ) in source
    assert "AcceptTrainingDatasetTerms" in source
    assert "reuses_bodyrig_photoreal_torch = $true" in source
    assert "parallel_torch_install = $false" in source
    assert "diagnostic_only = $true" in source
    assert "identity_matching_authorized = $false" in source
    assert "teacher_training_authorized = $false" in source
    assert "photoreal_acceptance_authority = $false" in source
    assert "production_activation = $false" in source
    assert "hf_hub_download" in source
    assert "\"--no-deps\"" in source
    assert "\"torch==\"" not in source
    assert "\"torchvision==\"" not in source
    assert "\"cuda-toolkit\"" not in source
    assert "\"nvidia-cudnn\"" not in source
    assert "\"cvlface-stage-*\"" in source


@pytest.mark.parametrize("script", [OPERATOR, SETUP])
def test_cvlface_scripts_parse_when_pwsh_available(script: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")
    command = (
        "$tokens=$null; $errors=$null; "
        "$null=[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:BODYRIG_PARSE_SCRIPT,[ref]$tokens,[ref]$errors); "
        "if ($errors.Count -ne 0) { "
        "$errors | ForEach-Object { Write-Error $_ }; exit 1 }; exit 0"
    )
    env = os.environ.copy()
    env["BODYRIG_PARSE_SCRIPT"] = str(script)
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-Command", command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
