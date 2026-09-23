from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-exavatar-runtime.ps1"


def test_runtime_operator_revalidates_existing_receipt_before_cuda_rebuild() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '$runtimeReceiptExists = ($LASTEXITCODE -eq 0)' in source
    assert '=== 1/2 REVALIDATE EXISTING PINNED CUDA RUNTIME ===' in source
    assert 'Gaussian extension: REUSE VALIDATED BUILD' in source
    assert source.count("bodyrig.photoreal_exavatar_runtime_preflight_cli") == 2
    assert source.index('$runtimeReceiptExists = ($LASTEXITCODE -eq 0)') < source.index('"build_ext"')
    assert source.index('if ($preflightCode -eq 0)') < source.index('"build_ext"')
    assert source.index('exit 0') < source.index('"build_ext"')


def test_runtime_operator_keeps_rebuild_as_fail_closed_fallback() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'Existing runtime receipt did not revalidate; rebuilding pinned Gaussian extension.' in source
    assert '"FORCE_CUDA=1"' in source
    assert '"build_ext"' in source
    assert '"--inplace"' in source
    assert source.count("--reuse-existing") == 1
    assert source.count("--replace-existing") == 1
    assert source.index('"--inplace"') < source.index("--replace-existing")


def test_runtime_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
