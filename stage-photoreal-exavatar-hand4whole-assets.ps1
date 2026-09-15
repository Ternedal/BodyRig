param(
    [Parameter(Mandatory = $true)][string]$LinuxWorkspaceRoot,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
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

$code = @'
import sys
from pathlib import Path
repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo))
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
print(make_wsl_path_converter(sys.argv[2], sys.argv[3])(str(repo)))
'@
$linuxRepo = (& $py -c $code $repo $WslExe $Distribution).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($linuxRepo)) {
    throw "Could not translate BodyRig repository path into WSL."
}

Write-Host ""
Write-Host "=== HAND4WHOLE HUMAN-MODEL ASSET STAGE ==="
& $WslExe -d $Distribution -- /usr/bin/env `
    "PYTHONPATH=$linuxRepo" `
    "PYTHONNOUSERSITE=1" `
    $LinuxPython `
    -m bodyrig.photoreal_exavatar_hand4whole_stage_cli `
    --workspace-root $LinuxWorkspaceRoot
$code = $LASTEXITCODE
if ($code -ne 0) {
    throw "BodyRig Hand4Whole asset staging failed with code $code"
}

& $WslExe -d $Distribution -- /usr/bin/test -f "$LinuxWorkspaceRoot/hand4whole-assets-receipt.json"
if ($LASTEXITCODE -ne 0) {
    throw "Hand4Whole asset receipt was not created."
}

Write-Host "BodyRig Hand4Whole assets: READY"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production: FALSE"
