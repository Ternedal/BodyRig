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
if ($report.automated_pass -ne $true) {
    throw "Automated acceptance is not PASS; renderer attestation cannot override it."
}
if ([string]$report.physical_renderer_acceptance -ne "pending") {
    throw "Acceptance report is not in the expected pending renderer state."
}
if ($report.production_activation -ne $false) {
    throw "Input acceptance report unexpectedly has production_activation=true."
}
if (-not $WindowsRendererPass -or -not $QuestRendererPass) {
    throw "Both Windows and Quest/Android renderer checks must be explicitly attested."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not read BodyRig Git HEAD."
}
if ($head -ne ([string]$report.bodyrig_revision).ToLowerInvariant()) {
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

$completed = [ordered]@{
    format = "bodyrig-release-acceptance"
    version = 1
    completed_at = [DateTime]::UtcNow.ToString("o")
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
    }
    release_gate_pass = $true
    production_activation = $true
}

$temp = "$Output.tmp"
try {
    $completed | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temp -Encoding UTF8
    $roundTrip = Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json
    if ($roundTrip.release_gate_pass -ne $true -or $roundTrip.production_activation -ne $true) {
        throw "Release acceptance round-trip validation failed."
    }
    Move-Item -LiteralPath $temp -Destination $Output -Force
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
