param(
    [Parameter(Mandatory = $true)]
    [string]$PerformerId,

    [Parameter(Mandatory = $true)]
    [string]$ExternalPython,

    [Parameter(Mandatory = $true)]
    [string]$FourDHumansRepo,

    [string]$PhalpRepo = "",
    [string]$RecoveryDistribution = "",
    [string]$IdentityCaptureConfig = "",
    [string]$FitterConfig = "",

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId,

    [string]$Name = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [ValidateRange(1, 10)]
    [int]$MaxSources = 10,
    [ValidateRange(1, 1000)]
    [int]$SceneLimit = 200,
    [string]$ObservationAnalyzerConfig = "",
    [ValidateRange(1, 10)]
    [int]$MaxSegments = 10,
    [string]$Ffmpeg = "",
    [switch]$SkipObservationSelection,
    [string]$TrackId = "",
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$SithDistribution = "",
    [string]$SithRepo = "",
    [string]$SithPython = "",
    [string]$SithOpenPoseRepo = "",
    [string]$SithOpenPose = "",
    [string]$SithOpenPoseSha256 = "",
    [string]$SithOpenPoseModelsSha256 = "",
    [string]$SithDiffusionModel = "",
    [string]$SithDiffusionModelSha256 = "",
    [ValidateRange(0, 2147483647)]
    [int]$SithSeed = 1337,
    [string]$WslExe = "wsl.exe",
    [switch]$AllowCpu,
    [switch]$KeepPrivateWorkspace,
    # Benchmark only: process straight from the Stash media paths (the pre-#1377 behaviour)
    # so local staging can be compared against it. Never use it for a normal clone.
    [switch]$DirectSourceBenchmark,
    # Rig check in minutes: Stash selection + local staging on the real share, timing, cleanup,
    # then stop before observation/recovery/fitting (which take days).
    [switch]$StageOnly
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
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Test-V1Version($Value) {
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }
}

function Resolve-Executable {
    param([string]$Value, [Parameter(Mandatory = $true)][string]$Fallback, [Parameter(Mandatory = $true)][string]$Label)
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        if (Test-Path -LiteralPath $Value -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Value).Path
        }
        $resolvedValue = Resolve-CommandPath $Value
        if ($null -ne $resolvedValue) { return $resolvedValue }
        throw "$Label executable not found: $Value"
    }
    $resolved = Resolve-CommandPath $Fallback
    if ($null -eq $resolved) { throw "$Label executable not found: $Fallback" }
    return $resolved
}

function Resolve-Setting {
    param(
        [string]$Value,
        [Parameter(Mandatory = $true)][string]$EnvironmentName,
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$DefaultValue = ""
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        $Value = [string][Environment]::GetEnvironmentVariable($EnvironmentName)
    }
    if ([string]::IsNullOrWhiteSpace($Value) -and -not [string]::IsNullOrWhiteSpace($DefaultValue)) {
        $Value = $DefaultValue
    }
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Label is required via parameter or $EnvironmentName."
    }
    return $Value.Trim()
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Remove-StaleSnapshotsFromKilledRuns {
    # Codex P2 4398060821: every run gets a new OutputDir, so a killed run's snapshot sits in a
    # sibling directory. Remove it only when (a) that run's lock can be taken, i.e. no process
    # holds it any more, and (b) bodyrig.stage_stash_sources finds its ownership marker.
    # Run outputs other than the disposable snapshot are never touched.
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$Current)
    foreach ($dir in @(Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue)) {
        if ($dir.FullName -eq $Current) { continue }
        $lockPath = Join-Path $dir.FullName "bodyrig-run.lock"
        $snapshot = Join-Path $dir.FullName "local-source-snapshot"
        if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) { continue }
        $hasSnapshot = (Test-Path -LiteralPath $snapshot -PathType Container) -or
            @(Get-ChildItem -LiteralPath $dir.FullName -Directory -Filter ".bodyrig-staging-*" -Force -ErrorAction SilentlyContinue).Count -gt 0
        if (-not $hasSnapshot) { continue }
        try {
            $probe = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        } catch {
            Write-Host "Skipping $($dir.Name): its run is still active."
            continue
        }
        try {
            & $BodyRigPython -m bodyrig.stage_stash_sources --cleanup-stale --destination $snapshot
            if ($LASTEXITCODE -ne 0) { Write-Warning "Could not clean the stale snapshot in $($dir.Name) (exit $LASTEXITCODE); left in place." }
        } finally {
            $probe.Dispose()
        }
    }
}

function Convert-WindowsPathToWsl {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not $usingWslRecovery) { throw "WSL path conversion requested without WSL recovery transport." }

    # wsl.exe can consume single backslashes while forwarding direct Linux argv.
    # Match setup-recovery-windows.ps1: escape once so wslpath sees C:\Users\...
    # intact instead of C:Users... .
    $escapedPath = $Path.Replace('\', '\\')
    $raw = @(& $WslExe -d $RecoveryDistribution -- wslpath -a -u $escapedPath)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$raw[0])) {
        throw "Could not translate BodyRig bridge path into WSL: $Path"
    }
    return ([string]$raw[0]).Trim()
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    $StashUrl = [string]$env:STASH_URL
}
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    throw "Stash URL is required via -StashUrl or STASH_URL."
}
if ([string]::IsNullOrWhiteSpace($ApiKeyEnv)) {
    throw "-ApiKeyEnv must name the environment variable containing the Stash API key."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $BodyRigPython = $venvPython
    } else {
        $BodyRigPython = Resolve-CommandPath "python"
    }
}
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    throw "BodyRig Python not found. Create .venv or pass -BodyRigPython."
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"

$usingWslRecovery = -not [string]::IsNullOrWhiteSpace($RecoveryDistribution)
if ($usingWslRecovery) {
    $RecoveryDistribution = $RecoveryDistribution.Trim()
    foreach ($linuxSetting in @(
        @{ Label = "External recovery Python"; Value = $ExternalPython },
        @{ Label = "4D-Humans repository"; Value = $FourDHumansRepo },
        @{ Label = "PHALP repository"; Value = $PhalpRepo }
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$linuxSetting.Value) -or -not ([string]$linuxSetting.Value).StartsWith("/")) {
            throw "$($linuxSetting.Label) must be an absolute Linux path for WSL recovery."
        }
    }
    $ExternalPython = $ExternalPython.Trim()
    $FourDHumansRepo = $FourDHumansRepo.TrimEnd("/")
    $PhalpRepo = $PhalpRepo.TrimEnd("/")
    $WslExe = Resolve-Executable -Value $WslExe -Fallback "wsl.exe" -Label "WSL"
} else {
    $ExternalPython = Resolve-InputFile -Path $ExternalPython -Label "External recovery Python"
}

$powerShellExe = Resolve-CommandPath "pwsh"
if ($null -eq $powerShellExe) {
    $powerShellExe = Resolve-CommandPath "powershell"
}
if ($null -eq $powerShellExe) {
    throw "PowerShell executable not found."
}

$usingObservationSelection = -not $SkipObservationSelection
$usingBuiltInObservationAnalyzer = $usingObservationSelection -and [string]::IsNullOrWhiteSpace($ObservationAnalyzerConfig)
$usingBuiltInIdentityCapture = [string]::IsNullOrWhiteSpace($IdentityCaptureConfig)
$usingBuiltInFitter = [string]::IsNullOrWhiteSpace($FitterConfig)

if (-not $usingBuiltInIdentityCapture) {
    $IdentityCaptureConfig = Resolve-InputFile -Path $IdentityCaptureConfig -Label "Identity capture config"
}
if ($usingBuiltInIdentityCapture) {
    $identityPreflightArgs = @(
        "-m", "bodyrig.identity_capture_preflight",
        "--external-python", $ExternalPython
    )
    if ($usingWslRecovery) {
        $identityPreflightArgs += @("--distribution", $RecoveryDistribution, "--wsl-exe", $WslExe)
    }
    Invoke-Checked -Executable $BodyRigPython -Arguments $identityPreflightArgs -Step "Built-in identity capture preflight"
}

if (-not $usingBuiltInFitter) {
    $FitterConfig = Resolve-InputFile -Path $FitterConfig -Label "High-fidelity fitter config"
} else {
    $SithDistribution = Resolve-Setting -Value $SithDistribution -EnvironmentName "BODYRIG_SITH_DISTRIBUTION" -Label "SiTH WSL distribution" -DefaultValue "Ubuntu-22.04"
    $SithRepo = Resolve-Setting -Value $SithRepo -EnvironmentName "BODYRIG_SITH_REPO" -Label "SiTH repository"
    $SithPython = Resolve-Setting -Value $SithPython -EnvironmentName "BODYRIG_SITH_PYTHON" -Label "SiTH Python"
    $SithOpenPoseRepo = Resolve-Setting -Value $SithOpenPoseRepo -EnvironmentName "BODYRIG_SITH_OPENPOSE_REPO" -Label "SiTH OpenPose repository"
    $SithOpenPose = Resolve-Setting -Value $SithOpenPose -EnvironmentName "BODYRIG_SITH_OPENPOSE" -Label "SiTH OpenPose executable"
    $SithOpenPoseSha256 = Resolve-Setting -Value $SithOpenPoseSha256 -EnvironmentName "BODYRIG_SITH_OPENPOSE_SHA256" -Label "SiTH OpenPose executable SHA-256"
    $SithOpenPoseModelsSha256 = Resolve-Setting -Value $SithOpenPoseModelsSha256 -EnvironmentName "BODYRIG_SITH_OPENPOSE_MODELS_SHA256" -Label "SiTH OpenPose model tree SHA-256"
    $SithDiffusionModel = Resolve-Setting -Value $SithDiffusionModel -EnvironmentName "BODYRIG_SITH_DIFFUSION_MODEL" -Label "SiTH diffusion model"
    $SithDiffusionModelSha256 = Resolve-Setting -Value $SithDiffusionModelSha256 -EnvironmentName "BODYRIG_SITH_DIFFUSION_SHA256" -Label "SiTH diffusion model SHA-256"

    $SithOpenPoseSha256 = $SithOpenPoseSha256.ToLowerInvariant()
    $SithOpenPoseModelsSha256 = $SithOpenPoseModelsSha256.ToLowerInvariant()
    $SithDiffusionModelSha256 = $SithDiffusionModelSha256.ToLowerInvariant()
    foreach ($hashSetting in @(
        @{ Label = "SiTH OpenPose executable SHA-256"; Value = $SithOpenPoseSha256 },
        @{ Label = "SiTH OpenPose model tree SHA-256"; Value = $SithOpenPoseModelsSha256 },
        @{ Label = "SiTH diffusion model SHA-256"; Value = $SithDiffusionModelSha256 }
    )) {
        if ([string]$hashSetting.Value -notmatch '^[0-9a-f]{64}$') {
            throw "$($hashSetting.Label) must be exactly 64 hexadecimal characters."
        }
    }
    foreach ($linuxSetting in @(
        @{ Label = "SiTH repository"; Value = $SithRepo },
        @{ Label = "SiTH Python"; Value = $SithPython },
        @{ Label = "SiTH OpenPose repository"; Value = $SithOpenPoseRepo },
        @{ Label = "SiTH OpenPose executable"; Value = $SithOpenPose },
        @{ Label = "SiTH diffusion model"; Value = $SithDiffusionModel }
    )) {
        if (-not ([string]$linuxSetting.Value).StartsWith("/")) {
            throw "$($linuxSetting.Label) must be an absolute Linux path."
        }
    }
    $SithOpenPoseRepo = $SithOpenPoseRepo.TrimEnd("/")
    if (-not $usingWslRecovery) {
        $WslExe = Resolve-Executable -Value $WslExe -Fallback "wsl.exe" -Label "WSL"
    }

    $sithPreflightArgs = @(
        "-m", "bodyrig.sith_preflight",
        "--distribution", $SithDistribution,
        "--repo", $SithRepo,
        "--python", $SithPython,
        "--openpose", $SithOpenPose,
        "--openpose-repo", $SithOpenPoseRepo,
        "--wsl-exe", $WslExe
    )
    Invoke-Checked -Executable $BodyRigPython -Arguments $sithPreflightArgs -Step "Built-in SiTH fitter preflight"

    $openPoseRaw = & $BodyRigPython -m bodyrig.wsl_file_digest --distribution $SithDistribution --python $SithPython --path $SithOpenPose --wsl-exe $WslExe
    if ($LASTEXITCODE -ne 0) {
        throw "SiTH OpenPose executable digest failed with exit code $LASTEXITCODE"
    }
    try {
        $openPoseDigest = $openPoseRaw | ConvertFrom-Json
    } catch {
        throw "SiTH OpenPose executable digest returned unreadable JSON."
    }
    if ([string]$openPoseDigest.sha256 -ne $SithOpenPoseSha256) {
        throw "SiTH OpenPose executable SHA-256 mismatch: expected $SithOpenPoseSha256, got $([string]$openPoseDigest.sha256)"
    }

    $openPoseModelsRaw = & $BodyRigPython -m bodyrig.wsl_tree_digest --distribution $SithDistribution --python $SithPython --path "$SithOpenPoseRepo/models" --wsl-exe $WslExe
    if ($LASTEXITCODE -ne 0) {
        throw "SiTH OpenPose model tree digest failed with exit code $LASTEXITCODE"
    }
    try {
        $openPoseModelsDigest = $openPoseModelsRaw | ConvertFrom-Json
    } catch {
        throw "SiTH OpenPose model tree digest returned unreadable JSON."
    }
    if ([string]$openPoseModelsDigest.sha256 -ne $SithOpenPoseModelsSha256) {
        throw "SiTH OpenPose model tree SHA-256 mismatch: expected $SithOpenPoseModelsSha256, got $([string]$openPoseModelsDigest.sha256)"
    }

    $digestArgs = @(
        "-m", "bodyrig.sith_model",
        "--distribution", $SithDistribution,
        "--python", $SithPython,
        "--model-path", $SithDiffusionModel,
        "--wsl-exe", $WslExe
    )
    $digestRaw = & $BodyRigPython @digestArgs
    if ($LASTEXITCODE -ne 0) {
        throw "SiTH diffusion model digest failed with exit code $LASTEXITCODE"
    }
    try {
        $digest = $digestRaw | ConvertFrom-Json
    } catch {
        throw "SiTH diffusion model digest returned unreadable JSON."
    }
    if ([string]$digest.sha256 -ne $SithDiffusionModelSha256) {
        throw "SiTH diffusion model SHA-256 mismatch: expected $SithDiffusionModelSha256, got $([string]$digest.sha256)"
    }
}

if ($usingObservationSelection) {
    $Ffmpeg = Resolve-Executable -Value $Ffmpeg -Fallback "ffmpeg" -Label "FFmpeg"
    if (-not $usingBuiltInObservationAnalyzer) {
        $ObservationAnalyzerConfig = Resolve-InputFile -Path $ObservationAnalyzerConfig -Label "Observation analyzer config"
    }

    $observationPreflightArgs = @(
        "-m", "bodyrig.observation_preflight",
        "--external-python", $ExternalPython,
        "--ffmpeg", $Ffmpeg
    )
    if (-not $usingBuiltInObservationAnalyzer) {
        $observationPreflightArgs += "--ffmpeg-only"
    } elseif ($usingWslRecovery) {
        $observationPreflightArgs += @("--distribution", $RecoveryDistribution, "--wsl-exe", $WslExe)
    }
    Invoke-Checked -Executable $BodyRigPython -Arguments $observationPreflightArgs -Step "Observation selection preflight"
}

$stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path (Get-Location).Path "bodyrig-stash-$BodyId-$stamp"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) {
    throw "Stash clone output directory already exists; refusing cross-run reuse: $OutputDir"
}
New-Item -ItemType Directory -Path $OutputDir | Out-Null
# Held for the whole run (FileShare.None) and released by the OS if the process dies.
# A later launch that can open it knows this run is no longer alive.
$runLock = [System.IO.File]::Open((Join-Path $OutputDir "bodyrig-run.lock"), [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)

$sourceManifest = Join-Path $OutputDir "bodyrig-stash-source-manifest.json"
$observationSelection = Join-Path $OutputDir "bodyrig-observation-selection.json"
$observationSegments = Join-Path $OutputDir "bodyrig-observation-segments.json"
$observationEvidence = Join-Path $OutputDir "bodyrig-observation-evidence.json"
$cloneOutput = Join-Path $OutputDir "clone"
$observationWorkspace = ""

if ($usingBuiltInIdentityCapture) {
    $identityBridge = Resolve-InputFile -Path (Join-Path $repoRoot "bodyrig\bridges\opencv_identity_capture.py") -Label "Built-in OpenCV identity capture adapter"
    $IdentityCaptureConfig = Join-Path $OutputDir "bodyrig-identity-capture-config.json"
    if ($usingWslRecovery) {
        $identityBridgeWsl = Convert-WindowsPathToWsl -Path $identityBridge
        $identityCommand = @(
            $BodyRigPython,
            "-m", "bodyrig.wsl_adapter_bridge",
            "--distribution", $RecoveryDistribution,
            "--wsl-exe", $WslExe,
            "--",
            $ExternalPython,
            $identityBridgeWsl
        )
    } else {
        $identityCommand = @($ExternalPython, $identityBridge)
    }
    $builtInIdentityConfig = [ordered]@{
        format = "bodyrig-identity-capture-config"
        version = 1
        adapter = "opencv-identity-rgba"
        revision = "1"
        command = $identityCommand
        timeout_seconds = 3600
    }
    $builtInIdentityConfig | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $IdentityCaptureConfig -Encoding UTF8
}

if ($usingBuiltInFitter) {
    $FitterConfig = Join-Path $OutputDir "bodyrig-sith-fitter-config.json"
    $builtInFitterConfig = [ordered]@{
        format = "bodyrig-external-fitter-config"
        version = 1
        adapter = "sith-smplx-vrm"
        revision = "1"
        command = @(
            $BodyRigPython,
            "-m", "bodyrig.sith_fitter_orchestrator",
            "--distribution", $SithDistribution,
            "--sith-repo", $SithRepo,
            "--sith-python", $SithPython,
            "--openpose", $SithOpenPose,
            "--diffusion-model", $SithDiffusionModel,
            "--diffusion-model-sha256", $SithDiffusionModelSha256,
            "--seed", [string]$SithSeed,
            "--wsl-exe", $WslExe
        )
        capabilities = [ordered]@{
            visual_identity = $true
            textures = $true
            hair = $false
            clothing = $false
        }
        timeout_seconds = 86400
    }
    $builtInFitterConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $FitterConfig -Encoding UTF8
}

$selectArgs = @(
    "-m", "bodyrig.stash_cli", "select",
    "--performer-id", $PerformerId,
    "--scene-limit", [string]$SceneLimit,
    "--max-sources", [string]$MaxSources,
    "--out", $sourceManifest,
    "--url", $StashUrl,
    "--api-key-env", $ApiKeyEnv
)
if ($usingObservationSelection) {
    $selectArgs += @("--ffmpeg", $Ffmpeg)
} else {
    $selectArgs += "--skip-decode-probe"
}
Invoke-Checked -Executable $BodyRigPython -Arguments $selectArgs -Step "Stash performer source selection"

try {
    $manifest = Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    throw "BodyRig Stash source manifest is unreadable after selection."
}
if ([string]$manifest.format -ne "bodyrig-stash-source-manifest" -or -not (Test-V1Version $manifest.version)) {
    throw "BodyRig Stash source manifest format/version mismatch."
}
if ([string]$manifest.performer.id -ne $PerformerId) {
    throw "Stash source manifest performer id mismatch."
}
$selected = @($manifest.selected)
if ($selected.Count -lt 1 -or $selected.Count -gt 10) {
    throw "Stash source selection returned an invalid source count."
}
if ([string]::IsNullOrWhiteSpace($Name)) {
    $Name = [string]$manifest.performer.name
}
if ([string]::IsNullOrWhiteSpace($Name) -or $Name.Length -gt 160) {
    throw "BodyRig display name from Stash is invalid; pass -Name explicitly."
}

# Phase 1 (Stash and the media share are needed): selection above, staging below.
# Phase 2 (offline): everything after staging reads only the local snapshot.
# Cover staging and all subsequent setup, observation and clone steps with cleanup.
$localSnapshot = Join-Path $OutputDir "local-source-snapshot"
$stagingTiming = Join-Path $OutputDir "bodyrig-staging-timing.json"
$previousOffline = $env:BODYRIG_STASH_OFFLINE
$previousApiKey = [Environment]::GetEnvironmentVariable($ApiKeyEnv, "Process")
$processingTimer = $null
# Initialised before the try: finally reads it under Set-StrictMode (Codex P2 4398060811).
$success = $false
try {
# A run killed earlier (power loss, kill -9) can leave its marked snapshot in its own OutputDir.
Remove-StaleSnapshotsFromKilledRuns -Root (Split-Path -Parent $OutputDir) -Current $OutputDir
if ($DirectSourceBenchmark) {
    Write-Warning "DirectSourceBenchmark: processing straight from Stash media paths (benchmark only; no local snapshot)."
    [ordered]@{ format = "bodyrig-staging-timing"; version = 1; staged = $false; files = $selected.Count } |
        ConvertTo-Json | Set-Content -LiteralPath $stagingTiming -Encoding UTF8
} else {
    # Snapshot every selected original before any expensive observation/recovery work.
    # All subsequent stages consume only snapshot paths, never Stash media paths.
    $stageArgs = @("-m", "bodyrig.stage_stash_sources", "--manifest", $sourceManifest, "--destination", $localSnapshot, "--timing-out", $stagingTiming)
    Invoke-Checked -Executable $BodyRigPython -Arguments $stageArgs -Step "Copy and SHA256-verify Stash originals locally"
    $sourceManifest = Join-Path $localSnapshot "bodyrig-stash-source-manifest.json"
    $manifest = Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8 | ConvertFrom-Json
    $selected = @($manifest.selected)
}
# From here on Stash is not needed: any Stash call fails closed (stash_source), and the
# API key is removed from this process. Both are restored in the finally block below.
$env:BODYRIG_STASH_OFFLINE = "1"
Remove-Item -LiteralPath ("Env:$ApiKeyEnv") -ErrorAction SilentlyContinue
if ($DirectSourceBenchmark) {
    Write-Host "Stash API no longer required; the media share is still read directly (benchmark mode)."
} else {
    Write-Host "Stash source snapshot complete; Stash and source shares are no longer required."
}
$processingTimer = [System.Diagnostics.Stopwatch]::StartNew()
if ($StageOnly) {
    if ($DirectSourceBenchmark) { throw "-StageOnly and -DirectSourceBenchmark cannot be combined." }
    Write-Host "StageOnly: Stash selection and local staging verified; observation, recovery and fitting are skipped."
    $success = $true
    exit 0  # finally still runs: records timing, restores the environment and deletes the snapshot
}

if ($usingBuiltInObservationAnalyzer) {
    $bridge = Resolve-InputFile -Path (Join-Path $repoRoot "bodyrig\bridges\opencv_observation_analyzer.py") -Label "Built-in OpenCV observation analyzer"
    $ObservationAnalyzerConfig = Join-Path $OutputDir "bodyrig-observation-analyzer-config.json"
    if ($usingWslRecovery) {
        $bridgeWsl = Convert-WindowsPathToWsl -Path $bridge
        $observationCommand = @(
            $BodyRigPython,
            "-m", "bodyrig.wsl_adapter_bridge",
            "--distribution", $RecoveryDistribution,
            "--wsl-exe", $WslExe,
            "--",
            $ExternalPython,
            $bridgeWsl,
            "--bodyrig-stash-manifest",
            $sourceManifest
        )
    } else {
        $observationCommand = @(
            $ExternalPython,
            $bridge,
            "--bodyrig-stash-manifest",
            $sourceManifest
        )
    }
    $builtInConfig = [ordered]@{
        format = "bodyrig-observation-analyzer-config"
        version = 1
        adapter = "opencv-hog-haar"
        revision = "1"
        command = $observationCommand
        timeout_seconds = 7200
    }
    $builtInConfig | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ObservationAnalyzerConfig -Encoding UTF8
}

Write-Host "BodyRig Stash clone"
Write-Host "Performer: $Name [$PerformerId]"
Write-Host "Selected source files: $($selected.Count)"
foreach ($item in $selected) {
    Write-Host ("  {0:N1} | {1}x{2} | performers={3} | {4}" -f [double]$item.score, [int]$item.width, [int]$item.height, [int]$item.performer_count, [string]$item.scene_title)
}
if ($usingObservationSelection) {
    Write-Host "Observation selection: enabled"
} else {
    Write-Host "Observation selection: SKIPPED by explicit request"
}
if ($usingBuiltInIdentityCapture) {
    Write-Host "Identity capture: built-in opencv-identity-rgba v1"
} else {
    Write-Host "Identity capture: custom config"
}
if ($usingBuiltInFitter) {
    Write-Host "High-fidelity fitter: built-in sith-smplx-vrm v1 (OpenPose source/binary/models + diffusion bytes verified; garments external)"
} else {
    Write-Host "High-fidelity fitter: custom config"
}
if ($usingWslRecovery) {
    Write-Host "Recovery transport: WSL $RecoveryDistribution"
}
Write-Host ""

$success = $false
try {
    if ($usingObservationSelection) {
        $privateBase = [string]$env:LOCALAPPDATA
        if ([string]::IsNullOrWhiteSpace($privateBase)) {
            $privateBase = [System.IO.Path]::GetTempPath()
        }
        $observationWorkspace = Join-Path $privateBase ("BodyRig\observation-workspaces\$BodyId-$stamp-" + [Guid]::NewGuid().ToString("N"))
        $observationWorkspace = [System.IO.Path]::GetFullPath($observationWorkspace)
        if (Test-Path -LiteralPath $observationWorkspace) {
            throw "Observation workspace already exists; refusing cross-run reuse."
        }

        $observationArgs = @(
            "-m", "bodyrig.observation_cli",
            $sourceManifest,
            "--config", $ObservationAnalyzerConfig,
            "--workspace", $observationWorkspace,
            "--selection-out", $observationSelection,
            "--segments-out", $observationSegments,
            "--max-segments", [string]$MaxSegments,
            "--ffmpeg", $Ffmpeg
        )
        Invoke-Checked -Executable $BodyRigPython -Arguments $observationArgs -Step "Stash frame/segment observation selection"

        try {
            $segmentManifest = Get-Content -LiteralPath $observationSegments -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            throw "BodyRig observation segment manifest is unreadable after selection."
        }
        if ([string]$segmentManifest.format -ne "bodyrig-observation-segments" -or -not (Test-V1Version $segmentManifest.version)) {
            throw "BodyRig observation segment manifest format/version mismatch."
        }
        $segments = @($segmentManifest.segments)
        if ($segments.Count -lt 1 -or $segments.Count -gt 10) {
            throw "BodyRig observation selection returned an invalid segment count."
        }

        $evidenceArgs = @(
            "-m", "bodyrig.observation_evidence",
            "--source-manifest", $sourceManifest,
            "--selection", $observationSelection,
            "--segments", $observationSegments,
            "--out", $observationEvidence
        )
        Invoke-Checked -Executable $BodyRigPython -Arguments $evidenceArgs -Step "Observation evidence binding"

        Write-Host "Observation segments: $($segments.Count)"
        Write-Host "Observation selection evidence: $observationSelection"
        Write-Host "Observation path-free evidence: $observationEvidence"
        Write-Host ""
    }

    $cloneScript = Join-Path $repoRoot "clone-body.ps1"
    if (-not (Test-Path -LiteralPath $cloneScript -PathType Leaf)) {
        throw "clone-body.ps1 not found: $cloneScript"
    }

    $cloneArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $cloneScript,
        "-SourceManifest", $sourceManifest,
        "-ExternalPython", $ExternalPython,
        "-FourDHumansRepo", $FourDHumansRepo,
        "-IdentityCaptureConfig", $IdentityCaptureConfig,
        "-FitterConfig", $FitterConfig,
        "-BodyId", $BodyId,
        "-Name", $Name,
        "-OutputDir", $cloneOutput,
        "-BodyRigPython", $BodyRigPython
    )
    if ($usingWslRecovery) {
        $cloneArgs += @(
            "-PhalpRepo", $PhalpRepo,
            "-RecoveryDistribution", $RecoveryDistribution,
            "-WslExe", $WslExe
        )
    }
    if ($usingObservationSelection) {
        $cloneArgs += @("-SourceOverrideManifest", $observationSegments)
    }
    if (-not [string]::IsNullOrWhiteSpace($TrackId)) {
        $cloneArgs += @("-TrackId", $TrackId)
    }
    if ($AllowCpu) { $cloneArgs += "-AllowCpu" }
    if ($KeepPrivateWorkspace) { $cloneArgs += "-KeepPrivateWorkspace" }

    Invoke-Checked -Executable $powerShellExe -Arguments $cloneArgs -Step "BodyRig clone pipeline"

    Copy-Item -LiteralPath $sourceManifest -Destination (Join-Path $cloneOutput "bodyrig-stash-source-manifest.json") -Force
    if ($usingObservationSelection) {
        Copy-Item -LiteralPath $observationSelection -Destination (Join-Path $cloneOutput "bodyrig-observation-selection.json") -Force
        Copy-Item -LiteralPath $observationEvidence -Destination (Join-Path $cloneOutput "bodyrig-observation-evidence.json") -Force
    }
    $success = $true
} finally {
    if ($usingObservationSelection -and -not [string]::IsNullOrWhiteSpace($observationWorkspace) -and (Test-Path -LiteralPath $observationWorkspace -PathType Container)) {
        if ($KeepPrivateWorkspace) {
            Write-Host "Observation workspace retained by explicit request: $observationWorkspace"
        } else {
            Remove-Item -LiteralPath $observationWorkspace -Recurse -Force -ErrorAction SilentlyContinue
            if ($success) {
                Write-Host "Private observation workspace deleted after successful clone."
            } else {
                Write-Host "Private observation workspace deleted after failed clone."
            }
        }
    }
}

if (-not $success) { exit 1 }
Write-Host ""
Write-Host "BodyRig Stash clone: PASS"
Write-Host "Performer: $Name [$PerformerId]"
Write-Host "Source manifest copy: $(Join-Path $cloneOutput 'bodyrig-stash-source-manifest.json')"
if ($usingObservationSelection) {
    Write-Host "Observation selection: $observationSelection"
    Write-Host "Observation path-free evidence: $observationEvidence"
}
Write-Host "Clone output: $cloneOutput"
} finally {
    try {
        if ($null -ne $processingTimer -and (Test-Path -LiteralPath $stagingTiming -PathType Leaf)) {
            # Processing time is recorded next to the copy/verify time. Counts and seconds only, no paths.
            $processingTimer.Stop()
            $timing = Get-Content -LiteralPath $stagingTiming -Raw -Encoding UTF8 | ConvertFrom-Json
            $timing | Add-Member -NotePropertyName processing_seconds -NotePropertyValue ([math]::Round($processingTimer.Elapsed.TotalSeconds, 3)) -Force
            $timing | Add-Member -NotePropertyName processing_succeeded -NotePropertyValue ([bool]$success) -Force
            $timing | Add-Member -NotePropertyName stage_only -NotePropertyValue ([bool]$StageOnly) -Force
            $timing | ConvertTo-Json | Set-Content -LiteralPath $stagingTiming -Encoding UTF8
            Write-Host "Staging/processing timing: $stagingTiming"
        }
    } catch {
        # Timing is diagnostics; it must never block the cleanup below.
        Write-Warning "Could not record staging timing: $($_.Exception.Message)"
    }
    try {
        # Restore this session's environment: the script may have been run in-process.
        if ($null -eq $previousOffline) { Remove-Item -LiteralPath "Env:BODYRIG_STASH_OFFLINE" -ErrorAction SilentlyContinue } else { $env:BODYRIG_STASH_OFFLINE = $previousOffline }
        if ($null -ne $previousApiKey) { [Environment]::SetEnvironmentVariable($ApiKeyEnv, $previousApiKey, "Process") }
        # Only the local disposable snapshot is removed; never the original Stash media.
        if (Test-Path -LiteralPath $localSnapshot -PathType Container) {
            Remove-Item -LiteralPath $localSnapshot -Recurse -Force -ErrorAction Stop
            Write-Host "Temporary local Stash source snapshot deleted."
        }
    } finally {
        $runLock.Dispose()
    }
}
exit 0