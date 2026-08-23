$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Add-Type -AssemblyName System.IO.Compression.FileSystem

$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$SourceGate = (Resolve-Path (Join-Path $PSScriptRoot "../complete-acceptance.ps1")).Path
$SourceRecorder = (Resolve-Path (Join-Path $PSScriptRoot "../record-renderer-acceptance.ps1")).Path
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("bodyrig-release-gate-tests-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string]$Repo, [Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = @(& git -C $Repo @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)" }
    return $output
}

function Get-ByteHash {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($Bytes)
        return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Add-ZipEntry {
    param([Parameter(Mandatory = $true)]$Archive, [Parameter(Mandatory = $true)][string]$Name, [Parameter(Mandatory = $true)][byte[]]$Bytes)
    $entry = $Archive.CreateEntry($Name, [System.IO.Compression.CompressionLevel]::Optimal)
    $stream = $entry.Open()
    try { $stream.Write($Bytes, 0, $Bytes.Length) } finally { $stream.Dispose() }
}

function Assert-Success {
    param([Parameter(Mandatory = $true)]$Result, [Parameter(Mandatory = $true)][string]$Case)
    if ($Result.ExitCode -ne 0) { throw "$Case expected PASS, got exit $($Result.ExitCode): $($Result.Output)" }
}

function Assert-Failure {
    param([Parameter(Mandatory = $true)]$Result, [Parameter(Mandatory = $true)][string]$Case)
    if ($Result.ExitCode -eq 0) { throw "$Case expected FAIL, but gate returned success. Output: $($Result.Output)" }
}

function New-Fixture {
    param([Parameter(Mandatory = $true)][string]$Name)

    $repo = Join-Path $TempRoot "$Name-repo"
    $artifacts = Join-Path $TempRoot "$Name-artifacts"
    $runtimeDir = Join-Path $artifacts "runtime"
    New-Item -ItemType Directory -Path $repo, $artifacts, $runtimeDir -Force | Out-Null
    Copy-Item -LiteralPath $SourceGate -Destination (Join-Path $repo "complete-acceptance.ps1")
    Copy-Item -LiteralPath $SourceRecorder -Destination (Join-Path $repo "record-renderer-acceptance.ps1")

    & git -C $repo init --quiet
    if ($LASTEXITCODE -ne 0) { throw "git init failed" }
    Invoke-Git $repo @("config", "user.email", "bodyrig-ci@example.invalid") | Out-Null
    Invoke-Git $repo @("config", "user.name", "BodyRig CI") | Out-Null
    Invoke-Git $repo @("add", "complete-acceptance.ps1", "record-renderer-acceptance.ps1") | Out-Null
    Invoke-Git $repo @("commit", "--quiet", "-m", "fixture") | Out-Null
    $head = ([string]@(Invoke-Git $repo @("rev-parse", "HEAD"))[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "fixture Git HEAD is invalid: $head" }

    $bodyId = "fixture-body"
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $avatarBytes = $utf8.GetBytes("fixture-avatar-vrm-bytes-$Name")
    $bodyprintBytes = $utf8.GetBytes('{"format":"modelrig-bodyprint","version":1,"shape":{"shoulder_to_height":0.24}}')
    $provenanceBytes = $utf8.GetBytes('{"format":"modelrig-body-provenance","version":1}')
    $thumbnailBytes = [byte[]](0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,0x66,0x69,0x78)
    $avatarHash = Get-ByteHash $avatarBytes
    $bodyprintHash = Get-ByteHash $bodyprintBytes

    $checksums = [ordered]@{
        "avatar.vrm" = $avatarHash
        "bodyprint.json" = $bodyprintHash
        "provenance.json" = Get-ByteHash $provenanceBytes
        "thumbnail.png" = Get-ByteHash $thumbnailBytes
    }
    $manifestBytes = $utf8.GetBytes('{"format":"modelrig-body","format_version":1,"id":"fixture-body"}')
    $checksumsBytes = $utf8.GetBytes(($checksums | ConvertTo-Json -Compress))

    $packagePath = Join-Path $artifacts "$bodyId.mrbody"
    $archive = [System.IO.Compression.ZipFile]::Open($packagePath, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        Add-ZipEntry $archive "manifest.json" $manifestBytes
        Add-ZipEntry $archive "checksums.json" $checksumsBytes
        Add-ZipEntry $archive "avatar.vrm" $avatarBytes
        Add-ZipEntry $archive "bodyprint.json" $bodyprintBytes
        Add-ZipEntry $archive "provenance.json" $provenanceBytes
        Add-ZipEntry $archive "thumbnail.png" $thumbnailBytes
    } finally { $archive.Dispose() }
    $packageHash = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()

    [System.IO.File]::WriteAllBytes((Join-Path $runtimeDir "avatar.vrm"), $avatarBytes)
    [System.IO.File]::WriteAllBytes((Join-Path $runtimeDir "bodyprint.json"), $bodyprintBytes)
    [System.IO.File]::WriteAllBytes((Join-Path $runtimeDir "provenance.json"), $provenanceBytes)
    [System.IO.File]::WriteAllBytes((Join-Path $runtimeDir "thumbnail.png"), $thumbnailBytes)
    $runtimeManifest = [ordered]@{
        format = "bodyrig-runtime-assets"
        version = 1
        body_id = $bodyId
        body_name = "Fixture Body"
        package_sha256 = $packageHash
        avatar = "avatar.vrm"
        bodyprint = "bodyprint.json"
        payloads = @("avatar.vrm", "bodyprint.json", "provenance.json", "thumbnail.png")
    }
    $runtimeManifestPath = Join-Path $runtimeDir "runtime-manifest.json"
    $runtimeManifest | ConvertTo-Json -Depth 8 -Compress | Set-Content -LiteralPath $runtimeManifestPath -Encoding UTF8
    $runtimeManifestHash = (Get-FileHash -LiteralPath $runtimeManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()

    $checks = [ordered]@{
        bodyrig_checkout_clean = $true
        preflight_ok = $true
        recovery_adapter_pinned = $true
        observed_frames_ge_2 = $true
        source_derived_shape_present = $true
        source_derived_motion_present = $true
        bodyprint_matches_package = $true
        source_count_matches_package = $true
        recovery_provenance_matches = $true
        avatar_fitting_provenance_present = $true
        avatar_is_vrm_1_0 = $true
        runtime_materialized_from_package = $true
    }
    $report = [ordered]@{
        format = "bodyrig-rig-acceptance"
        version = 1
        created_at = [DateTime]::UtcNow.ToString("o")
        bodyrig_revision = $head
        bodyrig_checkout_clean = $true
        source_count = 1
        recovery = [ordered]@{
            adapter = "4dhumans-hmr2-phalp"
            revision = "fixture-pinned"
            track_id = "track-1"
            observed_frames = 120
        }
        package = [ordered]@{
            package_sha256 = $packageHash
            body_id = $bodyId
            body_name = "Fixture Body"
            payload_names = @("avatar.vrm", "bodyprint.json", "provenance.json", "thumbnail.png")
            bodyprint_matches_proof = $true
            source_count_matches = $true
            recovery_provenance_matches = $true
            avatar_fitting_provenance_present = $true
            vrm_spec_version = "1.0"
            placeholder_avatar = $true
        }
        runtime = [ordered]@{
            manifest = "runtime/runtime-manifest.json"
            manifest_sha256 = $runtimeManifestHash
            materialized_from_package = $true
        }
        checks = $checks
        automated_pass = $true
        physical_renderer_acceptance = "pending"
        production_activation = $false
    }
    $reportPath = Join-Path $artifacts "bodyrig-acceptance.json"
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding UTF8

    return [pscustomobject]@{
        Repo = $repo
        GateScript = Join-Path $repo "complete-acceptance.ps1"
        RecorderScript = Join-Path $repo "record-renderer-acceptance.ps1"
        Artifacts = $artifacts
        RuntimeDir = $runtimeDir
        RuntimeManifestPath = $runtimeManifestPath
        RuntimeManifestHash = $runtimeManifestHash
        ReportPath = $reportPath
        Report = $report
        PackagePath = $packagePath
        PackageHash = $packageHash
        AvatarHash = $avatarHash
        BodyprintHash = $bodyprintHash
        BodyId = $bodyId
        Head = $head
    }
}

function Save-Report {
    param([Parameter(Mandatory = $true)]$Fixture)
    $Fixture.Report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Fixture.ReportPath -Encoding UTF8
}

function New-Probe {
    param(
        [Parameter(Mandatory = $true)]$Fixture,
        [Parameter(Mandatory = $true)][ValidateSet("windows-unity-univrm", "android-quest-class")][string]$Platform,
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$RendererVersion = "fixture-renderer-1"
    )
    $unityPlatform = if ($Platform -eq "windows-unity-univrm") { "WindowsPlayer" } else { "Android" }
    $probe = [ordered]@{
        format = "bodyrig-renderer-probe"
        version = 1
        observed_at = [DateTime]::UtcNow.ToString("o")
        platform = $Platform
        unity_platform = $unityPlatform
        unity_version = "2022.3-fixture"
        graphics_device = "Fixture GPU"
        body_id = $Fixture.BodyId
        package_sha256 = $Fixture.PackageHash
        runtime_manifest_sha256 = $Fixture.RuntimeManifestHash
        avatar_sha256 = $Fixture.AvatarHash
        bodyprint_sha256 = $Fixture.BodyprintHash
        vrm10_loaded = $true
        humanoid_valid = $true
        required_bones_valid = $true
        active_renderer = [ordered]@{
            name = "BodyRig Reference Renderer"
            version = $RendererVersion
        }
    }
    $probe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
    return $Path
}

function Invoke-RendererRecord {
    param(
        [Parameter(Mandatory = $true)]$Fixture,
        [Parameter(Mandatory = $true)][ValidateSet("windows-unity-univrm", "android-quest-class")][string]$Platform,
        [Parameter(Mandatory = $true)][string]$ProbePath,
        [Parameter(Mandatory = $true)][string]$Output,
        [string]$QualityNote = "Avatar loads correctly and proportions/motion are visually plausible.",
        [string]$RendererVersion = "fixture-renderer-1"
    )
    $arguments = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $Fixture.RecorderScript,
        "-AcceptanceReport", $Fixture.ReportPath,
        "-RuntimeManifest", $Fixture.RuntimeManifestPath,
        "-ProbeReport", $ProbePath,
        "-Platform", $Platform,
        "-Pass",
        "-RendererName", "BodyRig Reference Renderer",
        "-RendererVersion", $RendererVersion,
        "-QualityNote", $QualityNote,
        "-Output", $Output
    )
    $outputLines = @(& $Pwsh @arguments 2>&1)
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = ($outputLines -join [Environment]::NewLine) }
}

function New-RendererPair {
    param([Parameter(Mandatory = $true)]$Fixture)
    $windowsProbe = New-Probe $Fixture "windows-unity-univrm" (Join-Path $Fixture.Artifacts "windows-probe.json")
    $questProbe = New-Probe $Fixture "android-quest-class" (Join-Path $Fixture.Artifacts "quest-probe.json")
    $windowsPath = Join-Path $Fixture.Artifacts "windows-renderer.json"
    $questPath = Join-Path $Fixture.Artifacts "quest-renderer.json"
    Assert-Success (Invoke-RendererRecord $Fixture "windows-unity-univrm" $windowsProbe $windowsPath) "record Windows renderer"
    Assert-Success (Invoke-RendererRecord $Fixture "android-quest-class" $questProbe $questPath) "record Quest renderer"
    return [pscustomobject]@{ Windows = $windowsPath; WindowsProbe = $windowsProbe; Quest = $questPath; QuestProbe = $questProbe }
}

function Invoke-Gate {
    param(
        [Parameter(Mandatory = $true)]$Fixture,
        [Parameter(Mandatory = $true)][string]$WindowsReport,
        [Parameter(Mandatory = $true)][string]$WindowsProbe,
        [Parameter(Mandatory = $true)][string]$QuestReport,
        [Parameter(Mandatory = $true)][string]$QuestProbe,
        [string]$Output = ""
    )
    $arguments = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $Fixture.GateScript,
        "-AcceptanceReport", $Fixture.ReportPath,
        "-WindowsRendererReport", $WindowsReport,
        "-WindowsProbeReport", $WindowsProbe,
        "-QuestRendererReport", $QuestReport,
        "-QuestProbeReport", $QuestProbe
    )
    if (-not [string]::IsNullOrWhiteSpace($Output)) { $arguments += @("-Output", $Output) }
    $outputLines = @(& $Pwsh @arguments 2>&1)
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = ($outputLines -join [Environment]::NewLine) }
}

try {
    $fixture = New-Fixture "pass"
    $renderer = New-RendererPair $fixture
    $releasePath = Join-Path $fixture.Artifacts "release.json"
    $result = Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Quest $renderer.QuestProbe $releasePath
    Assert-Success $result "valid machine-probe-bound evidence chain"
    $release = Get-Content -LiteralPath $releasePath -Raw | ConvertFrom-Json
    if ([string]$release.format -ne "bodyrig-release-acceptance" -or
        $release.release_gate_pass -ne $true -or
        $release.production_activation -ne $true -or
        [string]$release.bodyrig_revision -ne $fixture.Head -or
        $release.renderer_acceptance.windows_unity_univrm.machine_probe -ne $true -or
        $release.renderer_acceptance.android_quest_class.machine_probe -ne $true -or
        [string]$release.renderer_acceptance.windows_unity_univrm.probe_report_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$release.renderer_acceptance.android_quest_class.probe_report_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "valid release report failed machine-probe round-trip assertions"
    }
    Write-Host "PASS: package -> runtime -> machine probes -> operator attestations -> release chain"

    $fixture = New-Fixture "blank-note"
    $probe = New-Probe $fixture "windows-unity-univrm" (Join-Path $fixture.Artifacts "probe.json")
    Assert-Failure (Invoke-RendererRecord $fixture "windows-unity-univrm" $probe (Join-Path $fixture.Artifacts "blank.json") -QualityNote "   ") "blank renderer quality note"
    Write-Host "PASS: blank renderer quality note is rejected"

    $fixture = New-Fixture "probe-platform-mismatch"
    $probe = New-Probe $fixture "android-quest-class" (Join-Path $fixture.Artifacts "probe.json")
    Assert-Failure (Invoke-RendererRecord $fixture "windows-unity-univrm" $probe (Join-Path $fixture.Artifacts "windows.json")) "probe platform mismatch"
    Write-Host "PASS: machine probe cannot be relabelled as another platform"

    $fixture = New-Fixture "probe-avatar-mismatch"
    $probePath = New-Probe $fixture "windows-unity-univrm" (Join-Path $fixture.Artifacts "probe.json")
    $probe = Get-Content -LiteralPath $probePath -Raw | ConvertFrom-Json
    $probe.avatar_sha256 = ("0" * 64)
    $probe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $probePath -Encoding UTF8
    Assert-Failure (Invoke-RendererRecord $fixture "windows-unity-univrm" $probePath (Join-Path $fixture.Artifacts "windows.json")) "probe avatar mismatch"
    Write-Host "PASS: machine probe must identify the accepted avatar bytes"

    $fixture = New-Fixture "runtime-avatar-tamper"
    $probe = New-Probe $fixture "windows-unity-univrm" (Join-Path $fixture.Artifacts "probe.json")
    Add-Content -LiteralPath (Join-Path $fixture.RuntimeDir "avatar.vrm") -Value "tamper" -Encoding UTF8
    Assert-Failure (Invoke-RendererRecord $fixture "windows-unity-univrm" $probe (Join-Path $fixture.Artifacts "windows.json")) "runtime avatar tamper"
    Write-Host "PASS: substituted runtime avatar is rejected before attestation"

    $fixture = New-Fixture "runtime-manifest-tamper"
    $probe = New-Probe $fixture "windows-unity-univrm" (Join-Path $fixture.Artifacts "probe.json")
    $runtime = Get-Content -LiteralPath $fixture.RuntimeManifestPath -Raw | ConvertFrom-Json
    $runtime.body_name = "Tampered Name"
    $runtime | ConvertTo-Json -Depth 8 -Compress | Set-Content -LiteralPath $fixture.RuntimeManifestPath -Encoding UTF8
    Assert-Failure (Invoke-RendererRecord $fixture "windows-unity-univrm" $probe (Join-Path $fixture.Artifacts "windows.json")) "runtime manifest tamper"
    Write-Host "PASS: modified runtime manifest is rejected against Gate A hash"

    $fixture = New-Fixture "probe-tamper-after-attestation"
    $renderer = New-RendererPair $fixture
    $probe = Get-Content -LiteralPath $renderer.QuestProbe -Raw | ConvertFrom-Json
    $probe.graphics_device = "Substituted GPU"
    $probe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $renderer.QuestProbe -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Quest $renderer.QuestProbe) "probe tamper after attestation"
    Write-Host "PASS: final gate re-hashes original machine probes"

    $fixture = New-Fixture "tampered-renderer-package"
    $renderer = New-RendererPair $fixture
    $quest = Get-Content -LiteralPath $renderer.Quest -Raw | ConvertFrom-Json
    $quest.package_sha256 = ("0" * 64)
    $quest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $renderer.Quest -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Quest $renderer.QuestProbe) "tampered renderer package binding"
    Write-Host "PASS: tampered renderer package binding is rejected"

    $fixture = New-Fixture "tampered-runtime-binding"
    $renderer = New-RendererPair $fixture
    $windows = Get-Content -LiteralPath $renderer.Windows -Raw | ConvertFrom-Json
    $windows.runtime_manifest_sha256 = ("0" * 64)
    $windows | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $renderer.Windows -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Quest $renderer.QuestProbe) "tampered runtime binding"
    Write-Host "PASS: tampered renderer runtime binding is rejected"

    $fixture = New-Fixture "platform-swap"
    $renderer = New-RendererPair $fixture
    Assert-Failure (Invoke-Gate $fixture $renderer.Quest $renderer.QuestProbe $renderer.Windows $renderer.WindowsProbe) "platform-swapped evidence"
    Write-Host "PASS: platform-swapped machine/operator evidence is rejected"

    $fixture = New-Fixture "same-report"
    $renderer = New-RendererPair $fixture
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Windows $renderer.WindowsProbe) "same evidence for both platforms"
    Write-Host "PASS: one machine/operator evidence pair cannot satisfy both platforms"

    $fixture = New-Fixture "missing-quest"
    $renderer = New-RendererPair $fixture
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe (Join-Path $fixture.Artifacts "missing.json") $renderer.QuestProbe) "missing Quest report"
    Write-Host "PASS: missing Quest operator evidence is rejected"

    $fixture = New-Fixture "package-tamper"
    $renderer = New-RendererPair $fixture
    Add-Content -LiteralPath $fixture.PackagePath -Value "tamper" -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Quest $renderer.QuestProbe) "package tamper after renderer acceptance"
    Write-Host "PASS: post-attestation package tamper is rejected"

    $fixture = New-Fixture "failed-check"
    $renderer = New-RendererPair $fixture
    $fixture.Report.checks.preflight_ok = $false
    Save-Report $fixture
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Quest $renderer.QuestProbe) "false automated check"
    Write-Host "PASS: false automated check is rejected by final gate"

    $fixture = New-Fixture "revision-mismatch"
    $renderer = New-RendererPair $fixture
    $fixture.Report.bodyrig_revision = ("0" * 40)
    Save-Report $fixture
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Quest $renderer.QuestProbe) "revision mismatch"
    Write-Host "PASS: automated revision mutation is rejected"

    $fixture = New-Fixture "dirty-repo"
    $renderer = New-RendererPair $fixture
    Set-Content -LiteralPath (Join-Path $fixture.Repo "dirty.txt") -Value "dirty" -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Quest $renderer.QuestProbe) "dirty checkout"
    Write-Host "PASS: dirty checkout is rejected"

    $fixture = New-Fixture "output-collision"
    $renderer = New-RendererPair $fixture
    Assert-Failure (Invoke-Gate $fixture $renderer.Windows $renderer.WindowsProbe $renderer.Quest $renderer.QuestProbe $fixture.ReportPath) "output collision"
    Write-Host "PASS: release evidence overwrite is rejected"

    Write-Host "BodyRig machine-probe-bound runtime + renderer + final release gate tests: PASS"
    exit 0
} finally {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
