param(
    [Parameter(Mandatory = $true)]
    [string]$AcceptanceReport,

    [Parameter(Mandatory = $true)]
    [ValidateSet("windows-unity-univrm", "android-quest-class")]
    [string]$Platform,

    [Parameter(Mandatory = $true)]
    [switch]$Pass,

    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 160)]
    [string]$RendererName,

    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 160)]
    [string]$RendererVersion,

    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 2000)]
    [string]$QualityNote,

    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

foreach ($value in @($RendererName, $RendererVersion, $QualityNote)) {
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "RendererName, RendererVersion and QualityNote must contain non-whitespace text."
    }
}
$RendererName = $RendererName.Trim()
$RendererVersion = $RendererVersion.Trim()
$QualityNote = $QualityNote.Trim()
if (-not $Pass) {
    throw "Renderer acceptance requires an explicit -Pass attestation."
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
if ($report.automated_pass -ne $true -or $report.production_activation -ne $false -or [string]$report.physical_renderer_acceptance -ne "pending") {
    throw "Automated rig acceptance is not in a valid pending-renderer PASS state."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not read BodyRig Git HEAD."
}
$acceptedRevision = ([string]$report.bodyrig_revision).ToLowerInvariant()
if ($acceptedRevision -notmatch '^[0-9a-f]{40}$' -or $head -ne $acceptedRevision) {
    throw "BodyRig HEAD does not match the automated acceptance revision."
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -gt 0) {
    throw "BodyRig checkout is dirty; renderer attestation requires the exact clean accepted revision."
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
    $suffix = if ($Platform -eq "windows-unity-univrm") { "windows" } else { "quest" }
    $Output = Join-Path $reportDir "bodyrig-renderer-acceptance-$suffix.json"
}
$Output = [System.IO.Path]::GetFullPath($Output)
if ([string]::Equals($Output, $AcceptanceReport, [System.StringComparison]::OrdinalIgnoreCase) -or
    [string]::Equals($Output, $packagePath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Renderer acceptance output must not overwrite automated evidence."
}
if (Test-Path -LiteralPath $Output) {
    throw "Renderer acceptance output already exists; refusing to overwrite evidence: $Output"
}
$outputDir = Split-Path -Parent $Output
if (-not (Test-Path -LiteralPath $outputDir -PathType Container)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

$attestation = [ordered]@{
    format = "bodyrig-renderer-acceptance"
    version = 1
    attested_at = [DateTime]::UtcNow.ToString("o")
    bodyrig_revision = $head
    automated_report_sha256 = $reportHash
    package_sha256 = $actualPackageHash
    body_id = $bodyId
    platform = $Platform
    renderer_name = $RendererName
    renderer_version = $RendererVersion
    result = "pass"
    quality_note = $QualityNote
    attestation = "operator-supplied"
    production_activation = $false
}

$temp = Join-Path $outputDir ("." + [System.IO.Path]::GetFileName($Output) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
try {
    $attestation | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temp -Encoding UTF8
    $roundTrip = Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json
    if ([string]$roundTrip.platform -ne $Platform -or [string]$roundTrip.result -ne "pass" -or $roundTrip.production_activation -ne $false) {
        throw "Renderer acceptance round-trip validation failed."
    }
    Move-Item -LiteralPath $temp -Destination $Output
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
}

Write-Host "BodyRig renderer acceptance: PASS"
Write-Host "Platform: $Platform"
Write-Host "Revision: $head"
Write-Host "Package SHA-256: $actualPackageHash"
Write-Host "Renderer: $RendererName | $RendererVersion"
Write-Host "Report: $Output"
exit 0
