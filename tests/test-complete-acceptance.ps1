$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$SourceGate = (Resolve-Path (Join-Path $PSScriptRoot "../complete-acceptance.ps1")).Path
$SourceRecorder = (Resolve-Path (Join-Path $PSScriptRoot "../record-renderer-acceptance.ps1")).Path
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("bodyrig-release-gate-tests-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)][string]$Repo,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $output = @(& git -C $Repo @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return $output
}

function New-Fixture {
    param([Parameter(Mandatory = $true)][string]$Name)

    $repo = Join-Path $TempRoot "$Name-repo"
    $artifacts = Join-Path $TempRoot "$Name-artifacts"
    New-Item -ItemType Directory -Path $repo, $artifacts -Force | Out-Null
    Copy-Item -LiteralPath $SourceGate -Destination (Join-Path $repo "complete-acceptance.ps1")
    Copy-Item -LiteralPath $SourceRecorder -Destination (Join-Path $repo "record-renderer-acceptance.ps1")

    & git -C $repo init --quiet
    if ($LASTEXITCODE -ne 0) { throw "git init failed" }
    Invoke-Git $repo @("config", "user.email", "bodyrig-ci@example.invalid") | Out-Null
    Invoke-Git $repo @("config", "user.name", "BodyRig CI") | Out-Null
    Invoke-Git $repo @("add", "complete-acceptance.ps1", "record-renderer-acceptance.ps1") | Out-Null
    Invoke-Git $repo @("commit", "--quiet", "-m", "fixture") | Out-Null
    $headLines = @(Invoke-Git $repo @("rev-parse", "HEAD"))
    if ($headLines.Count -ne 1) { throw "fixture git rev-parse returned an unexpected number of lines" }
    $head = ([string]$headLines[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "fixture Git HEAD is invalid: $head" }

    $bodyId = "fixture-body"
    $packagePath = Join-Path $artifacts "$bodyId.mrbody"
    [System.IO.File]::WriteAllBytes(
        $packagePath,
        [System.Text.Encoding]::UTF8.GetBytes("BodyRig acceptance fixture: $Name")
    )
    $packageHash = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()

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
        ReportPath = $reportPath
        Report = $report
        PackagePath = $packagePath
        Head = $head
    }
}

function Save-Report {
    param([Parameter(Mandatory = $true)]$Fixture)
    $Fixture.Report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Fixture.ReportPath -Encoding UTF8
}

function Invoke-RendererRecord {
    param(
        [Parameter(Mandatory = $true)]$Fixture,
        [Parameter(Mandatory = $true)][ValidateSet("windows-unity-univrm", "android-quest-class")][string]$Platform,
        [Parameter(Mandatory = $true)][string]$Output,
        [string]$QualityNote = "Avatar loads correctly and proportions/motion are visually plausible.",
        [string]$RendererVersion = "fixture-renderer-1"
    )
    $arguments = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $Fixture.RecorderScript,
        "-AcceptanceReport", $Fixture.ReportPath,
        "-Platform", $Platform,
        "-Pass",
        "-RendererName", "BodyRig Reference Renderer",
        "-RendererVersion", $RendererVersion,
        "-QualityNote", $QualityNote,
        "-Output", $Output
    )
    $outputLines = @(& $Pwsh @arguments 2>&1)
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output = ($outputLines -join [Environment]::NewLine)
    }
}

function Assert-Success {
    param([Parameter(Mandatory = $true)]$Result, [Parameter(Mandatory = $true)][string]$Case)
    if ($Result.ExitCode -ne 0) {
        throw "$Case expected PASS, got exit $($Result.ExitCode): $($Result.Output)"
    }
}

function Assert-Failure {
    param([Parameter(Mandatory = $true)]$Result, [Parameter(Mandatory = $true)][string]$Case)
    if ($Result.ExitCode -eq 0) {
        throw "$Case expected FAIL, but gate returned success. Output: $($Result.Output)"
    }
}

function New-RendererPair {
    param([Parameter(Mandatory = $true)]$Fixture)
    $windowsPath = Join-Path $Fixture.Artifacts "windows-renderer.json"
    $questPath = Join-Path $Fixture.Artifacts "quest-renderer.json"
    Assert-Success (Invoke-RendererRecord $Fixture -Platform "windows-unity-univrm" -Output $windowsPath) "record Windows renderer"
    Assert-Success (Invoke-RendererRecord $Fixture -Platform "android-quest-class" -Output $questPath) "record Quest renderer"
    return [pscustomobject]@{ Windows = $windowsPath; Quest = $questPath }
}

function Invoke-Gate {
    param(
        [Parameter(Mandatory = $true)]$Fixture,
        [Parameter(Mandatory = $true)][string]$WindowsReport,
        [Parameter(Mandatory = $true)][string]$QuestReport,
        [string]$Output = ""
    )
    $arguments = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $Fixture.GateScript,
        "-AcceptanceReport", $Fixture.ReportPath,
        "-WindowsRendererReport", $WindowsReport,
        "-QuestRendererReport", $QuestReport
    )
    if (-not [string]::IsNullOrWhiteSpace($Output)) {
        $arguments += @("-Output", $Output)
    }
    $outputLines = @(& $Pwsh @arguments 2>&1)
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output = ($outputLines -join [Environment]::NewLine)
    }
}

try {
    $fixture = New-Fixture "pass"
    $renderer = New-RendererPair $fixture
    $releasePath = Join-Path $fixture.Artifacts "release.json"
    $result = Invoke-Gate $fixture -WindowsReport $renderer.Windows -QuestReport $renderer.Quest -Output $releasePath
    Assert-Success $result "valid evidence chain"
    $release = Get-Content -LiteralPath $releasePath -Raw | ConvertFrom-Json
    if ([string]$release.format -ne "bodyrig-release-acceptance" -or
        $release.release_gate_pass -ne $true -or
        $release.production_activation -ne $true -or
        [string]$release.bodyrig_revision -ne $fixture.Head -or
        [string]$release.renderer_acceptance.windows_unity_univrm.result -ne "pass" -or
        [string]$release.renderer_acceptance.android_quest_class.result -ne "pass" -or
        [string]$release.renderer_acceptance.windows_unity_univrm.report_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$release.renderer_acceptance.android_quest_class.report_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "valid release report failed round-trip assertions"
    }
    Write-Host "PASS: full automated + Windows + Quest evidence chain"

    $fixture = New-Fixture "blank-note"
    $blankPath = Join-Path $fixture.Artifacts "blank.json"
    Assert-Failure (Invoke-RendererRecord $fixture -Platform "windows-unity-univrm" -Output $blankPath -QualityNote "   ") "blank renderer quality note"
    Write-Host "PASS: blank renderer quality note is rejected"

    $fixture = New-Fixture "tampered-renderer-package"
    $renderer = New-RendererPair $fixture
    $quest = Get-Content -LiteralPath $renderer.Quest -Raw | ConvertFrom-Json
    $quest.package_sha256 = ("0" * 64)
    $quest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $renderer.Quest -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture -WindowsReport $renderer.Windows -QuestReport $renderer.Quest) "tampered renderer package binding"
    Write-Host "PASS: tampered renderer package binding is rejected"

    $fixture = New-Fixture "tampered-report-binding"
    $renderer = New-RendererPair $fixture
    $windows = Get-Content -LiteralPath $renderer.Windows -Raw | ConvertFrom-Json
    $windows.automated_report_sha256 = ("0" * 64)
    $windows | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $renderer.Windows -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture -WindowsReport $renderer.Windows -QuestReport $renderer.Quest) "tampered automated report binding"
    Write-Host "PASS: tampered automated-report binding is rejected"

    $fixture = New-Fixture "platform-swap"
    $renderer = New-RendererPair $fixture
    Assert-Failure (Invoke-Gate $fixture -WindowsReport $renderer.Quest -QuestReport $renderer.Windows) "platform-swapped evidence"
    Write-Host "PASS: platform-swapped evidence is rejected"

    $fixture = New-Fixture "missing-quest"
    $renderer = New-RendererPair $fixture
    Assert-Failure (Invoke-Gate $fixture -WindowsReport $renderer.Windows -QuestReport (Join-Path $fixture.Artifacts "missing.json")) "missing Quest report"
    Write-Host "PASS: missing Quest evidence is rejected"

    $fixture = New-Fixture "package-tamper"
    $renderer = New-RendererPair $fixture
    Add-Content -LiteralPath $fixture.PackagePath -Value "tamper" -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture -WindowsReport $renderer.Windows -QuestReport $renderer.Quest) "package tamper after renderer acceptance"
    Write-Host "PASS: post-attestation package tamper is rejected"

    $fixture = New-Fixture "failed-check"
    $fixture.Report.checks.preflight_ok = $false
    Save-Report $fixture
    $renderer = New-RendererPair $fixture
    Assert-Failure (Invoke-Gate $fixture -WindowsReport $renderer.Windows -QuestReport $renderer.Quest) "false automated check"
    Write-Host "PASS: false automated check is rejected by final gate"

    $fixture = New-Fixture "revision-mismatch"
    $renderer = New-RendererPair $fixture
    $fixture.Report.bodyrig_revision = ("0" * 40)
    Save-Report $fixture
    Assert-Failure (Invoke-Gate $fixture -WindowsReport $renderer.Windows -QuestReport $renderer.Quest) "revision mismatch"
    Write-Host "PASS: automated revision mutation is rejected"

    $fixture = New-Fixture "dirty-repo"
    $renderer = New-RendererPair $fixture
    Set-Content -LiteralPath (Join-Path $fixture.Repo "dirty.txt") -Value "dirty" -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture -WindowsReport $renderer.Windows -QuestReport $renderer.Quest) "dirty checkout"
    Write-Host "PASS: dirty checkout is rejected"

    $fixture = New-Fixture "output-collision"
    $renderer = New-RendererPair $fixture
    Assert-Failure (Invoke-Gate $fixture -WindowsReport $renderer.Windows -QuestReport $renderer.Quest -Output $fixture.ReportPath) "output collision"
    Write-Host "PASS: release evidence overwrite is rejected"

    Write-Host "BodyRig physical renderer + final acceptance gate tests: PASS"
    exit 0
} finally {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
