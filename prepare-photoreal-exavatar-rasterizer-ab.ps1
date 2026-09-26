param(
    [string]$LinuxWorkspaceRoot = '/opt/bodyrig-exavatar/workspaces/bodyrig-42-1d2f658e0fa9',
    [string]$Distribution = 'Ubuntu-22.04',
    [string]$LinuxPython = '/opt/bodyrig-exavatar/bin/python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path

$diagnosticBranch = 'diag/exavatar-final-symlink-containment-runner'
$branchRaw = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1) {
    throw 'Could not resolve BodyRig Git branch.'
}
$currentBranch = ([string]$branchRaw[0]).Trim()
if ($currentBranch -ne $diagnosticBranch) {
    throw "This operator requires the diagnostic branch: $diagnosticBranch"
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw 'This diagnostic operator requires a clean BodyRig checkout.'
}
$localHead = @(& git -C $repoRoot rev-parse HEAD 2>&1)
$originHead = @(& git -C $repoRoot rev-parse "refs/remotes/origin/$diagnosticBranch^{commit}" 2>&1)
if (
    $LASTEXITCODE -ne 0 -or
    $localHead.Count -ne 1 -or
    $originHead.Count -ne 1 -or
    ([string]$localHead[0]).Trim().ToLowerInvariant() -ne
        ([string]$originHead[0]).Trim().ToLowerInvariant()
) {
    throw "Diagnostic checkout must exactly match origin/$diagnosticBranch."
}
& git -C $repoRoot merge-base --is-ancestor "refs/remotes/origin/main^{commit}" HEAD 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'Diagnostic checkout must descend from origin/main.'
}
$driveMatch = [regex]::Match($repoRoot, '^(?<drive>[A-Za-z]):\\(?<rest>.*)$')
if (-not $driveMatch.Success) { throw "BodyRig repo must be on a Windows drive: $repoRoot" }
$drive = $driveMatch.Groups['drive'].Value.ToLowerInvariant()
$rest = $driveMatch.Groups['rest'].Value.Replace('\', '/')
$linuxRepo = "/mnt/$drive/$rest"
$tool = "$linuxRepo/tools/photoreal_exavatar_prepare_rasterizer_ab.py"

Write-Host '============================================================'
Write-Host 'BODYRIG EXAVATAR RASTERIZER CONIC-GRADIENT A/B PREP'
Write-Host "Workspace: $LinuxWorkspaceRoot"
Write-Host 'Original rasterizer mutation: FALSE'
Write-Host 'Production: FALSE'
Write-Host '============================================================'

& wsl.exe -d $Distribution -- /usr/bin/env `
    "PYTHONPATH=$linuxRepo" `
    PYTHONNOUSERSITE=1 `
    FORCE_CUDA=1 `
    CUDA_HOME=/usr/local/cuda-12.4 `
    CUDACXX=/usr/local/cuda-12.4/bin/nvcc `
    $LinuxPython `
    $tool `
    --workspace-root $LinuxWorkspaceRoot

if ($LASTEXITCODE -ne 0) {
    throw "BodyRig rasterizer conic-gradient A/B preparation failed with code $LASTEXITCODE"
}

Write-Host ''
Write-Host 'A/B rasterizer prepared at:'
Write-Host "$LinuxWorkspaceRoot/diagnostics/rasterizer-conic-offdiag-fix"
Write-Host 'Production: FALSE'
