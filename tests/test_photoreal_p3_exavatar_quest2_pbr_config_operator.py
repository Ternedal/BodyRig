from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p3-exavatar-quest2-pbr-config.ps1"


def test_config_operator_requires_clean_main_and_pinned_teacher() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert "d45268730c779fae4118f1a361cf9ff639bc4d1e" in source
    assert "exavatar-teacher-config.json" in source


def test_config_operator_pins_exact_adapter_bytes_and_quest2() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Get-FileHash -LiteralPath $adapterPath -Algorithm SHA256" in source
    assert 'adapter = "bodyrig-exavatar-quest2-pbr-v1"' in source
    assert 'student_representation = "skinned-mesh-pbr"' in source
    assert 'supported_target_models = @("quest-2")' in source
    assert "gaussian_splat_target_support = $false" in source


def test_config_operator_requires_eye_hair_and_full_delta_universe() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "specialized-eye-component" in source
    assert "teacher-derived-hair-component" in source
    for dimension in (
        "identity_likeness",
        "face_detail",
        "eyes",
        "hair_silhouette_and_appearance",
        "skin_material_response",
        "hands_and_extremities",
        "motion_identity_preservation",
        "temporal_stability",
    ):
        assert dimension in source
    assert "consumes_staged_teacher_only = $true" in source


def test_config_operator_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
