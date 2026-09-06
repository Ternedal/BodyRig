param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$AssemblyReceipt,
    [Parameter(Mandatory = $true)][string]$BodyReleaseStatus,
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$MotorState,
    [Parameter(Mandatory = $true)][string]$SpeechTiming,
    [Parameter(Mandatory = $true)][string]$AuditionReceipt,
    [Parameter(Mandatory = $true)][string]$QualityNote,
    [switch]$ConfirmMotionReview,
    [switch]$ConfirmExpressionReview,
    [switch]$ConfirmVoiceTimingReview,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for Person embodiment finalization."
}
if (-not $ConfirmMotionReview -or -not $ConfirmExpressionReview -or -not $ConfirmVoiceTimingReview) {
    throw "M4 requires explicit operator confirmation of motion, expression and VoiceRig timing review."
}
$note = $QualityNote.Trim()
if ($note.Length -lt 12 -or $note.Length -gt 2000 -or $note -match '^<[^>]+>$') {
    throw "QualityNote must be a real 12-2000 character operator note, not a placeholder."
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -ne 0) { throw "Person embodiment finalization requires a clean BodyRig checkout." }
$revision = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve exact BodyRig revision." }

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$assembly = Need-File $AssemblyReceipt "Person assembly receipt"
$release = Need-File $BodyReleaseStatus "Body release status"
$package = Need-File $PackagePath "Exact .mrbody package"
$motor = Need-File $MotorState "Motor State v2 evidence"
$timing = Need-File $SpeechTiming "VoiceRig speech timing evidence"
$audition = Need-File $AuditionReceipt "Person audition receipt"
$rootPath = [System.IO.Path]::GetFullPath($Root)

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction Stop
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File $BodyRigPython "BodyRig Python"
& $BodyRigPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Person embodiment finalization requires Python 3.11+." }

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot
    $imported = (& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not import BodyRig from operator checkout." }
    $expectedRoot = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
    $actualModule = [System.IO.Path]::GetFullPath($imported)
    if (-not $actualModule.StartsWith($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Python imported BodyRig outside current checkout: $actualModule"
    }

    $output = @(& $BodyRigPython -m bodyrig.embodiment_authority_cli `
        --root $rootPath `
        --assembly-receipt $assembly `
        --body-release-status $release `
        --package $package `
        --motor-state $motor `
        --speech-timing $timing `
        --audition-receipt $audition `
        --bodyrig-revision $revision `
        --quality-note $note `
        --confirm-motion-review `
        --confirm-expression-review `
        --confirm-voice-timing-review)
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1) {
        throw "Person embodiment authority finalization failed."
    }
    Write-Output ([string]$output[0])
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
