from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
EYE = ROOT / "extract-eye-appearance.ps1"
ORCHESTRATOR = ROOT / "bodyrig" / "sith_fitter_orchestrator.py"
GEOMETRY = ROOT / "bodyrig" / "sith_body_geometry_authority.py"
EXTERNAL_FITTER = ROOT / "bodyrig" / "external_fitter_cli.py"


def test_canonical_resume_and_geometry_routes_revalidate_reconstruction_authority() -> None:
    orchestrator = ORCHESTRATOR.read_text(encoding="utf-8")
    geometry = GEOMETRY.read_text(encoding="utf-8")
    external = EXTERNAL_FITTER.read_text(encoding="utf-8")

    resume_authority = orchestrator.index("validate_reconstruction_authority(")
    resume_read = orchestrator.index(
        'evidence = _load_json_object(evidence_path, label="SiTH resume reconstruction evidence")',
        resume_authority,
    )
    assert resume_authority < resume_read

    geometry_read = geometry.index(
        'reconstruction = _load_json(reconstruction_path, label="SiTH reconstruction evidence")'
    )
    geometry_authority = geometry.index("validate_reconstruction_authority(", geometry_read)
    assert geometry_read < geometry_authority

    bind = external.index("avatar_vrm = bind_sith_body_geometry_authority(")
    retained = external.index("publish_retained_anatomy_source(", bind)
    assert bind < retained


def test_eye_appearance_validates_reconstruction_before_texture_selection() -> None:
    source = EYE.read_text(encoding="utf-8")

    assert "function Test-V1Version($Value)" in source
    reconstruction_read = source.index(
        "$reconstructionValue = Get-Content -LiteralPath $reconstruction -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20"
    )
    version_guard = source.index("Test-V1Version $reconstructionValue.version", reconstruction_read)
    texture_read = source.index("$textureName = [string]$reconstructionValue.reconstruction.mesh_texture_name", version_guard)
    assert reconstruction_read < version_guard < texture_read
    assert '[string]$reconstructionValue.format -ne "bodyrig-sith-reconstruction"' in source[
        reconstruction_read:texture_read
    ]

    assert "Test-V1Version $evidence.version" in source
    assert "[int]$evidence.version" not in source


def test_eye_appearance_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    eye = str(EYE.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{eye}', [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{
    $errors | ForEach-Object {{ Write-Error $_.Message }}
    exit 20
}}
$fn = $ast.Find({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-V1Version' }}, $true)
if ($null -eq $fn) {{ exit 21 }}
Invoke-Expression $fn.Extent.Text

if (-not (Test-V1Version 1)) {{ exit 31 }}
if (-not (Test-V1Version 1.0)) {{ exit 32 }}
if (Test-V1Version $true) {{ exit 33 }}
if (Test-V1Version $false) {{ exit 34 }}
if (Test-V1Version '1') {{ exit 35 }}
if (Test-V1Version $null) {{ exit 36 }}
if (Test-V1Version 2) {{ exit 37 }}
exit 0
"""
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
