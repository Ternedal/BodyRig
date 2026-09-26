param(
    [string]$LinuxWorkspaceRoot = '/opt/bodyrig-exavatar/workspaces/bodyrig-42-1d2f658e0fa9',
    [ValidateSet('virtual','colmap')][string]$CameraMode = 'virtual',
    [string]$Distribution = 'Ubuntu-22.04',
    [string]$LinuxPython = '/opt/bodyrig-exavatar/bin/python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$driveMatch = [regex]::Match($repoRoot, '^(?<drive>[A-Za-z]):\\(?<rest>.*)$')
if (-not $driveMatch.Success) {
    throw "BodyRig repo must be on a Windows drive: $repoRoot"
}
$drive = $driveMatch.Groups['drive'].Value.ToLowerInvariant()
$rest = $driveMatch.Groups['rest'].Value.Replace('\', '/')
$linuxRepo = "/mnt/$drive/$rest"

Write-Host '============================================================'
Write-Host 'BODYRIG EXAVATAR DIAGNOSTIC FIT PROMOTION + RESUME'
Write-Host "Workspace: $LinuxWorkspaceRoot"
Write-Host "Camera mode: $CameraMode"
Write-Host 'Reuses stages 1-4: TRUE'
Write-Host 'Promotes finite diagnostic stage 5: TRUE'
Write-Host 'Reruns stages 6-9: TRUE'
Write-Host 'Photoreal authority: FALSE'
Write-Host 'Production: FALSE'
Write-Host '============================================================'

& wsl.exe -d $Distribution -- /usr/bin/env `
    "PYTHONPATH=$linuxRepo" `
    PYTHONNOUSERSITE=1 `
    $LinuxPython `
    -m bodyrig.photoreal_exavatar_fit_promotion_cli `
    --workspace-root $LinuxWorkspaceRoot `
    --camera-mode $CameraMode `
    --python $LinuxPython
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig ExAvatar diagnostic fit promotion failed with code $LASTEXITCODE"
}

Write-Host ''
Write-Host '=== RESUME PREPROCESS FROM PROMOTED FIT ==='
& wsl.exe -d $Distribution -- /usr/bin/env `
    "PYTHONPATH=$linuxRepo" `
    PYTHONNOUSERSITE=1 `
    $LinuxPython `
    -m bodyrig.photoreal_exavatar_preprocess_cli `
    --workspace-root $LinuxWorkspaceRoot `
    --camera-mode $CameraMode `
    --python $LinuxPython `
    --execute
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig ExAvatar downstream preprocess resume failed with code $LASTEXITCODE"
}

Write-Host ''
Write-Host 'BODYRIG EXAVATAR DIAGNOSTIC FIT PROMOTION: COMPLETE'
Write-Host 'Stages 1-4: REUSED'
Write-Host 'Stage 5: PROMOTED FROM FULLY FINITE DIAGNOSTIC FIT'
Write-Host 'Stages 6-9: REBUILT'
Write-Host 'Teacher training: READY TO RETRY'
Write-Host 'Photoreal authority: FALSE'
Write-Host 'Production: FALSE'
