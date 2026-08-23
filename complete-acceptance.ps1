param(
    [Parameter(Mandatory = $true)]
    [string]$AcceptanceReport,

    [Parameter(Mandatory = $true)]
    [string]$WindowsRendererReport,

    [Parameter(Mandatory = $true)]
    [string]$QuestRendererReport,

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

function Read-RendererAcceptance {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedPlatform,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$ExpectedAutomatedReportHash,
        [Parameter(Mandatory = $true)][string]$ExpectedPackageHash,
        [Parameter(Mandatory = $true)][string]$ExpectedRuntimeManifestHash,
        [Parameter(Mandatory = $true)][string]$ExpectedAvatarHash,
        [Parameter(Mandatory = $true)][string]$ExpectedBodyprintHash,
        [Parameter(Mandatory = $true)][string]$ExpectedBodyId
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Renderer acceptance report not found: $Path"
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    try {
        $value = Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json
    } catch {
        throw "Renderer acceptance report is not valid JSON: $resolved"
    }
    if ([string]$value.format -ne "bodyrig-renderer-acceptance" -or [int]$value.version -ne 1) {
        throw "Unsupported renderer acceptance format/version: $resolved"
    }
    if ([string]$value.platform -ne $ExpectedPlatform) {
        throw "Renderer acceptance platform mismatch. Expected $ExpectedPlatform, got $($value.platform)."
    }
    if ([string]$value.result -ne "pass" -or [string]$value.attestation -ne "operator-supplied" -or $value.production_activation -ne $false) {
        throw "Renderer acceptance is not a valid non-activating PASS attestation: $resolved"
    }
    if (([string]$value.bodyrig_revision).ToLowerInvariant() -ne $ExpectedRevision) {
        throw "Renderer acceptance revision does not match automated acceptance: $resolved"
    }
    if (([string]$value.automated_report_sha256).ToLowerInvariant() -ne $ExpectedAutomatedReportHash) {
        throw "Renderer acceptance is bound to a different automated acceptance report: $resolved"
    }
    if (([string]$value.package_sha256).ToLowerInvariant() -ne $ExpectedPackageHash) {
        throw "Renderer acceptance is bound to a different .mrbody package: $resolved"
    }
    if (([string]$value.runtime_manifest_sha256).ToLowerInvariant() -ne $ExpectedRuntimeManifestHash) {
        throw "Renderer acceptance is bound to a different materialized runtime manifest: $resolved"
    }
    if (([string]$value.avatar_sha256).ToLowerInvariant() -ne $ExpectedAvatarHash) {
        throw "Renderer acceptance avatar hash does not match the accepted .mrbody payload: $resolved"
    }
    if (([string]$value.bodyprint_sha256).ToLowerInvariant() -ne $ExpectedBodyprintHash) {
        throw "Renderer acceptance bodyprint hash does not match the accepted .mrbody payload: $resolved"
    }
    if ([string]$value.body_id -ne $ExpectedBodyId) {
        throw "Renderer acceptance body id does not match automated acceptance: $resolved"
    }
    foreach ($fieldName in @("renderer_name", "renderer_version", "quality_note", "attested_at")) {
        $property = $value.PSObject.Properties[$fieldName]
        if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            throw "Renderer acceptance is missing required evidence field '$fieldName': $resolved"
        }
    }
    return [pscustomobject]@{
        Path = $resolved
        Hash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
        Value = $value
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
    "avatar_is_vrm_1_0",
    "runtime_materialized_from_package"
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
if ([string]$report.runtime.manifest -ne "runtime/runtime-manifest.json" -or $report.runtime.materialized_from_package -ne $true) {
    throw "Automated acceptance does not contain valid materialized runtime evidence."
}
$expectedRuntimeManifestHash = ([string]$report.runtime.manifest_sha256).ToLowerInvariant()
if ($expectedRuntimeManifestHash -notmatch '^[0-9a-f]{64}$') {
    throw "Automated acceptance runtime manifest hash is invalid."
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

$checksums = Read-PackageChecksums -PackagePath $packagePath
$avatarChecksumProperty = $checksums.PSObject.Properties["avatar.vrm"]
$bodyprintChecksumProperty = $checksums.PSObject.Properties["bodyprint.json"]
if ($null -eq $avatarChecksumProperty -or $null -eq $bodyprintChecksumProperty) {
    throw "Accepted .mrbody checksums.json does not contain avatar/bodyprint hashes."
}
$expectedAvatarHash = ([string]$avatarChecksumProperty.Value).ToLowerInvariant()
$expectedBodyprintHash = ([string]$bodyprintChecksumProperty.Value).ToLowerInvariant()
if ($expectedAvatarHash -notmatch '^[0-9a-f]{64}$' -or $expectedBodyprintHash -notmatch '^[0-9a-f]{64}$') {
    throw "Accepted .mrbody contains invalid avatar/bodyprint checksums."
}

$commonRendererArguments = @{
    ExpectedRevision = $head
    ExpectedAutomatedReportHash = $reportHash
    ExpectedPackageHash = $actualPackageHash
    ExpectedRuntimeManifestHash = $expectedRuntimeManifestHash
    ExpectedAvatarHash = $expectedAvatarHash
    ExpectedBodyprintHash = $expectedBodyprintHash
    ExpectedBodyId = $bodyId
}
$windowsArguments = $commonRendererArguments.Clone()
$windowsArguments.Path = $WindowsRendererReport
$windowsArguments.ExpectedPlatform = "windows-unity-univrm"
$windows = Read-RendererAcceptance @windowsArguments
$questArguments = $commonRendererArguments.Clone()
$questArguments.Path = $QuestRendererReport
$questArguments.ExpectedPlatform = "android-quest-class"
$quest = Read-RendererAcceptance @questArguments
if ([string]::Equals($windows.Path, $quest.Path, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Windows and Quest renderer acceptance must be two distinct evidence files."
}

if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $reportDir "bodyrig-release-acceptance.json"
}
$Output = [System.IO.Path]::GetFullPath($Output)
foreach ($evidencePath in @($AcceptanceReport, $packagePath, $windows.Path, $quest.Path)) {
    if ([string]::Equals($Output, $evidencePath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Release output must not overwrite input evidence."
    }
}
if (Test-Path -LiteralPath $Output) {
    throw "Release acceptance output already exists; refusing to overwrite evidence: $Output"
}
$outputDir = Split-Path -Parent $Output
if (-not (Test-Path -LiteralPath $outputDir -PathType Container)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
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
        windows_unity_univrm = [ordered]@{
            report_sha256 = $windows.Hash
            runtime_manifest_sha256 = $expectedRuntimeManifestHash
            avatar_sha256 = $expectedAvatarHash
            bodyprint_sha256 = $expectedBodyprintHash
            result = "pass"
            renderer_name = [string]$windows.Value.renderer_name
            renderer_version = [string]$windows.Value.renderer_version
            quality_note = [string]$windows.Value.quality_note
            attested_at = [string]$windows.Value.attested_at
        }
        android_quest_class = [ordered]@{
            report_sha256 = $quest.Hash
            runtime_manifest_sha256 = $expectedRuntimeManifestHash
            avatar_sha256 = $expectedAvatarHash
            bodyprint_sha256 = $expectedBodyprintHash
            result = "pass"
            renderer_name = [string]$quest.Value.renderer_name
            renderer_version = [string]$quest.Value.renderer_version
            quality_note = [string]$quest.Value.quality_note
            attested_at = [string]$quest.Value.attested_at
        }
    }
    release_gate_pass = $true
    production_activation = $true
}

$temp = Join-Path $outputDir ("." + [System.IO.Path]::GetFileName($Output) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
try {
    $completed | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temp -Encoding UTF8
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
Write-Host "Runtime manifest SHA-256: $expectedRuntimeManifestHash"
Write-Host "Avatar SHA-256: $expectedAvatarHash"
Write-Host "Windows renderer evidence SHA-256: $($windows.Hash)"
Write-Host "Quest renderer evidence SHA-256: $($quest.Hash)"
Write-Host "Release report: $Output"
exit 0
