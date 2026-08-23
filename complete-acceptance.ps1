param(
    [Parameter(Mandatory = $true)]
    [string]$AcceptanceReport,

    [Parameter(Mandatory = $true)]
    [switch]$WindowsRendererPass,

    [Parameter(Mandatory = $true)]
    [switch]$QuestRendererPass,

    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 2000)]
    [string]$QualityNote,

    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-True {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Field
    )
    if ($Value -ne $true) {
        throw "$Field must be true before release acceptance can pass."
    }
}

if (-not (Test-Path -LiteralPath $AcceptanceReport -PathType Leaf)) {
    throw "Acceptance report not found: $AcceptanceReport"
}
$AcceptanceReport = (Resolve-Path -LiteralPath $AcceptanceReport).Path
$reportDir = Split-Path -Parent $AcceptanceReport

try {
    $report = Get-Content -LiteralPath $AcceptanceReport -Raw | ConvertFrom-Json
} catch {
    throw "Acceptance report is not valid JSON: $AcceptanceReport"
}

if ([string]$report.format -ne "bodyrig-rig-acceptance" -or [int]$report.version -ne 1) {
    throw "Unsupported BodyRig acceptance report format/version."
}
Require-True $report.automated_pass "automated_pass"
Require-True $report.bodyrig_checkout_clean "bodyrig_checkout_clean"
if ([string]$report.physical_renderer_acceptance -ne "pending") {
    throw "Acceptance report is not in the expected pending renderer state."
}
if ($report.production_activation -ne $false) {
    throw "Input acceptance report unexpectedly has production_activation=true."
}
if (-not $WindowsRendererPass -or -not $QuestRendererPass) {
    throw "Both Windows and Quest/Android renderer checks must be explicitly attested."
}
$QualityNote = $QualityNote.Trim()
if ([string]::IsNullOrWhiteSpace($QualityNote)) {
    throw "QualityNote must contain a meaningful non-whitespace renderer observation."
}

$sourceCount = [int]$report.source_count
if ($sourceCount -lt 1 -or $sourceCount -gt 10) {
    throw "Acceptance report contains an invalid source_count."
}
$observedFrames = [int]$report.recovery.observed_frames
if ($observedFrames -lt 2) {
    throw "Acceptance report does not contain enough observed recovery frames."
}

$requiredChecks = @(
    "bodyrig_checkout_clean",
    "preflight_ok",
    "recovery_adapter_pinned",
    "observed_frames_ge_2",
    "source_derived_shape_present",
    "source_derived_motion_present",
    "bodyprint_matches_package",
    "source_count_matches_package",
    "recovery_provenance_matches",
    "avatar_fitting_provenance_present",
    "avatar_is_vrm_1_0"
)
foreach ($checkName in $requiredChecks) {
    $property = $report.checks.PSObject.Properties[$checkName]
    if ($null -eq $property -or $property.Value -ne $true) {
        throw "Automated acceptance check is missing or false: checks.$checkName"
    }
}

$requiredPackageChecks = @(
    "bodyprint_matches_proof",
    "source_count_matches",
    "recovery_provenance_matches",
    "avatar_fitting_provenance_present"
)
foreach ($checkName in $requiredPackageChecks) {
    $property = $report.package.PSObject.Properties[$checkName]
    if ($null -eq $property -or $property.Value -ne $true) {
        throw "Package acceptance check is missing or false: package.$checkName"
    }
}
if ([string]$report.package.vrm_spec_version -ne "1.0") {
    throw "Accepted package is not recorded as VRM 1.0."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not read BodyRig Git HEAD."
}
$acceptedRevision = ([string]$report.bodyrig_revision).ToLowerInvariant()
if ($acceptedRevision -notmatch '^[0-9a-f]{40}$' -or $head -ne $acceptedRevision) {
    throw "BodyRig HEAD no longer matches the revision that produced the acceptance report. Expected $($report.bodyrig_revision), got $head."
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect BodyRig Git status."
}
if ($dirty.Count -gt 0) {
    throw "BodyRig checkout is dirty; release attestation requires the exact clean accepted revision."
}

$bodyId = [string]$report.package.body_id
if ([string]::IsNullOrWhiteSpace($bodyId) -or $bodyId -notmatch '^[a-z0-9æøå_-]{1,160}$') {
    throw "Acceptance report contains an invalid body id."
}
$packagePath = Join-Path $reportDir "$bodyId.mrbody"
if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) {
    throw "Accepted .mrbody package not found beside report: $packagePath"
}
$packagePath = (Resolve-Path -LiteralPath $packagePath).Path
$expectedPackageHash = ([string]$report.package.package_sha256).ToLowerInvariant()
$actualPackageHash = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expectedPackageHash -notmatch '^[0-9a-f]{64}$' -or $actualPackageHash -ne $expectedPackageHash) {
    throw "Accepted .mrbody SHA-256 no longer matches the automated acceptance report."
}

$reportHash = (Get-FileHash -LiteralPath $AcceptanceReport -Algorithm SHA256).Hash.ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $reportDir "bodyrig-release-acceptance.json"
}
$Output = [System.IO.Path]::GetFullPath($Output)
if ([string]::Equals($Output, $AcceptanceReport, [System.StringComparison]::OrdinalIgnoreCase) -or
    [string]::Equals($Output, $packagePath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Release output must not overwrite the automated acceptance report or accepted .mrbody package."
}
if (Test-Path -LiteralPath $Output) {
    throw "Release acceptance output already exists; refusing to overwrite evidence: $Output"
}
$outputDir = Split-Path -Parent $Output
if (-not (Test-Path -LiteralPath $outputDir -PathType Container)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

$completedAt = [DateTime]::UtcNow.ToString("o")
$completed = [ordered]@{
    format = "bodyrig-release-acceptance"
    version = 1
    completed_at = $completedAt
    bodyrig_revision = $head
    automated_acceptance = [ordered]@{
        report_sha256 = $reportHash
        package_sha256 = $actualPackageHash
        body_id = $bodyId
        automated_pass = $true
    }
    renderer_acceptance = [ordered]@{
        windows_unity_univrm = "pass"
        android_quest_class = "pass"
        quality_note = $QualityNote
        attestation = "operator-supplied"
        attested_at = $completedAt
    }
    release_gate_pass = $true
    production_activation = $true
}

$temp = Join-Path $outputDir ("." + [System.IO.Path]::GetFileName($Output) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
try {
    $completed | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temp -Encoding UTF8
    $roundTrip = Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json
    if ($roundTrip.release_gate_pass -ne $true -or $roundTrip.production_activation -ne $true) {
        throw "Release acceptance round-trip validation failed."
    }
    Move-Item -LiteralPath $temp -Destination $Output
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
}

Write-Host "BodyRig release acceptance: PASS"
Write-Host "Revision: $head"
Write-Host "Package SHA-256: $actualPackageHash"
Write-Host "Windows Unity/UniVRM: PASS (operator attested)"
Write-Host "Android/Quest-class: PASS (operator attested)"
Write-Host "Release report: $Output"
exit 0
