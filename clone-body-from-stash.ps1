param(
    [Parameter(Mandatory = $true)]
    [string]$PerformerId,

    [Parameter(Mandatory = $true)]
    [string]$ExternalPython,

    [Parameter(Mandatory = $true)]
    [string]$FourDHumansRepo,

    [Parameter(Mandatory = $true)]
    [string]$IdentityCaptureConfig,

    [Parameter(Mandatory = $true)]
    [string]$FitterConfig,

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
if ($usingObservationSelection) {
    $Ffmpeg = Resolve-Executable -Value $Ffmpeg -Fallback "ffmpeg" -Label "FFmpeg"
    if (-not [string]::IsNullOrWhiteSpace($ObservationAnalyzerConfig)) {
        $ObservationAnalyzerConfig = Resolve-InputFile -Path $ObservationAnalyzerConfig -Label "Observation analyzer config"
    }
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
$cloneOutput = Join-Path $OutputDir "clone"
$observationWorkspace = ""

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

if ($usingObservationSelection -and [string]::IsNullOrWhiteSpace($ObservationAnalyzerConfig)) {
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
        Write-Host "Observation segments: $($segments.Count)"
        Write-Host "Observation selection evidence: $observationSelection"
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
        Copy-Item -LiteralPath $observationSegments -Destination (Join-Path $cloneOutput "bodyrig-observation-segments.json") -Force
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
    Write-Host "Observation segment evidence: $observationSegments"
}
Write-Host "Clone output: $cloneOutput"
exit 0
