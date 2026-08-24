param(
    [string]$RecoveryRoot = "",
    [string]$CondaExe = "",
    [string]$SmplModelPath = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$SithInstallRoot = "",
    [string]$OpenPoseRepo = "",
    [string]$OpenPoseExecutable = "",
    [string]$DiffusionModel = "",
    [string]$SmplxSource = "",
    [string]$SithSetupReport = "",
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$WslExe = "wsl.exe",
    [switch]$RecreateRecoveryEnvironment,
    [switch]$ProvisionOpenPose,
    [switch]$DownloadPublicCheckpoints,
    [switch]$SkipSithDependencyInstall,
    [switch]$PersistUserEnvironment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Resolve-WindowsFile {
    param([string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    if (-not (Test-Path -LiteralPath $Value -PathType Leaf)) { throw "$Label not found: $Value" }
    return (Resolve-Path -LiteralPath $Value).Path
}

function Invoke-SetupScript {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    & $script:PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Set-BodyRigEnvironment {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Values,
        [switch]$Persist
    )
    foreach ($entry in $Values.GetEnumerator()) {
        $name = [string]$entry.Key
        $value = [string]$entry.Value
        if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($value)) {
            throw "BodyRig environment hydration contains an empty name/value."
        }
        Set-Item -Path "Env:$name" -Value $value
        if ($Persist) {
            [Environment]::SetEnvironmentVariable($name, $value, "User")
        }
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$script:PowerShellExe = Resolve-CommandPath "pwsh"
if ($null -eq $script:PowerShellExe) { $script:PowerShellExe = Resolve-CommandPath "powershell" }
if ($null -eq $script:PowerShellExe) { throw "PowerShell executable not found." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { $BodyRigPython = $venv }
    else { $BodyRigPython = Resolve-CommandPath "python" }
}
$BodyRigPython = Resolve-WindowsFile -Value $BodyRigPython -Label "BodyRig Python"

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA) -and ([string]::IsNullOrWhiteSpace($RecoveryRoot) -or [string]::IsNullOrWhiteSpace($SithSetupReport) -or [string]::IsNullOrWhiteSpace($RigSetupReport))) {
    throw "LOCALAPPDATA is unavailable; pass explicit setup/report paths."
}
if ([string]::IsNullOrWhiteSpace($RecoveryRoot)) { $RecoveryRoot = Join-Path $env:LOCALAPPDATA "BodyRig\recovery" }
$RecoveryRoot = [System.IO.Path]::GetFullPath($RecoveryRoot)
if ([string]::IsNullOrWhiteSpace($SithSetupReport)) { $SithSetupReport = Join-Path $env:LOCALAPPDATA "BodyRig\sith\setup-report.json" }
$SithSetupReport = [System.IO.Path]::GetFullPath($SithSetupReport)
if ([string]::IsNullOrWhiteSpace($RigSetupReport)) { $RigSetupReport = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json" }
$RigSetupReport = [System.IO.Path]::GetFullPath($RigSetupReport)

Write-Host "BodyRig full rig bootstrap"
Write-Host "Recovery root: $RecoveryRoot"
Write-Host "SiTH setup report: $SithSetupReport"
Write-Host "Rig setup report: $RigSetupReport"
Write-Host ""

$recoveryScript = Join-Path $repoRoot "setup-recovery-windows.ps1"
if (-not (Test-Path -LiteralPath $recoveryScript -PathType Leaf)) { throw "setup-recovery-windows.ps1 not found." }
$recoveryArgs = @("-Root", $RecoveryRoot)
if (-not [string]::IsNullOrWhiteSpace($CondaExe)) { $recoveryArgs += @("-CondaExe", $CondaExe) }
if (-not [string]::IsNullOrWhiteSpace($SmplModelPath)) { $recoveryArgs += @("-SmplModelPath", $SmplModelPath) }
if ($RecreateRecoveryEnvironment) { $recoveryArgs += "-RecreateEnvironment" }
Invoke-SetupScript -Script $recoveryScript -Arguments $recoveryArgs -Step "BodyRig recovery provisioning"

$recoverySummary = Join-Path $RecoveryRoot "bodyrig-recovery-environment.json"
$recoveryPreflight = Join-Path $RecoveryRoot "bodyrig-recovery-preflight.json"
foreach ($required in @($recoverySummary, $recoveryPreflight)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Recovery provisioning did not produce required evidence: $required" }
}
try { $recovery = Get-Content -LiteralPath $recoverySummary -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Recovery environment summary is unreadable after provisioning." }
if ([string]$recovery.format -ne "bodyrig-recovery-environment" -or [int]$recovery.version -ne 1 -or $recovery.smpl_present -ne $true) {
    throw "Recovery environment summary is not READY."
}

$highScript = Join-Path $repoRoot "setup-high-fidelity-wsl.ps1"
if (-not (Test-Path -LiteralPath $highScript -PathType Leaf)) { throw "setup-high-fidelity-wsl.ps1 not found." }
$highArgs = @("-Distribution", $Distribution, "-ReportPath", $SithSetupReport, "-BodyRigPython", $BodyRigPython, "-WslExe", $WslExe)
if (-not [string]::IsNullOrWhiteSpace($SithInstallRoot)) { $highArgs += @("-SithInstallRoot", $SithInstallRoot) }
if (-not [string]::IsNullOrWhiteSpace($OpenPoseRepo)) { $highArgs += @("-OpenPoseRepo", $OpenPoseRepo) }
if (-not [string]::IsNullOrWhiteSpace($OpenPoseExecutable)) { $highArgs += @("-OpenPoseExecutable", $OpenPoseExecutable) }
if (-not [string]::IsNullOrWhiteSpace($DiffusionModel)) { $highArgs += @("-DiffusionModel", $DiffusionModel) }
if (-not [string]::IsNullOrWhiteSpace($SmplxSource)) { $highArgs += @("-SmplxSource", $SmplxSource) }
if ($ProvisionOpenPose) { $highArgs += "-ProvisionOpenPose" }
if ($DownloadPublicCheckpoints) { $highArgs += "-DownloadPublicCheckpoints" }
if ($SkipSithDependencyInstall) { $highArgs += "-SkipDependencyInstall" }
if ($PersistUserEnvironment) { $highArgs += "-PersistUserEnvironment" }
Invoke-SetupScript -Script $highScript -Arguments $highArgs -Step "BodyRig high-fidelity provisioning"

if (-not (Test-Path -LiteralPath $SithSetupReport -PathType Leaf)) { throw "High-fidelity provisioning did not produce setup report: $SithSetupReport" }
& $BodyRigPython -m bodyrig.sith_setup $SithSetupReport | Out-Null
if ($LASTEXITCODE -ne 0) { throw "High-fidelity setup report failed final validation." }
try { $sithSetup = Get-Content -LiteralPath $SithSetupReport -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "High-fidelity setup report is unreadable after validation." }

$sithEnvironment = @{
    BODYRIG_SITH_SETUP_REPORT = $SithSetupReport
    BODYRIG_SITH_DISTRIBUTION = [string]$sithSetup.distribution
    BODYRIG_SITH_REPO = [string]$sithSetup.sith.repository
    BODYRIG_SITH_PYTHON = [string]$sithSetup.sith.python
    BODYRIG_SITH_OPENPOSE_REPO = [string]$sithSetup.openpose.repository
    BODYRIG_SITH_OPENPOSE = [string]$sithSetup.openpose.executable
    BODYRIG_SITH_OPENPOSE_SHA256 = ([string]$sithSetup.openpose.sha256).ToLowerInvariant()
    BODYRIG_SITH_OPENPOSE_MODELS_SHA256 = ([string]$sithSetup.openpose.models_sha256).ToLowerInvariant()
    BODYRIG_SITH_DIFFUSION_MODEL = [string]$sithSetup.diffusion_model.path
    BODYRIG_SITH_DIFFUSION_SHA256 = ([string]$sithSetup.diffusion_model.sha256).ToLowerInvariant()
}
Set-BodyRigEnvironment -Values $sithEnvironment -Persist:$PersistUserEnvironment

$report = [ordered]@{
    format = "bodyrig-rig-setup"
    version = 1
    recovery = [ordered]@{
        environment_summary = $recoverySummary
        environment_summary_sha256 = Get-Sha256 -Path $recoverySummary
        preflight = $recoveryPreflight
        preflight_sha256 = Get-Sha256 -Path $recoveryPreflight
        external_python = [string]$recovery.external_python
        four_d_humans_repo = [string]$recovery.four_d_humans_repo
        phalp_repo = [string]$recovery.phalp_repo
    }
    high_fidelity = [ordered]@{
        setup_report = $SithSetupReport
        setup_report_sha256 = Get-Sha256 -Path $SithSetupReport
    }
}
$parent = Split-Path -Parent $RigSetupReport
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$temp = "$RigSetupReport.tmp-$([Guid]::NewGuid().ToString('N'))"
$json = $report | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($temp, $json + "`n", [System.Text.UTF8Encoding]::new($false))
& $BodyRigPython -m bodyrig.rig_setup $temp | Out-Null
if ($LASTEXITCODE -ne 0) {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    throw "Combined BodyRig rig setup report failed validation."
}
Move-Item -LiteralPath $temp -Destination $RigSetupReport -Force

Set-BodyRigEnvironment -Values @{ BODYRIG_RIG_SETUP_REPORT = $RigSetupReport } -Persist:$PersistUserEnvironment

Write-Host ""
Write-Host "BodyRig rig bootstrap: READY"
Write-Host "External recovery Python: $([string]$recovery.external_python)"
Write-Host "4D-Humans: $([string]$recovery.four_d_humans_repo)"
Write-Host "PHALP: $([string]$recovery.phalp_repo)"
Write-Host "SiTH setup: $SithSetupReport"
Write-Host "Combined rig setup: $RigSetupReport"
Write-Host ""
Write-Host "Next physical run: configure a fresh local Stash API token in `$env:STASH_API_KEY, then prove auth before clone:"
Write-Host ".\stash-sources.ps1 health"
Write-Host ".\stash-sources.ps1 search '<performer name>' -Limit 10"
Write-Host "Then follow docs\FIRST_PHYSICAL_RUN.md and run clone-body-from-stash-ready.ps1 with the selected performer id."
exit 0
