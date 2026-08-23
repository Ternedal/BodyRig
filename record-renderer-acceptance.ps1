param(
    [Parameter(Mandatory = $true)]
    [string]$AcceptanceReport,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeManifest,

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

function Read-PackageChecksums {
    param([Parameter(Mandatory = $true)][string]$PackagePath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($PackagePath)
    try {
        $entry = $archive.GetEntry("checksums.json")
        if ($null -eq $entry) {
            throw "Accepted .mrbody has no checksums.json."
        }
        $stream = $entry.Open()
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true, 4096, $false)
        try {
            $text = $reader.ReadToEnd()
        } finally {
            $reader.Dispose()
        }
        try {
            return $text | ConvertFrom-Json
        } catch {
            throw "Accepted .mrbody checksums.json is invalid JSON."
        }
    } finally {
        $archive.Dispose()
    }
}

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

if (-not (Test-Path -LiteralPath $RuntimeManifest -PathType Leaf)) {
    throw "Runtime manifest not found: $RuntimeManifest"
}
$RuntimeManifest = (Resolve-Path -LiteralPath $RuntimeManifest).Path
try {
    $runtime = Get-Content -LiteralPath $RuntimeManifest -Raw | ConvertFrom-Json
} catch {
    throw "Runtime manifest is not valid JSON: $RuntimeManifest"
}
$expectedRuntimeFields = @(
    "format", "version", "body_id", "body_name", "package_sha256", "avatar", "bodyprint", "payloads"
)
$runtimeFields = @($runtime.PSObject.Properties.Name)
if (@(Compare-Object -ReferenceObject $expectedRuntimeFields -DifferenceObject $runtimeFields).Count -ne 0) {
    throw "Runtime manifest fields do not match BodyRig runtime assets v1."
}
if ([string]$runtime.format -ne "bodyrig-runtime-assets" -or [int]$runtime.version -ne 1) {
    throw "Unsupported BodyRig runtime manifest format/version."
}
if ([string]$runtime.body_id -ne $bodyId) {
    throw "Runtime manifest body id does not match automated acceptance."
}
if (([string]$runtime.package_sha256).ToLowerInvariant() -ne $actualPackageHash) {
    throw "Runtime manifest is bound to a different .mrbody package."
}
if ([string]$runtime.avatar -ne "avatar.vrm" -or [string]$runtime.bodyprint -ne "bodyprint.json") {
    throw "Runtime manifest contains unexpected avatar/bodyprint paths."
}
$payloads = @($runtime.payloads)
if ($payloads -notcontains "avatar.vrm" -or $payloads -notcontains "bodyprint.json") {
    throw "Runtime manifest does not include required avatar/bodyprint payloads."
}

$runtimeDir = Split-Path -Parent $RuntimeManifest
$avatarPath = Join-Path $runtimeDir "avatar.vrm"
$bodyprintPath = Join-Path $runtimeDir "bodyprint.json"
if (-not (Test-Path -LiteralPath $avatarPath -PathType Leaf) -or -not (Test-Path -LiteralPath $bodyprintPath -PathType Leaf)) {
    throw "Materialized runtime is missing avatar.vrm or bodyprint.json."
}
$avatarHash = (Get-FileHash -LiteralPath $avatarPath -Algorithm SHA256).Hash.ToLowerInvariant()
$bodyprintHash = (Get-FileHash -LiteralPath $bodyprintPath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksums = Read-PackageChecksums -PackagePath $packagePath
$avatarChecksumProperty = $checksums.PSObject.Properties["avatar.vrm"]
$bodyprintChecksumProperty = $checksums.PSObject.Properties["bodyprint.json"]
if ($null -eq $avatarChecksumProperty -or $null -eq $bodyprintChecksumProperty) {
    throw "Accepted .mrbody checksums.json does not contain avatar/bodyprint hashes."
}
$expectedAvatarHash = ([string]$avatarChecksumProperty.Value).ToLowerInvariant()
$expectedBodyprintHash = ([string]$bodyprintChecksumProperty.Value).ToLowerInvariant()
if ($expectedAvatarHash -notmatch '^[0-9a-f]{64}$' -or $avatarHash -ne $expectedAvatarHash) {
    throw "Materialized avatar.vrm does not match the accepted .mrbody payload checksum."
}
if ($expectedBodyprintHash -notmatch '^[0-9a-f]{64}$' -or $bodyprintHash -ne $expectedBodyprintHash) {
    throw "Materialized bodyprint.json does not match the accepted .mrbody payload checksum."
}
$runtimeManifestHash = (Get-FileHash -LiteralPath $RuntimeManifest -Algorithm SHA256).Hash.ToLowerInvariant()

if ([string]::IsNullOrWhiteSpace($Output)) {
    $suffix = if ($Platform -eq "windows-unity-univrm") { "windows" } else { "quest" }
    $Output = Join-Path $reportDir "bodyrig-renderer-acceptance-$suffix.json"
}
$Output = [System.IO.Path]::GetFullPath($Output)
foreach ($evidencePath in @($AcceptanceReport, $packagePath, $RuntimeManifest, $avatarPath, $bodyprintPath)) {
    if ([string]::Equals($Output, $evidencePath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Renderer acceptance output must not overwrite input evidence."
    }
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
    runtime_manifest_sha256 = $runtimeManifestHash
    avatar_sha256 = $avatarHash
    bodyprint_sha256 = $bodyprintHash
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
Write-Host "Runtime manifest SHA-256: $runtimeManifestHash"
Write-Host "Avatar SHA-256: $avatarHash"
Write-Host "Renderer: $RendererName | $RendererVersion"
Write-Host "Report: $Output"
exit 0
