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
    if ($code -ne 0) { throw "WSL command failed with code ${code}: $($Arguments -join ' ')" }
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
$expectedCudaVersion = "12.4"
$cudaHome = "/usr/local/cuda-$expectedCudaVersion"
$cudaCompiler = "$cudaHome/bin/nvcc"
$cudaRuntimeHeader = "$cudaHome/include/cuda_runtime.h"

Invoke-Wsl -Arguments @("/usr/bin/test", "-f", "$gaussian/setup.py")
Invoke-Wsl -Arguments @("/usr/bin/test", "-x", $cudaCompiler)
Invoke-Wsl -Arguments @("/usr/bin/test", "-f", $cudaRuntimeHeader)

$nvccVersionRaw = @(& $WslExe -d $Distribution -- $cudaCompiler --version 2>&1)
$nvccVersionCode = $LASTEXITCODE
$nvccVersionText = (@($nvccVersionRaw) -join "`n")
if ($nvccVersionCode -ne 0 -or $nvccVersionText -notmatch "release\s+$([regex]::Escape($expectedCudaVersion))(?:,|\s)") {
    throw "Pinned ExAvatar CUDA compiler mismatch: expected $expectedCudaVersion at $cudaCompiler."
}
Write-Host "CUDA toolkit:        $cudaHome"
Write-Host "CUDA runtime header: VERIFIED"

$code = @'
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
& $WslExe -d $Distribution -- /usr/bin/test -f $receipt 2>$null
$runtimeReceiptExists = ($LASTEXITCODE -eq 0)

if ($runtimeReceiptExists) {
    Write-Host ""
    Write-Host "=== 1/2 REVALIDATE EXISTING PINNED CUDA RUNTIME ==="
    & $WslExe -d $Distribution -- /usr/bin/env `
        "PYTHONPATH=$linuxRepo" `
        "PYTHONNOUSERSITE=1" `
        $LinuxPython `
        -m bodyrig.photoreal_exavatar_runtime_preflight_cli `
        --workspace-root $LinuxWorkspaceRoot `
        --out $receipt `
        --reuse-existing
    $preflightCode = $LASTEXITCODE
    if ($preflightCode -eq 0) {
        Write-Host ""
        Write-Host "Gaussian extension: REUSE VALIDATED BUILD"
        Write-Host "BodyRig ExAvatar runtime: READY"
        Write-Host "Receipt:            $receipt"
        Write-Host "Photoreal authority: FALSE"
        Write-Host "Production:          FALSE"
        exit 0
    }
    Write-Host ""
    Write-Host "Existing runtime receipt did not revalidate; rebuilding pinned Gaussian extension."
}

Write-Host ""
Write-Host "=== 1/2 BUILD PINNED GAUSSIAN CUDA EXTENSION ==="
Invoke-Wsl -Arguments @(
    "/usr/bin/env",
    "-C",
    $gaussian,
    "FORCE_CUDA=1",
    "CUDA_HOME=$cudaHome",
    "CUDACXX=$cudaCompiler",
    "PYTHONNOUSERSITE=1",
    $LinuxPython,
    "setup.py",
    "build_ext",
    "--inplace"
)

Write-Host ""
Write-Host "=== 2/2 RUNTIME PREFLIGHT ==="
& $WslExe -d $Distribution -- /usr/bin/env `
    "PYTHONPATH=$linuxRepo" `
    "PYTHONNOUSERSITE=1" `
    $LinuxPython `
    -m bodyrig.photoreal_exavatar_runtime_preflight_cli `
    --workspace-root $LinuxWorkspaceRoot `
    --out $receipt `
    --replace-existing
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
