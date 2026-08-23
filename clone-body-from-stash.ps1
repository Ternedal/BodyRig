param(
    [Parameter(Mandatory = $true)]
    [string]$PerformerId,

    [Parameter(Mandatory = $true)]
    [string]$ExternalPython,

    [Parameter(Mandatory = $true)]
    [string]$FourDHumansRepo,

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
    [string]$SithOpenPose = "",
    [string]$SithDiffusionModel = "",
    [string]$SithDiffusionModelSha256 = "",
    [ValidateRange(0, 2147483647)]
    [int]$SithSeed = 1337,
    [string]$WslExe = "wsl.exe",
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
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
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

$ExternalPython = Resolve-InputFile -Path $ExternalPython -Label "External recovery Python"
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
    Invoke-Checked -Executable $BodyRigPython -Arguments $identityPreflightArgs -Step "Built-in identity capture preflight"
}

if (-not $usingBuiltInFitter) {
    $FitterConfig = Resolve-InputFile -Path $FitterConfig -Label "High-fidelity fitter config"
} else {
    $SithDistribution = Resolve-Setting -Value $SithDistribution -EnvironmentName "BODYRIG_SITH_DISTRIBUTION" -Label "SiTH WSL distribution" -DefaultValue "Ubuntu-22.04"
    $SithRepo = Resolve-Setting -Value $SithRepo -EnvironmentName "BODYRIG_SITH_REPO" -Label "SiTH repository"
    $SithPython = Resolve-Setting -Value $SithPython -EnvironmentName "BODYRIG_SITH_PYTHON" -Label "SiTH Python"
    $SithOpenPose = Resolve-Setting -Value $SithOpenPose -EnvironmentName "BODYRIG_SITH_OPENPOSE" -Label "SiTH OpenPose executable"
    $SithDiffusionModel = Resolve-Setting -Value $SithDiffusionModel -EnvironmentName "BODYRIG_SITH_DIFFUSION_MODEL" -Label "SiTH diffusion model"
    $SithDiffusionModelSha256 = Resolve-Setting -Value $SithDiffusionModelSha256 -EnvironmentName "BODYRIG_SITH_DIFFUSION_SHA256" -Label "SiTH diffusion model SHA-256"
    $SithDiffusionModelSha256 = $SithDiffusionModelSha256.ToLowerInvariant()
    if ($SithDiffusionModelSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "SiTH diffusion model SHA-256 must be exactly 64 hexadecimal characters."
    }
    foreach ($linuxSetting in @(
        @{ Label = "SiTH repository"; Value = $SithRepo },
        @{ Label = "SiTH Python"; Value = $SithPython },
        @{ Label = "SiTH OpenPose executable"; Value = $SithOpenPose },
        @{ Label = "SiTH diffusion model"; Value = $SithDiffusionModel }
    )) {
        if (-not ([string]$linuxSetting.Value).StartsWith("/")) {
            throw "$($linuxSetting.Label) must be an absolute Linux path."
        }
    }
    $WslExe = Resolve-Executable -Value $WslExe -Fallback "wsl.exe" -Label "WSL"

    $sithPreflightArgs = @(
        "-m", "bodyrig.sith_preflight",
        "--distribution", $SithDistribution,
        "--repo", $SithRepo,
        "--python", $SithPython,
        "--openpose", $SithOpenPose,
        "--wsl-exe", $WslExe
    )
    Invoke-Checked -Executable $BodyRigPython -Arguments $sithPreflightArgs -Step "Built-in SiTH fitter preflight"

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

$sourceManifest = Join-Path $OutputDir "bodyrig-stash-source-manifest.json"
$observationSelection = Join-Path $OutputDir "bodyrig-observation-selection.json"
$observationSegments = Join-Path $OutputDir "bodyrig-observation-segments.json"
$observationEvidence = Join-Path $OutputDir "bodyrig-observation-evidence.json"
$cloneOutput = Join-Path $OutputDir "clone"
$observationWorkspace = ""

if ($usingBuiltInIdentityCapture) {
    $identityBridge = Resolve-InputFile -Path (Join-Path $repoRoot "bodyrig\bridges\opencv_identity_capture.py") -Label "Built-in OpenCV identity capture adapter"
    $IdentityCaptureConfig = Join-Path $OutputDir "bodyrig-identity-capture-config.json"
    $builtInIdentityConfig = [ordered]@{
        format = "bodyrig-identity-capture-config"
        version = 1
        adapter = "opencv-identity-rgba"
        revision = "1"
        command = @(
            $ExternalPython,
            $identityBridge
        )
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
            clothing = $true
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
Invoke-Checked -Executable $BodyRigPython -Arguments $selectArgs -Step "Stash performer source selection"

try {
    $manifest = Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    throw "BodyRig Stash source manifest is unreadable after selection."
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

if ($usingBuiltInObservationAnalyzer) {
    $bridge = Resolve-InputFile -Path (Join-Path $repoRoot "bodyrig\bridges\opencv_observation_analyzer.py") -Label "Built-in OpenCV observation analyzer"
    $ObservationAnalyzerConfig = Join-Path $OutputDir "bodyrig-observation-analyzer-config.json"
    $builtInConfig = [ordered]@{
        format = "bodyrig-observation-analyzer-config"
        version = 1
        adapter = "opencv-hog-haar"
        revision = "1"
        command = @(
            $ExternalPython,
            $bridge,
            "--bodyrig-stash-manifest",
            $sourceManifest
        )
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
    Write-Host "High-fidelity fitter: built-in sith-smplx-vrm v1"
} else {
    Write-Host "High-fidelity fitter: custom config"
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
        if ([string]$segmentManifest.format -ne "bodyrig-observation-segments" -or [int]$segmentManifest.version -ne 1) {
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
Write-Host "Source manifest: $sourceManifest"
if ($usingObservationSelection) {
    Write-Host "Observation selection: $observationSelection"
    Write-Host "Observation path-free evidence: $observationEvidence"
}
Write-Host "Clone output: $cloneOutput"
exit 0
