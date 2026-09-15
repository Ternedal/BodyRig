param(
    [Parameter(Mandatory = $true)][string]$LinuxWorkspaceRoot,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-exavatar/bin/python",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($LinuxWorkspaceRoot) -or -not $LinuxWorkspaceRoot.StartsWith('/')) {
    throw "LinuxWorkspaceRoot must be an absolute Linux path."
}
if ($LinuxWorkspaceRoot -eq "/") { throw "LinuxWorkspaceRoot may not be '/'." }
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) {
    throw "LinuxPython must be an absolute Linux path."
}

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = if (Test-Path (Join-Path $repo ".venv\Scripts\python.exe")) {
    (Resolve-Path (Join-Path $repo ".venv\Scripts\python.exe")).Path
} else {
    (Get-Command python).Source
}

function Invoke-Wsl {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & $WslExe -d $Distribution -- @Arguments
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "WSL command failed with code $code: $($Arguments -join ' ')" }
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL EXAVATAR RUNTIME"
Write-Host "Workspace:          $LinuxWorkspaceRoot"
Write-Host "Python:             $LinuxPython"
Write-Host "Distribution:       $Distribution"
Write-Host "Gaussian extension: WORKSPACE-IN-PLACE"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:          FALSE"
Write-Host "============================================================"

Invoke-Wsl -Arguments @("/usr/bin/test", "-f", "$LinuxWorkspaceRoot/workspace-receipt.json")
Invoke-Wsl -Arguments @("/usr/bin/test", "-x", $LinuxPython)

$gaussian = "$LinuxWorkspaceRoot/repos/diff-gaussian-rasterization-depth"
Invoke-Wsl -Arguments @("/usr/bin/test", "-f", "$gaussian/setup.py")

Write-Host ""
Write-Host "=== 1/2 BUILD PINNED GAUSSIAN CUDA EXTENSION ==="
Invoke-Wsl -Arguments @(
    "/usr/bin/env",
    "FORCE_CUDA=1",
    "PYTHONNOUSERSITE=1",
    $LinuxPython,
    "$gaussian/setup.py",
    "build_ext",
    "--inplace"
)

Write-Host ""
Write-Host "=== 2/2 RUNTIME PREFLIGHT ==="
$code = @'
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo))
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter

converter = make_wsl_path_converter(sys.argv[2], sys.argv[3])
print(converter(str(repo)))
'@
$linuxRepo = (& $py -c $code $repo $WslExe $Distribution).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($linuxRepo)) {
    throw "Could not translate BodyRig repository path into WSL."
}

$receipt = "$LinuxWorkspaceRoot/runtime-preflight.json"
& $WslExe -d $Distribution -- /usr/bin/test '!' -e $receipt
if ($LASTEXITCODE -ne 0) { throw "Runtime preflight receipt already exists: $receipt" }

& $WslExe -d $Distribution -- /usr/bin/env `
    "PYTHONPATH=$linuxRepo" `
    "PYTHONNOUSERSITE=1" `
    $LinuxPython `
    -m bodyrig.photoreal_exavatar_runtime_preflight_cli `
    --workspace-root $LinuxWorkspaceRoot `
    --out $receipt
$preflightCode = $LASTEXITCODE
if ($preflightCode -eq 2) {
    Write-Host ""
    Write-Host "BodyRig ExAvatar runtime: BLOCKED (see $receipt)"
    exit 2
}
if ($preflightCode -ne 0) {
    throw "BodyRig ExAvatar runtime preflight failed with code $preflightCode"
}

Write-Host ""
Write-Host "BodyRig ExAvatar runtime: READY"
Write-Host "Receipt:            $receipt"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:          FALSE"
