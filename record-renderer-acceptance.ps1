param(
    [Parameter(Mandatory = $true)]
    [string]$AcceptanceReport,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeManifest,

    [Parameter(Mandatory = $true)]
    [string]$ProbeReport,

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

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    try {
        $value = Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json
    } catch {
        throw "$Label is not valid JSON: $resolved"
    }
    return [pscustomobject]@{ Path = $resolved; Value = $value }
}

function Require-LowerSha256 {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Field)
    $normalized = $Value.ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Field is not a canonical SHA-256." }
    return $normalized
}

function Read-PackageChecksums {
    param([Parameter(Mandatory = $true)][string]$PackagePath)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($PackagePath)
    try {
        $entry = $archive.GetEntry("checksums.json")
        if ($null -eq $entry) { throw "Accepted .mrbody has no checksums.json." }
        $stream = $entry.Open()
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true, 4096, $false)
        try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
        try { return $text | ConvertFrom-Json } catch { throw "Accepted .mrbody checksums.json is invalid JSON." }
    } finally { $archive.Dispose() }
}

foreach ($value in @($RendererName, $RendererVersion, $QualityNote)) {
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "RendererName, RendererVersion and QualityNote must contain non-whitespace text."
    }
}
$RendererName = $RendererName.Trim()
$RendererVersion = $RendererVersion.Trim()
$QualityNote = $QualityNote.Trim()
if (-not $Pass) { throw "Renderer acceptance requires an explicit -Pass attestation." }

$acceptanceFile = Read-JsonFile -Path $AcceptanceReport -Label "Acceptance report"
$AcceptanceReport = $acceptanceFile.Path
$report = $acceptanceFile.Value
$reportDir = Split-Path -Parent $AcceptanceReport
if ([string]$report.format -ne "bodyrig-rig-acceptance" -or [int]$report.version -ne 1) {
    throw "Unsupported BodyRig acceptance report format/version."
}
if ($report.automated_pass -ne $true -or $report.production_activation -ne $false -or [string]$report.physical_renderer_acceptance -ne "pending") {
    throw "Automated rig acceptance is not in a valid pending-renderer PASS state."
}
if ([string]$report.runtime.manifest -ne "runtime/runtime-manifest.json" -or $report.runtime.materialized_from_package -ne $true) {
    throw "Automated acceptance does not contain valid materialized runtime evidence."
}
$acceptedRuntimeManifestHash = Require-LowerSha256 ([string]$report.runtime.manifest_sha256) "runtime.manifest_sha256"

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Could not read BodyRig Git HEAD." }
$acceptedRevision = ([string]$report.bodyrig_revision).ToLowerInvariant()
if ($acceptedRevision -notmatch '^[0-9a-f]{40}$' -or $head -ne $acceptedRevision) {
    throw "BodyRig HEAD does not match the automated acceptance revision."
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; renderer attestation requires the exact clean accepted revision." }

$bodyId = [string]$report.package.body_id
if ([string]::IsNullOrWhiteSpace($bodyId) -or $bodyId -notmatch '^[a-z0-9æøå_-]{1,160}$') {
    throw "Acceptance report contains an invalid body id."
}
$packagePath = Join-Path $reportDir "$bodyId.mrbody"
if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) { throw "Accepted .mrbody package not found beside report: $packagePath" }
$packagePath = (Resolve-Path -LiteralPath $packagePath).Path
$expectedPackageHash = Require-LowerSha256 ([string]$report.package.package_sha256) "package.package_sha256"
$actualPackageHash = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualPackageHash -ne $expectedPackageHash) { throw "Accepted .mrbody SHA-256 no longer matches the automated acceptance report." }
$reportHash = (Get-FileHash -LiteralPath $AcceptanceReport -Algorithm SHA256).Hash.ToLowerInvariant()

$runtimeFile = Read-JsonFile -Path $RuntimeManifest -Label "Runtime manifest"
$RuntimeManifest = $runtimeFile.Path
$runtime = $runtimeFile.Value
$expectedRuntimeFields = @("format", "version", "body_id", "body_name", "package_sha256", "avatar", "bodyprint", "payloads")
$runtimeFields = @($runtime.PSObject.Properties.Name)
if (@(Compare-Object -ReferenceObject $expectedRuntimeFields -DifferenceObject $runtimeFields).Count -ne 0) {
    throw "Runtime manifest fields do not match BodyRig runtime assets v1."
}
if ([string]$runtime.format -ne "bodyrig-runtime-assets" -or [int]$runtime.version -ne 1) { throw "Unsupported BodyRig runtime manifest format/version." }
if ([string]$runtime.body_id -ne $bodyId) { throw "Runtime manifest body id does not match automated acceptance." }
if (([string]$runtime.package_sha256).ToLowerInvariant() -ne $actualPackageHash) { throw "Runtime manifest is bound to a different .mrbody package." }
if ([string]$runtime.avatar -ne "avatar.vrm" -or [string]$runtime.bodyprint -ne "bodyprint.json") { throw "Runtime manifest contains unexpected avatar/bodyprint paths." }
$payloads = @($runtime.payloads)
if ($payloads -notcontains "avatar.vrm" -or $payloads -notcontains "bodyprint.json") { throw "Runtime manifest does not include required avatar/bodyprint payloads." }
$runtimeManifestHash = (Get-FileHash -LiteralPath $RuntimeManifest -Algorithm SHA256).Hash.ToLowerInvariant()
if ($runtimeManifestHash -ne $acceptedRuntimeManifestHash) { throw "Runtime manifest SHA-256 no longer matches the Gate A acceptance report." }

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
if ($null -eq $avatarChecksumProperty -or $null -eq $bodyprintChecksumProperty) { throw "Accepted .mrbody checksums.json does not contain avatar/bodyprint hashes." }
$expectedAvatarHash = Require-LowerSha256 ([string]$avatarChecksumProperty.Value) "checksums.avatar.vrm"
$expectedBodyprintHash = Require-LowerSha256 ([string]$bodyprintChecksumProperty.Value) "checksums.bodyprint.json"
if ($avatarHash -ne $expectedAvatarHash) { throw "Materialized avatar.vrm does not match the accepted .mrbody payload checksum." }
if ($bodyprintHash -ne $expectedBodyprintHash) { throw "Materialized bodyprint.json does not match the accepted .mrbody payload checksum." }

$probeFile = Read-JsonFile -Path $ProbeReport -Label "Renderer machine probe"
$ProbeReport = $probeFile.Path
$probe = $probeFile.Value
$expectedProbeFields = @(
    "format", "version", "observed_at", "platform", "unity_platform", "unity_version", "graphics_device",
    "body_id", "package_sha256", "runtime_manifest_sha256", "avatar_sha256", "bodyprint_sha256",
    "vrm10_loaded", "humanoid_valid", "required_bones_valid", "active_renderer"
)
$probeFields = @($probe.PSObject.Properties.Name)
if (@(Compare-Object -ReferenceObject $expectedProbeFields -DifferenceObject $probeFields).Count -ne 0) {
    throw "Renderer machine probe fields do not match BodyRig renderer probe v1."
}
if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1) { throw "Unsupported renderer machine probe format/version." }
if ([string]$probe.platform -ne $Platform) { throw "Renderer machine probe platform mismatch. Expected $Platform, got $($probe.platform)." }
if ($probe.vrm10_loaded -ne $true -or $probe.humanoid_valid -ne $true -or $probe.required_bones_valid -ne $true) {
    throw "Renderer machine probe did not prove VRM 1.0 + Humanoid + required-bones success."
}
if ([string]$probe.body_id -ne $bodyId) { throw "Renderer machine probe body id does not match automated acceptance." }
if ((Require-LowerSha256 ([string]$probe.package_sha256) "probe.package_sha256") -ne $actualPackageHash) { throw "Renderer machine probe is bound to a different .mrbody package." }
if ((Require-LowerSha256 ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $runtimeManifestHash) { throw "Renderer machine probe is bound to a different runtime manifest." }
if ((Require-LowerSha256 ([string]$probe.avatar_sha256) "probe.avatar_sha256") -ne $avatarHash) { throw "Renderer machine probe is bound to a different avatar." }
if ((Require-LowerSha256 ([string]$probe.bodyprint_sha256) "probe.bodyprint_sha256") -ne $bodyprintHash) { throw "Renderer machine probe is bound to a different bodyprint." }
if ([string]$probe.active_renderer.name -ne $RendererName -or [string]$probe.active_renderer.version -ne $RendererVersion) {
    throw "Renderer name/version do not match the machine probe."
}
foreach ($fieldName in @("observed_at", "unity_platform", "unity_version", "graphics_device")) {
    $value = [string]$probe.$fieldName
    if ([string]::IsNullOrWhiteSpace($value)) { throw "Renderer machine probe is missing '$fieldName'." }
}
if ($Platform -eq "windows-unity-univrm" -and [string]$probe.unity_platform -notin @("WindowsEditor", "WindowsPlayer")) {
    throw "Windows renderer probe was not produced by Unity on Windows."
}
if ($Platform -eq "android-quest-class" -and [string]$probe.unity_platform -ne "Android") {
    throw "Quest-class renderer probe was not produced by an Android Unity runtime."
}
$probeHash = (Get-FileHash -LiteralPath $ProbeReport -Algorithm SHA256).Hash.ToLowerInvariant()

if ([string]::IsNullOrWhiteSpace($Output)) {
    $suffix = if ($Platform -eq "windows-unity-univrm") { "windows" } else { "quest" }
    $Output = Join-Path $reportDir "bodyrig-renderer-acceptance-$suffix.json"
}
$Output = [System.IO.Path]::GetFullPath($Output)
foreach ($evidencePath in @($AcceptanceReport, $packagePath, $RuntimeManifest, $avatarPath, $bodyprintPath, $ProbeReport)) {
    if ([string]::Equals($Output, $evidencePath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Renderer acceptance output must not overwrite input evidence."
    }
}
if (Test-Path -LiteralPath $Output) { throw "Renderer acceptance output already exists; refusing to overwrite evidence: $Output" }
$outputDir = Split-Path -Parent $Output
if (-not (Test-Path -LiteralPath $outputDir -PathType Container)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }

$attestation = [ordered]@{
    format = "bodyrig-renderer-acceptance"
    version = 1
    attested_at = [DateTime]::UtcNow.ToString("o")
    bodyrig_revision = $head
    automated_report_sha256 = $reportHash
    probe_report_sha256 = $probeHash
    package_sha256 = $actualPackageHash
    runtime_manifest_sha256 = $runtimeManifestHash
    avatar_sha256 = $avatarHash
    bodyprint_sha256 = $bodyprintHash
    body_id = $bodyId
    platform = $Platform
    renderer_name = $RendererName
    renderer_version = $RendererVersion
    unity_platform = [string]$probe.unity_platform
    unity_version = [string]$probe.unity_version
    graphics_device = [string]$probe.graphics_device
    machine_probe = $true
    result = "pass"
    quality_note = $QualityNote
    attestation = "operator-supplied"
    production_activation = $false
}

$temp = Join-Path $outputDir ("." + [System.IO.Path]::GetFileName($Output) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
try {
    $attestation | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temp -Encoding UTF8
    $roundTrip = Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json
    if ([string]$roundTrip.platform -ne $Platform -or [string]$roundTrip.result -ne "pass" -or $roundTrip.machine_probe -ne $true -or $roundTrip.production_activation -ne $false) {
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
Write-Host "Machine probe SHA-256: $probeHash"
Write-Host "Runtime manifest SHA-256: $runtimeManifestHash"
Write-Host "Avatar SHA-256: $avatarHash"
Write-Host "Renderer: $RendererName | $RendererVersion"
Write-Host "Unity: $($probe.unity_platform) | $($probe.unity_version) | $($probe.graphics_device)"
Write-Host "Report: $Output"
exit 0
