param(
    [Parameter(Mandatory = $true)]
    [string]$AcceptanceReport,

    [Parameter(Mandatory = $true)]
    [string]$WindowsRendererReport,

    [Parameter(Mandatory = $true)]
    [string]$WindowsProbeReport,

    [Parameter(Mandatory = $true)]
    [string]$QuestRendererReport,

    [Parameter(Mandatory = $true)]
    [string]$QuestProbeReport,

    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-True {
    param([Parameter(Mandatory = $true)]$Value, [Parameter(Mandatory = $true)][string]$Field)
    if ($Value -ne $true) { throw "$Field must be true before release acceptance can pass." }
}

function Require-LowerSha256 {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Field)
    $normalized = $Value.ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Field is not a canonical SHA-256." }
    return $normalized
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    try { $value = Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $resolved" }
    return [pscustomobject]@{
        Path = $resolved
        Hash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
        Value = $value
    }
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

function Read-RendererProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedPlatform,
        [Parameter(Mandatory = $true)][string]$ExpectedPackageHash,
        [Parameter(Mandatory = $true)][string]$ExpectedRuntimeManifestHash,
        [Parameter(Mandatory = $true)][string]$ExpectedAvatarHash,
        [Parameter(Mandatory = $true)][string]$ExpectedBodyprintHash,
        [Parameter(Mandatory = $true)][string]$ExpectedBodyId
    )
    $file = Read-JsonFile -Path $Path -Label "Renderer machine probe"
    $value = $file.Value
    $expectedFields = @(
        "format", "version", "observed_at", "platform", "unity_platform", "unity_version", "graphics_device",
        "body_id", "package_sha256", "runtime_manifest_sha256", "avatar_sha256", "bodyprint_sha256",
        "vrm10_loaded", "humanoid_valid", "required_bones_valid", "active_renderer"
    )
    if (@(Compare-Object -ReferenceObject $expectedFields -DifferenceObject @($value.PSObject.Properties.Name)).Count -ne 0) {
        throw "Renderer machine probe fields do not match BodyRig renderer probe v1: $($file.Path)"
    }
    if ([string]$value.format -ne "bodyrig-renderer-probe" -or [int]$value.version -ne 1) { throw "Unsupported renderer machine probe format/version: $($file.Path)" }
    if ([string]$value.platform -ne $ExpectedPlatform) { throw "Renderer machine probe platform mismatch: $($file.Path)" }
    if ($value.vrm10_loaded -ne $true -or $value.humanoid_valid -ne $true -or $value.required_bones_valid -ne $true) {
        throw "Renderer machine probe did not prove VRM/Humanoid/bones success: $($file.Path)"
    }
    if ([string]$value.body_id -ne $ExpectedBodyId) { throw "Renderer machine probe body id mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.package_sha256) "probe.package_sha256") -ne $ExpectedPackageHash) { throw "Renderer machine probe package hash mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $ExpectedRuntimeManifestHash) { throw "Renderer machine probe runtime manifest hash mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.avatar_sha256) "probe.avatar_sha256") -ne $ExpectedAvatarHash) { throw "Renderer machine probe avatar hash mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.bodyprint_sha256) "probe.bodyprint_sha256") -ne $ExpectedBodyprintHash) { throw "Renderer machine probe bodyprint hash mismatch: $($file.Path)" }
    foreach ($fieldName in @("observed_at", "unity_platform", "unity_version", "graphics_device")) {
        if ([string]::IsNullOrWhiteSpace([string]$value.$fieldName)) { throw "Renderer machine probe is missing '$fieldName': $($file.Path)" }
    }
    if ([string]::IsNullOrWhiteSpace([string]$value.active_renderer.name) -or [string]::IsNullOrWhiteSpace([string]$value.active_renderer.version)) {
        throw "Renderer machine probe is missing renderer identity: $($file.Path)"
    }
    if ($ExpectedPlatform -eq "windows-unity-univrm" -and [string]$value.unity_platform -notin @("WindowsEditor", "WindowsPlayer")) {
        throw "Windows machine probe was not emitted by Unity on Windows: $($file.Path)"
    }
    if ($ExpectedPlatform -eq "android-quest-class" -and [string]$value.unity_platform -ne "Android") {
        throw "Quest-class machine probe was not emitted by an Android Unity runtime: $($file.Path)"
    }
    return $file
}

function Read-RendererAcceptance {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Probe,
        [Parameter(Mandatory = $true)][string]$ExpectedPlatform,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$ExpectedAutomatedReportHash,
        [Parameter(Mandatory = $true)][string]$ExpectedPackageHash,
        [Parameter(Mandatory = $true)][string]$ExpectedRuntimeManifestHash,
        [Parameter(Mandatory = $true)][string]$ExpectedAvatarHash,
        [Parameter(Mandatory = $true)][string]$ExpectedBodyprintHash,
        [Parameter(Mandatory = $true)][string]$ExpectedBodyId
    )
    $file = Read-JsonFile -Path $Path -Label "Renderer acceptance report"
    $value = $file.Value
    if ([string]$value.format -ne "bodyrig-renderer-acceptance" -or [int]$value.version -ne 1) { throw "Unsupported renderer acceptance format/version: $($file.Path)" }
    if ([string]$value.platform -ne $ExpectedPlatform) { throw "Renderer acceptance platform mismatch: $($file.Path)" }
    if ([string]$value.result -ne "pass" -or [string]$value.attestation -ne "operator-supplied" -or $value.machine_probe -ne $true -or $value.production_activation -ne $false) {
        throw "Renderer acceptance is not a valid machine-backed, non-activating PASS attestation: $($file.Path)"
    }
    if (([string]$value.bodyrig_revision).ToLowerInvariant() -ne $ExpectedRevision) { throw "Renderer acceptance revision mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.automated_report_sha256) "renderer.automated_report_sha256") -ne $ExpectedAutomatedReportHash) { throw "Renderer acceptance automated report binding mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.probe_report_sha256) "renderer.probe_report_sha256") -ne $Probe.Hash) { throw "Renderer acceptance machine probe binding mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.package_sha256) "renderer.package_sha256") -ne $ExpectedPackageHash) { throw "Renderer acceptance package mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.runtime_manifest_sha256) "renderer.runtime_manifest_sha256") -ne $ExpectedRuntimeManifestHash) { throw "Renderer acceptance runtime manifest mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.avatar_sha256) "renderer.avatar_sha256") -ne $ExpectedAvatarHash) { throw "Renderer acceptance avatar mismatch: $($file.Path)" }
    if ((Require-LowerSha256 ([string]$value.bodyprint_sha256) "renderer.bodyprint_sha256") -ne $ExpectedBodyprintHash) { throw "Renderer acceptance bodyprint mismatch: $($file.Path)" }
    if ([string]$value.body_id -ne $ExpectedBodyId) { throw "Renderer acceptance body id mismatch: $($file.Path)" }
    if ([string]$value.renderer_name -ne [string]$Probe.Value.active_renderer.name -or [string]$value.renderer_version -ne [string]$Probe.Value.active_renderer.version) {
        throw "Renderer acceptance identity no longer matches machine probe: $($file.Path)"
    }
    if ([string]$value.unity_platform -ne [string]$Probe.Value.unity_platform -or [string]$value.unity_version -ne [string]$Probe.Value.unity_version -or [string]$value.graphics_device -ne [string]$Probe.Value.graphics_device) {
        throw "Renderer acceptance Unity/device evidence no longer matches machine probe: $($file.Path)"
    }
    foreach ($fieldName in @("renderer_name", "renderer_version", "quality_note", "attested_at")) {
        if ([string]::IsNullOrWhiteSpace([string]$value.$fieldName)) { throw "Renderer acceptance is missing '$fieldName': $($file.Path)" }
    }
    return $file
}

$automated = Read-JsonFile -Path $AcceptanceReport -Label "Acceptance report"
$AcceptanceReport = $automated.Path
$report = $automated.Value
$reportDir = Split-Path -Parent $AcceptanceReport
if ([string]$report.format -ne "bodyrig-rig-acceptance" -or [int]$report.version -ne 1) { throw "Unsupported BodyRig acceptance report format/version." }
Require-True $report.automated_pass "automated_pass"
Require-True $report.bodyrig_checkout_clean "bodyrig_checkout_clean"
if ([string]$report.physical_renderer_acceptance -ne "pending") { throw "Acceptance report is not in the expected pending renderer state." }
if ($report.production_activation -ne $false) { throw "Input acceptance report unexpectedly has production_activation=true." }
if ([int]$report.source_count -lt 1 -or [int]$report.source_count -gt 10) { throw "Acceptance report contains an invalid source_count." }
if ([int]$report.recovery.observed_frames -lt 2) { throw "Acceptance report does not contain enough observed recovery frames." }

$requiredChecks = @(
    "bodyrig_checkout_clean", "preflight_ok", "recovery_adapter_pinned", "observed_frames_ge_2",
    "source_derived_shape_present", "source_derived_motion_present", "bodyprint_matches_package",
    "source_count_matches_package", "recovery_provenance_matches", "avatar_fitting_provenance_present",
    "avatar_is_vrm_1_0", "runtime_materialized_from_package"
)
foreach ($checkName in $requiredChecks) {
    $property = $report.checks.PSObject.Properties[$checkName]
    if ($null -eq $property -or $property.Value -ne $true) { throw "Automated acceptance check is missing or false: checks.$checkName" }
}
foreach ($checkName in @("bodyprint_matches_proof", "source_count_matches", "recovery_provenance_matches", "avatar_fitting_provenance_present")) {
    $property = $report.package.PSObject.Properties[$checkName]
    if ($null -eq $property -or $property.Value -ne $true) { throw "Package acceptance check is missing or false: package.$checkName" }
}
if ([string]$report.package.vrm_spec_version -ne "1.0") { throw "Accepted package is not recorded as VRM 1.0." }
if ([string]$report.runtime.manifest -ne "runtime/runtime-manifest.json" -or $report.runtime.materialized_from_package -ne $true) {
    throw "Automated acceptance does not contain valid materialized runtime evidence."
}
$expectedRuntimeManifestHash = Require-LowerSha256 ([string]$report.runtime.manifest_sha256) "runtime.manifest_sha256"

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Could not read BodyRig Git HEAD." }
$acceptedRevision = ([string]$report.bodyrig_revision).ToLowerInvariant()
if ($acceptedRevision -notmatch '^[0-9a-f]{40}$' -or $head -ne $acceptedRevision) {
    throw "BodyRig HEAD no longer matches the accepted revision. Expected $($report.bodyrig_revision), got $head."
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; release attestation requires the exact clean accepted revision." }

$bodyId = [string]$report.package.body_id
if ([string]::IsNullOrWhiteSpace($bodyId) -or $bodyId -notmatch '^[a-z0-9æøå_-]{1,160}$') { throw "Acceptance report contains an invalid body id." }
$packagePath = Join-Path $reportDir "$bodyId.mrbody"
if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) { throw "Accepted .mrbody package not found beside report: $packagePath" }
$packagePath = (Resolve-Path -LiteralPath $packagePath).Path
$expectedPackageHash = Require-LowerSha256 ([string]$report.package.package_sha256) "package.package_sha256"
$actualPackageHash = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualPackageHash -ne $expectedPackageHash) { throw "Accepted .mrbody SHA-256 no longer matches automated acceptance." }
$reportHash = $automated.Hash

$checksums = Read-PackageChecksums -PackagePath $packagePath
$avatarChecksumProperty = $checksums.PSObject.Properties["avatar.vrm"]
$bodyprintChecksumProperty = $checksums.PSObject.Properties["bodyprint.json"]
if ($null -eq $avatarChecksumProperty -or $null -eq $bodyprintChecksumProperty) { throw "Accepted .mrbody checksums.json does not contain avatar/bodyprint hashes." }
$expectedAvatarHash = Require-LowerSha256 ([string]$avatarChecksumProperty.Value) "checksums.avatar.vrm"
$expectedBodyprintHash = Require-LowerSha256 ([string]$bodyprintChecksumProperty.Value) "checksums.bodyprint.json"

$windowsProbe = Read-RendererProbe -Path $WindowsProbeReport -ExpectedPlatform "windows-unity-univrm" -ExpectedPackageHash $actualPackageHash -ExpectedRuntimeManifestHash $expectedRuntimeManifestHash -ExpectedAvatarHash $expectedAvatarHash -ExpectedBodyprintHash $expectedBodyprintHash -ExpectedBodyId $bodyId
$questProbe = Read-RendererProbe -Path $QuestProbeReport -ExpectedPlatform "android-quest-class" -ExpectedPackageHash $actualPackageHash -ExpectedRuntimeManifestHash $expectedRuntimeManifestHash -ExpectedAvatarHash $expectedAvatarHash -ExpectedBodyprintHash $expectedBodyprintHash -ExpectedBodyId $bodyId
if ([string]::Equals($windowsProbe.Path, $questProbe.Path, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Windows and Quest machine probes must be distinct evidence files." }

$common = @{
    ExpectedRevision = $head
    ExpectedAutomatedReportHash = $reportHash
    ExpectedPackageHash = $actualPackageHash
    ExpectedRuntimeManifestHash = $expectedRuntimeManifestHash
    ExpectedAvatarHash = $expectedAvatarHash
    ExpectedBodyprintHash = $expectedBodyprintHash
    ExpectedBodyId = $bodyId
}
$windowsArgs = $common.Clone(); $windowsArgs.Path = $WindowsRendererReport; $windowsArgs.Probe = $windowsProbe; $windowsArgs.ExpectedPlatform = "windows-unity-univrm"
$windows = Read-RendererAcceptance @windowsArgs
$questArgs = $common.Clone(); $questArgs.Path = $QuestRendererReport; $questArgs.Probe = $questProbe; $questArgs.ExpectedPlatform = "android-quest-class"
$quest = Read-RendererAcceptance @questArgs
if ([string]::Equals($windows.Path, $quest.Path, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Windows and Quest renderer acceptance must be distinct evidence files." }

if ([string]::IsNullOrWhiteSpace($Output)) { $Output = Join-Path $reportDir "bodyrig-release-acceptance.json" }
$Output = [System.IO.Path]::GetFullPath($Output)
foreach ($evidencePath in @($AcceptanceReport, $packagePath, $windows.Path, $quest.Path, $windowsProbe.Path, $questProbe.Path)) {
    if ([string]::Equals($Output, $evidencePath, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Release output must not overwrite input evidence." }
}
if (Test-Path -LiteralPath $Output) { throw "Release acceptance output already exists; refusing to overwrite evidence: $Output" }
$outputDir = Split-Path -Parent $Output
if (-not (Test-Path -LiteralPath $outputDir -PathType Container)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }

function RendererSummary {
    param($Acceptance, $Probe)
    return [ordered]@{
        report_sha256 = $Acceptance.Hash
        probe_report_sha256 = $Probe.Hash
        runtime_manifest_sha256 = $expectedRuntimeManifestHash
        avatar_sha256 = $expectedAvatarHash
        bodyprint_sha256 = $expectedBodyprintHash
        machine_probe = $true
        result = "pass"
        renderer_name = [string]$Acceptance.Value.renderer_name
        renderer_version = [string]$Acceptance.Value.renderer_version
        unity_platform = [string]$Probe.Value.unity_platform
        unity_version = [string]$Probe.Value.unity_version
        graphics_device = [string]$Probe.Value.graphics_device
        quality_note = [string]$Acceptance.Value.quality_note
        observed_at = [string]$Probe.Value.observed_at
        attested_at = [string]$Acceptance.Value.attested_at
    }
}

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
        windows_unity_univrm = RendererSummary $windows $windowsProbe
        android_quest_class = RendererSummary $quest $questProbe
    }
    release_gate_pass = $true
    production_activation = $true
}

$temp = Join-Path $outputDir ("." + [System.IO.Path]::GetFileName($Output) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
try {
    $completed | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temp -Encoding UTF8
    $roundTrip = Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json
    if ($roundTrip.release_gate_pass -ne $true -or $roundTrip.production_activation -ne $true -or $roundTrip.renderer_acceptance.windows_unity_univrm.machine_probe -ne $true -or $roundTrip.renderer_acceptance.android_quest_class.machine_probe -ne $true) {
        throw "Release acceptance round-trip validation failed."
    }
    Move-Item -LiteralPath $temp -Destination $Output
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
}

Write-Host "BodyRig release acceptance: PASS"
Write-Host "Revision: $head"
Write-Host "Package SHA-256: $actualPackageHash"
Write-Host "Windows probe SHA-256: $($windowsProbe.Hash)"
Write-Host "Windows renderer evidence SHA-256: $($windows.Hash)"
Write-Host "Quest probe SHA-256: $($questProbe.Hash)"
Write-Host "Quest renderer evidence SHA-256: $($quest.Hash)"
Write-Host "Release report: $Output"
exit 0
