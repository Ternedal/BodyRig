param(
    [string]$LinuxWorkspaceRoot = '/opt/bodyrig-exavatar/workspaces/bodyrig-42-1d2f658e0fa9',
    [string]$Distribution = 'Ubuntu-22.04',
    [string]$LinuxPython = '/opt/bodyrig-exavatar/bin/python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$diagnostic = Join-Path $repoRoot 'tools\photoreal_exavatar_fit_diagnostic.py'

if (-not (Test-Path -LiteralPath $diagnostic -PathType Leaf)) {
    throw "Fit diagnostic script not found: $diagnostic"
}

$resolvedDiagnostic = (Resolve-Path -LiteralPath $diagnostic).Path
if ($resolvedDiagnostic -notmatch '^([A-Za-z]):\\(.*)$') {
    throw "Fit diagnostic path is not on a Windows drive: $resolvedDiagnostic"
}

$drive = $Matches[1].ToLowerInvariant()
$rest = $Matches[2] -replace '\\', '/'
$linuxDiagnostic = "/mnt/$drive/$rest"

Write-Host '============================================================'
Write-Host 'BODYRIG EXAVATAR SMPL-X FIT DIAGNOSTIC'
Write-Host "Workspace: $LinuxWorkspaceRoot"
Write-Host "Distribution: $Distribution"
Write-Host "Python: $LinuxPython"
Write-Host 'Publishes to production dataset: FALSE'
Write-Host '============================================================'

& wsl.exe -d $Distribution -- /usr/bin/env `
    PYTHONNOUSERSITE=1 `
    CUDA_VISIBLE_DEVICES=0 `
    PYOPENGL_PLATFORM=egl `
    $LinuxPython `
    $linuxDiagnostic `
    --workspace-root $LinuxWorkspaceRoot

if ($LASTEXITCODE -ne 0) {
    throw "BodyRig ExAvatar fit diagnostic failed with code $LASTEXITCODE"
}
