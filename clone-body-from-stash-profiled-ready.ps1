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
    [string]$SessionReport = "",
    [string]$Ffmpeg = "",
    [ValidateRange(0, 2147483647)]
    [int]$SithSeed = 1337,
    [ValidateSet("female", "male", "neutral")]
    [string]$BodyModelGender = "",
    [switch]$SkipObservationSelection,
    [switch]$AllowCpu,
    [switch]$AllowDirty,
    [switch]$KeepPrivateWorkspace
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$readyScript = Join-Path $repoRoot "clone-body-from-stash-ready.ps1"
if (-not (Test-Path -LiteralPath $readyScript -PathType Leaf)) {
    throw "Canonical ready-rig Stash launcher not found: $readyScript"
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        $BodyRigPython = (Resolve-Path -LiteralPath $venv).Path
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
if (-not (Test-Path -LiteralPath $BodyRigPython -PathType Leaf)) {
    throw "BodyRig Python not found: $BodyRigPython"
}
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    $StashUrl = [string]$env:STASH_URL
}
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    throw "Stash URL is required via -StashUrl or STASH_URL."
}
if ([string]::IsNullOrWhiteSpace($ApiKeyEnv)) {
    throw "-ApiKeyEnv must name the environment variable containing the Stash API key."
}

$profileArgs = @(
    "-m", "bodyrig.stash_performer_profile",
    "--performer-id", $PerformerId,
    "--url", $StashUrl,
    "--api-key-env", $ApiKeyEnv
)
$profileRaw = @(& $BodyRigPython @profileArgs)
if ($LASTEXITCODE -ne 0 -or $profileRaw.Count -ne 1) {
    throw "BodyRig could not resolve the Stash performer profile before physical clone start."
}
try {
    $profile = ([string]$profileRaw[0]) | ConvertFrom-Json
} catch {
    throw "Stash performer profile returned unreadable JSON."
}
if ([string]$profile.id -ne $PerformerId) {
    throw "Stash performer profile resolved a different performer id."
}

$resolvedGender = $BodyModelGender
$genderSource = "operator-reviewed-override"
if ([string]::IsNullOrWhiteSpace($resolvedGender)) {
    $resolvedGender = ([string]$profile.body_model_gender).Trim().ToLowerInvariant()
    $genderSource = [string]$profile.gender_source
    if ([string]::IsNullOrWhiteSpace([string]$profile.stash_gender)) {
        throw "Stash performer gender metadata is missing/unavailable; refusing a silent neutral body model. Pass -BodyModelGender female|male|neutral after review."
    }
}
if ($resolvedGender -notin @("female", "male", "neutral")) {
    throw "Resolved SMPL-X body model gender is invalid: $resolvedGender"
}

$env:BODYRIG_SITH_BODY_MODEL_GENDER = $resolvedGender
$env:BODYRIG_STASH_EYE_COLOR = [string]$profile.eye_color
$env:BODYRIG_STASH_HAIR_COLOR = [string]$profile.hair_color
if ($null -ne $profile.height_cm) {
    $env:BODYRIG_STASH_HEIGHT_CM = [string]$profile.height_cm
} else {
    Remove-Item Env:BODYRIG_STASH_HEIGHT_CM -ErrorAction SilentlyContinue
}

Write-Host "BodyRig performer-profiled clone"
Write-Host "Performer: $([string]$profile.name) [$PerformerId]"
Write-Host "SMPL-X body model: $resolvedGender | source=$genderSource | Stash gender=$([string]$profile.stash_gender)"
if (-not [string]::IsNullOrWhiteSpace([string]$profile.hair_color)) {
    Write-Host "Appearance metadata: hair=$([string]$profile.hair_color)"
}
if (-not [string]::IsNullOrWhiteSpace([string]$profile.eye_color)) {
    Write-Host "Appearance metadata: eyes=$([string]$profile.eye_color)"
}
Write-Host "Source-shell fidelity repair: enabled by built-in gender-aware fitter"
Write-Host ""

$forward = @{}
foreach ($entry in $PSBoundParameters.GetEnumerator()) {
    if ([string]$entry.Key -eq "BodyModelGender") { continue }
    $forward[[string]$entry.Key] = $entry.Value
}
$forward["BodyRigPython"] = $BodyRigPython
$forward["StashUrl"] = $StashUrl
$forward["ApiKeyEnv"] = $ApiKeyEnv

& $readyScript @forward
if ($LASTEXITCODE -ne 0) {
    throw "Performer-profiled ready-rig clone failed with exit code $LASTEXITCODE"
}
exit 0
