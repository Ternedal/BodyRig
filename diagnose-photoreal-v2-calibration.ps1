param(
    [Parameter(Mandatory = $true)]
    [string]$RunRoot,

    [ValidateRange(1, 100)]
    [int]$TopMatches = 10,

    [string]$Out = "",

    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = $PSScriptRoot
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "BodyRig virtualenv Python not found: $python"
}

$RunRoot = (Resolve-Path -LiteralPath $RunRoot).Path
if (-not (Test-Path -LiteralPath $RunRoot -PathType Container)) {
    throw "BodyRig Photoreal run root not found: $RunRoot"
}

$requiredArtifacts = @(
    "identity-bank.json",
    "identity-calibration-plan.json",
    "identity-calibration-extractor\output\negative-observations.json"
)

foreach ($relativePath in $requiredArtifacts) {
    $artifactPath = Join-Path $RunRoot $relativePath
    if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
        throw "Required Photoreal calibration artifact not found: $artifactPath"
    }
}

$arguments = @(
    "-m",
    "bodyrig.photoreal_identity_calibration_diagnostic_cli",
    "--run-root",
    $RunRoot,
    "--top-matches",
    [string]$TopMatches
)

if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $outputPath = [System.IO.Path]::GetFullPath($Out)
    $arguments += @("--out", $outputPath)
}

Write-Host "BodyRig Photoreal identity calibration diagnostic"
Write-Host "Run root: $RunRoot"
Write-Host "Authority: diagnostic-only"
Write-Host ""

$jsonText = (& $python @arguments | Out-String).Trim()
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    exit $exitCode
}

try {
    $result = $jsonText | ConvertFrom-Json
}
catch {
    Write-Error "Diagnostic CLI returned invalid JSON."
    exit 1
}

$highest = $result.highest_negative_match
$source = $result.highest_collision_negative_source
$blockers = @($result.stage13_calibration_blockers) -join "; "

$fullDiagnostic = $null
$diagnosticOutput = [string]$result.output
if (-not [string]::IsNullOrWhiteSpace($diagnosticOutput) -and
    (Test-Path -LiteralPath $diagnosticOutput -PathType Leaf)) {
    try {
        $fullDiagnostic = Get-Content -LiteralPath $diagnosticOutput -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    } catch {
        throw "Full calibration diagnostic is unreadable JSON: $diagnosticOutput"
    }
}

Write-Host ""
Write-Host "Stage-13 diagnostic summary"
Write-Host "Target performer: $($result.target_performer_id)"
Write-Host "Blockers: $blockers"
Write-Host (
    "Separation margin: observed {0}; required >= {1}" -f
        $result.observed_separation_margin,
        $result.minimum_required_separation_margin
)
Write-Host (
    "Negative ceiling: {0}; maximum allowed {1}" -f
        $result.negative_ceiling,
        $result.maximum_allowed_negative_cosine
)
Write-Host (
    "Violating negatives: {0}/{1} across {2} performer(s) and {3} source(s)" -f
        $result.violating_negative_observation_count,
        $result.negative_observation_count,
        $result.violating_negative_performer_count,
        $result.violating_negative_source_count
)
Write-Host (
    "Extraction yield: {0}/{1} ({2})" -f
        $result.negative_observation_count,
        $result.planned_negative_observation_count,
        $result.negative_extraction_yield_fraction
)
Write-Host (
    "Positive floor: {0}; positive median: {1}" -f
        $result.positive_floor,
        $result.positive_cosine_median
)
Write-Host (
    "Positive reference-to-target cosine min: {0}" -f
        $result.positive_reference_to_target_cosine_min
)
Write-Host (
    "Positive cross-group centroid cosine min: {0}" -f
        $result.positive_cross_group_centroid_cosine_min
)

if ($null -ne $fullDiagnostic) {
    $weakest = $fullDiagnostic.weakest_positive_group
    Write-Host ""
    Write-Host "Weakest positive group"
    Write-Host "Group: $($weakest.group_id)"
    Write-Host "References: $($weakest.reference_count)"
    Write-Host "Sources: $($weakest.source_count)"
    Write-Host "Centroid-to-target cosine: $($weakest.centroid_to_target_cosine)"
    Write-Host (
        "Leave-group-out cosine min/median/max: {0} / {1} / {2}" -f
            $weakest.leave_group_out_cosine_min,
            $weakest.leave_group_out_cosine_median,
            $weakest.leave_group_out_cosine_max
    )
    Write-Host (
        "Within-group pairwise cosine min/median/max: {0} / {1} / {2}" -f
            $weakest.within_group_pairwise_cosine_min,
            $weakest.within_group_pairwise_cosine_median,
            $weakest.within_group_pairwise_cosine_max
    )

    $lowestPositive = $fullDiagnostic.lowest_positive_reference
    Write-Host ""
    Write-Host "Lowest positive reference"
    Write-Host "Group: $($lowestPositive.group_id)"
    Write-Host "Source: $($lowestPositive.source_key)"
    if ($null -ne $lowestPositive.timestamp_seconds) {
        Write-Host "Timestamp seconds: $($lowestPositive.timestamp_seconds)"
    }
    Write-Host "Eye: $($lowestPositive.eye)"
    Write-Host "Cosine: $($lowestPositive.cosine)"
    Write-Host "Frame SHA-256: $($lowestPositive.frame_sha256)"

    Write-Host ""
    Write-Host "Positive cross-group centroid pairs"
    foreach ($pair in @($fullDiagnostic.positive_cross_group_pairs)) {
        Write-Host (
            "{0} <-> {1}: {2}" -f
                $pair.left_group_id,
                $pair.right_group_id,
                $pair.centroid_cosine
        )
    }
}
$quality = $result.negative_observation_quality_metadata
Write-Host (
    "Calibration quality metadata: {0}/{1} observations complete" -f
        $quality.complete_observation_count,
        $result.negative_observation_count
)
if ($quality.reextraction_required_for_complete_quality_audit) {
    Write-Host (
        "Calibration quality audit: RE-EXTRACTION REQUIRED; missing fields: {0}" -f
            (@($quality.missing_fields) -join ", ")
    )
} else {
    Write-Host "Calibration quality audit: AVAILABLE FROM SAVED ARTIFACT"
}
Write-Host ""
Write-Host "Highest negative match"
Write-Host (
    "Performer: {0} {1}" -f
        $highest.subject_performer_id,
        $highest.subject_performer_name
)
Write-Host "Cosine: $($highest.cosine)"
Write-Host (
    "Closest positive group: {0} (cosine {1}; margin to next {2})" -f
        $highest.closest_positive_group.group_id,
        $highest.closest_positive_group.cosine,
        $highest.closest_positive_group_margin
)
Write-Host (
    "Closest positive reference: group {0}; source {1}; cosine {2}" -f
        $highest.closest_positive_reference.group_id,
        $highest.closest_positive_reference.source_key,
        $highest.closest_positive_reference.cosine
)
if ($null -ne $highest.closest_positive_reference.timestamp_seconds) {
    Write-Host (
        "Closest positive reference timestamp seconds: {0}" -f
            $highest.closest_positive_reference.timestamp_seconds
    )
}
Write-Host "Source: $($highest.resolved_path)"
if ($null -ne $highest.timestamp_seconds) {
    Write-Host "Timestamp seconds: $($highest.timestamp_seconds)"
}
Write-Host "Eye: $($highest.eye)"
Write-Host "Frame SHA-256: $($highest.frame_sha256)"
Write-Host ""
Write-Host "Highest-collision source: $($source.resolved_path)"
Write-Host "Diagnostic JSON: $($result.output)"
Write-Host "Authority: diagnostic-only; no matching, training, or production authority."

exit 0
