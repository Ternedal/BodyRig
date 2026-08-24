param(
    [Parameter(Mandatory = $true)]
    [string]$PerformerId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId,

    [string]$Name = "",
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [ValidateRange(1, 10)]
    [int]$MaxSources = 10,
    [ValidateRange(1, 1000)]
    [int]$SceneLimit = 200,
    [ValidateRange(1, 10)]
    [int]$MaxSegments = 10,
    [string]$TrackId = "",
    [string]$OutputDir = "",
    [string]$Ffmpeg = "",
    [ValidateRange(0, 2147483647)]
    [int]$SithSeed = 1337,
    [switch]$SkipObservationSelection,
    [switch]$AllowCpu,
    [switch]$KeepPrivateWorkspace
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Set-RequiredEnvironment {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    foreach ($entry in $Values.GetEnumerator()) {
        $name = [string]$entry.Key
        $value = [string]$entry.Value
        if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($value)) {
            throw "Ready-rig environment contains an empty setting."
        }
        Set-Item -Path "Env:$name" -Value $value
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { $BodyRigPython = $venv }
    else { $BodyRigPython = Resolve-CommandPath "python" }
}
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) { throw "BodyRig Python not found." }
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"

if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    $RigSetupReport = [string][Environment]::GetEnvironmentVariable("BODYRIG_RIG_SETUP_REPORT")
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport) -and -not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $candidate = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $RigSetupReport = $candidate }
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    throw "BodyRig rig setup report is required. Run setup-rig-windows.ps1 or pass -RigSetupReport."
}
$RigSetupReport = Resolve-InputFile -Path $RigSetupReport -Label "BodyRig rig setup report"

$validatedRaw = & $BodyRigPython -m bodyrig.rig_setup $RigSetupReport
if ($LASTEXITCODE -ne 0) { throw "BodyRig rig setup report failed live validation." }
try { $rig = $validatedRaw | ConvertFrom-Json }
catch { throw "BodyRig rig setup validator returned unreadable JSON." }
if ([string]$rig.format -ne "bodyrig-rig-setup" -or [int]$rig.version -ne 1) {
    throw "BodyRig rig setup report format/version mismatch after validation."
}

$externalPython = Resolve-InputFile -Path ([string]$rig.recovery.external_python) -Label "Recovery Python from rig setup"
$fourDHumansRepo = [string]$rig.recovery.four_d_humans_repo
if ([string]::IsNullOrWhiteSpace($fourDHumansRepo) -or -not (Test-Path -LiteralPath $fourDHumansRepo -PathType Container)) {
    throw "4D-Humans repository from rig setup is unavailable: $fourDHumansRepo"
}
$fourDHumansRepo = (Resolve-Path -LiteralPath $fourDHumansRepo).Path
$sithReport = Resolve-InputFile -Path ([string]$rig.high_fidelity.setup_report) -Label "SiTH setup report from rig setup"

$sithValidatedRaw = & $BodyRigPython -m bodyrig.sith_setup $sithReport
if ($LASTEXITCODE -ne 0) { throw "Nested SiTH setup report failed live validation." }
try { $sith = $sithValidatedRaw | ConvertFrom-Json }
catch { throw "SiTH setup validator returned unreadable JSON." }

Set-RequiredEnvironment -Values @{
    BODYRIG_RIG_SETUP_REPORT = $RigSetupReport
    BODYRIG_SITH_SETUP_REPORT = $sithReport
    BODYRIG_SITH_DISTRIBUTION = [string]$sith.distribution
    BODYRIG_SITH_REPO = [string]$sith.sith.repository
    BODYRIG_SITH_PYTHON = [string]$sith.sith.python
    BODYRIG_SITH_OPENPOSE_REPO = [string]$sith.openpose.repository
    BODYRIG_SITH_OPENPOSE = [string]$sith.openpose.executable
    BODYRIG_SITH_OPENPOSE_SHA256 = ([string]$sith.openpose.sha256).ToLowerInvariant()
    BODYRIG_SITH_DIFFUSION_MODEL = [string]$sith.diffusion_model.path
    BODYRIG_SITH_DIFFUSION_SHA256 = ([string]$sith.diffusion_model.sha256).ToLowerInvariant()
}

$powerShellExe = Resolve-CommandPath "pwsh"
if ($null -eq $powerShellExe) { $powerShellExe = Resolve-CommandPath "powershell" }
if ($null -eq $powerShellExe) { throw "PowerShell executable not found." }

$readinessScript = Join-Path $repoRoot "check-rig-ready.ps1"
if (-not (Test-Path -LiteralPath $readinessScript -PathType Leaf)) { throw "check-rig-ready.ps1 not found." }
$readinessArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $readinessScript,
    "-RigSetupReport", $RigSetupReport,
    "-BodyRigPython", $BodyRigPython,
    "-ApiKeyEnv", $ApiKeyEnv,
    "-WslExe", $WslExe
)
if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $readinessArgs += @("-StashUrl", $StashUrl) }

Write-Host "BodyRig ready-rig Stash clone"
Write-Host "Rig setup: $RigSetupReport"
Write-Host "Performer id: $PerformerId"
Write-Host "Body id: $BodyId"
Write-Host "Live readiness: checking recovery, SiTH/OpenPose source + binary, diffusion model and Stash"
Write-Host ""
& $powerShellExe @readinessArgs
if ($LASTEXITCODE -ne 0) { throw "BodyRig live rig readiness failed with exit code $LASTEXITCODE; clone not started." }

$cloneScript = Join-Path $repoRoot "clone-body-from-stash.ps1"
if (-not (Test-Path -LiteralPath $cloneScript -PathType Leaf)) { throw "clone-body-from-stash.ps1 not found." }
$cloneArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $cloneScript,
    "-PerformerId", $PerformerId,
    "-ExternalPython", $externalPython,
    "-FourDHumansRepo", $fourDHumansRepo,
    "-BodyId", $BodyId,
    "-BodyRigPython", $BodyRigPython,
    "-ApiKeyEnv", $ApiKeyEnv,
    "-MaxSources", [string]$MaxSources,
    "-SceneLimit", [string]$SceneLimit,
    "-MaxSegments", [string]$MaxSegments,
    "-SithSeed", [string]$SithSeed
)
if (-not [string]::IsNullOrWhiteSpace($Name)) { $cloneArgs += @("-Name", $Name) }
if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $cloneArgs += @("-StashUrl", $StashUrl) }
if (-not [string]::IsNullOrWhiteSpace($TrackId)) { $cloneArgs += @("-TrackId", $TrackId) }
if (-not [string]::IsNullOrWhiteSpace($OutputDir)) { $cloneArgs += @("-OutputDir", $OutputDir) }
if (-not [string]::IsNullOrWhiteSpace($Ffmpeg)) { $cloneArgs += @("-Ffmpeg", $Ffmpeg) }
if ($SkipObservationSelection) { $cloneArgs += "-SkipObservationSelection" }
if ($AllowCpu) { $cloneArgs += "-AllowCpu" }
if ($KeepPrivateWorkspace) { $cloneArgs += "-KeepPrivateWorkspace" }

Write-Host ""
Write-Host "Live readiness: PASS"
Write-Host "Starting Stash clone pipeline."
& $powerShellExe @cloneArgs
if ($LASTEXITCODE -ne 0) { throw "BodyRig Stash clone failed with exit code $LASTEXITCODE" }
exit 0
