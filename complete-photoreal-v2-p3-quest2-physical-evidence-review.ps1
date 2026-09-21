param(
    [Parameter(Mandatory = $true)][string]$MachinePrefill,
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-ReviewText {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][int]$Maximum
    )
    while ($true) {
        $value = [string](Read-Host $Prompt)
        $clean = $value.Trim()
        if (
            -not [string]::IsNullOrWhiteSpace($clean) -and
            $clean.Length -le $Maximum -and
            $clean -notmatch "[\r\n]"
        ) {
            return $clean
        }
        Write-Host "$Label must be non-empty and at most $Maximum characters."
    }
}

function Need-Decision {
    param([Parameter(Mandatory = $true)][string]$Criterion)
    while ($true) {
        $value = ([string](Read-Host "[$Criterion] pass/fail")).Trim().ToLowerInvariant()
        if ($value -in @("pass", "fail")) {
            return $value
        }
        Write-Host "Enter exactly 'pass' or 'fail'."
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 interactive physical review requires an exact clean BodyRig checkout."
}

$MachinePrefill = Need-File -Path $MachinePrefill -Label "Quest2 machine-prefilled physical evidence"
$evidence = Get-Content -LiteralPath $MachinePrefill -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

$expectedFields = @(
    "format",
    "version",
    "operator_supplied",
    "runtime_review_plan_sha256",
    "target_device_family",
    "target_device_model",
    "physical_device_observed",
    "installed_student_artifacts",
    "observed_refresh_hz",
    "p95_frame_time_ms",
    "stereo_rendering_observed",
    "vr_safe_frame_pacing_observed",
    "installed_student_hashes_verified_on_device",
    "visual_results",
    "reviewed_by",
    "review_notes",
    "confirm_physical_device_review_complete"
)
$actualFields = @($evidence.PSObject.Properties.Name | Sort-Object)
$expectedSorted = @($expectedFields | Sort-Object)
if (($actualFields -join "|") -ne ($expectedSorted -join "|")) {
    throw "Quest2 machine prefill fields do not match physical evidence v1 exactly."
}
if (
    [string]$evidence.format -ne "bodyrig-photoreal-p3-physical-runtime-evidence" -or
    $evidence.version -is [bool] -or
    [double]$evidence.version -ne 1.0
) {
    throw "Quest2 machine prefill format/version mismatch."
}
if ([string]$evidence.target_device_family -ne "meta-quest" -or [string]$evidence.target_device_model -ne "quest-2") {
    throw "Interactive review currently accepts only canonical Quest 2 evidence."
}

foreach ($field in @(
    "physical_device_observed",
    "stereo_rendering_observed",
    "vr_safe_frame_pacing_observed",
    "installed_student_hashes_verified_on_device"
)) {
    if ($evidence.$field -isnot [bool] -or $evidence.$field -ne $true) {
        throw "Machine-prefilled physical evidence is incomplete: $field"
    }
}
if ($evidence.operator_supplied -isnot [bool] -or $evidence.operator_supplied -ne $false) {
    throw "Interactive review requires an untouched machine prefill with operator_supplied=false."
}
if (
    $evidence.confirm_physical_device_review_complete -isnot [bool] -or
    $evidence.confirm_physical_device_review_complete -ne $false
) {
    throw "Interactive review requires an unconfirmed machine prefill."
}
if ([string]$evidence.reviewed_by -ne "REVIEW_REQUIRED") {
    throw "Interactive review requires reviewed_by=REVIEW_REQUIRED in the machine prefill."
}

$visual = @($evidence.visual_results)
if ($visual.Count -lt 1) {
    throw "Quest2 machine prefill contains no visual review criteria."
}
$seen = @{}
foreach ($item in $visual) {
    if ($null -eq $item) {
        throw "Quest2 machine prefill contains an invalid visual criterion."
    }
    $criterion = ([string]$item.criterion).Trim()
    $decision = ([string]$item.decision).Trim()
    if ([string]::IsNullOrWhiteSpace($criterion) -or $seen.ContainsKey($criterion)) {
        throw "Quest2 machine prefill contains invalid/repeated visual criteria."
    }
    if ($decision -ne "REVIEW_REQUIRED") {
        throw "Interactive review refuses a prefill that already contains a human decision: $criterion"
    }
    $seen[$criterion] = $true
}

if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path (Split-Path -Parent $MachinePrefill) "p3-physical-runtime-evidence.human-review.json"
} else {
    $Output = [IO.Path]::GetFullPath($Output)
}
if (Test-Path -LiteralPath $Output) {
    throw "Quest2 human review evidence already exists: $Output"
}

Write-Host "============================================================"
Write-Host "BODYRIG P3 - QUEST2 INTERACTIVE HUMAN REVIEW"
Write-Host "Machine evidence:          $MachinePrefill"
Write-Host "Target:                    Quest 2"
Write-Host "Observed refresh:          $($evidence.observed_refresh_hz) Hz"
Write-Host "P95 frame time:            $($evidence.p95_frame_time_ms) ms"
Write-Host "Stereo/frame pacing:       MACHINE VERIFIED"
Write-Host "Installed hashes:          MACHINE VERIFIED"
Write-Host "Visual criteria:           $($visual.Count)"
Write-Host "============================================================"
Write-Host ""
Write-Host "Complete every decision while physically reviewing the exact student in-headset."
Write-Host "This operator does not infer or auto-fill any visual PASS/FAIL result."
Write-Host ""

for ($i = 0; $i -lt $visual.Count; $i++) {
    $criterion = [string]$visual[$i].criterion
    $visual[$i].decision = Need-Decision -Criterion $criterion
}

$reviewedBy = Need-ReviewText -Prompt "Reviewer identity" -Label "Reviewer identity" -Maximum 256
$reviewNotes = Need-ReviewText -Prompt "Review notes" -Label "Review notes" -Maximum 8192

Write-Host ""
Write-Host "Visual decisions entered:"
foreach ($item in $visual) {
    Write-Host ("  {0}: {1}" -f $item.criterion, ([string]$item.decision).ToUpperInvariant())
}
Write-Host ""
$confirmation = ([string](Read-Host "Type REVIEW COMPLETE to attest that the physical Quest 2 review is complete")).Trim()
if ($confirmation -cne "REVIEW COMPLETE") {
    throw "Physical review was not explicitly confirmed. No evidence file was written."
}

$evidence.operator_supplied = $true
$evidence.visual_results = $visual
$evidence.reviewed_by = $reviewedBy
$evidence.review_notes = $reviewNotes
$evidence.confirm_physical_device_review_complete = $true

$evidence | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $Output -Encoding UTF8

Write-Host ""
Write-Host "Human-reviewed physical evidence created:"
Write-Host $Output
Write-Host ""
Write-Host "No runtime/photoreal acceptance authority has been granted yet."
Write-Host "Pass this evidence to record-photoreal-v2-p3-quest2-physical-runtime-review.ps1"
Write-Host "for strict validation and the final PASS/FAIL receipt."
exit 0
