$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$SourceGate = (Resolve-Path (Join-Path $PSScriptRoot "../complete-acceptance.ps1")).Path
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

    & git -C $repo init --quiet
    if ($LASTEXITCODE -ne 0) { throw "git init failed" }
    Invoke-Git $repo @("config", "user.email", "bodyrig-ci@example.invalid") | Out-Null
    Invoke-Git $repo @("config", "user.name", "BodyRig CI") | Out-Null
    Invoke-Git $repo @("add", "complete-acceptance.ps1") | Out-Null
    Invoke-Git $repo @("commit", "--quiet", "-m", "fixture") | Out-Null
    $head = ([string](Invoke-Git $repo @("rev-parse", "HEAD"))[0]).Trim().ToLowerInvariant()

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
        Script = Join-Path $repo "complete-acceptance.ps1"
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

function Invoke-Gate {
    param(
        [Parameter(Mandatory = $true)]$Fixture,
        [bool]$Windows = $true,
        [bool]$Quest = $true,
        [string]$QualityNote = "Avatar loads correctly and proportions/motion are visually plausible.",
        [string]$Output = ""
    )
    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        $Fixture.Script,
        "-AcceptanceReport",
        $Fixture.ReportPath
    )
    if ($Windows) { $arguments += "-WindowsRendererPass" }
    if ($Quest) { $arguments += "-QuestRendererPass" }
    $arguments += @("-QualityNote", $QualityNote)
    if (-not [string]::IsNullOrWhiteSpace($Output)) {
        $arguments += @("-Output", $Output)
    }
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

try {
    $fixture = New-Fixture "pass"
    $releasePath = Join-Path $fixture.Artifacts "release.json"
    $result = Invoke-Gate $fixture -Output $releasePath
    Assert-Success $result "valid attestation"
    if (-not (Test-Path -LiteralPath $releasePath -PathType Leaf)) {
        throw "valid attestation did not create release report"
    }
    $release = Get-Content -LiteralPath $releasePath -Raw | ConvertFrom-Json
    if ([string]$release.format -ne "bodyrig-release-acceptance" -or
        $release.release_gate_pass -ne $true -or
        $release.production_activation -ne $true -or
        [string]$release.bodyrig_revision -ne $fixture.Head -or
        [string]$release.renderer_acceptance.windows_unity_univrm -ne "pass" -or
        [string]$release.renderer_acceptance.android_quest_class -ne "pass") {
        throw "valid release report failed round-trip assertions"
    }
    Write-Host "PASS: valid dual-renderer attestation"

    $fixture = New-Fixture "hash-mismatch"
    $fixture.Report.package.package_sha256 = ("0" * 64)
    Save-Report $fixture
    Assert-Failure (Invoke-Gate $fixture) "package hash mismatch"
    Write-Host "PASS: package hash mismatch is rejected"

    $fixture = New-Fixture "revision-mismatch"
    $fixture.Report.bodyrig_revision = ("0" * 40)
    Save-Report $fixture
    Assert-Failure (Invoke-Gate $fixture) "revision mismatch"
    Write-Host "PASS: revision mismatch is rejected"

    $fixture = New-Fixture "missing-quest"
    Assert-Failure (Invoke-Gate $fixture -Quest:$false) "missing Quest attestation"
    Write-Host "PASS: missing Quest attestation is rejected"

    $fixture = New-Fixture "blank-note"
    Assert-Failure (Invoke-Gate $fixture -QualityNote "   ") "blank quality note"
    Write-Host "PASS: blank quality note is rejected"

    $fixture = New-Fixture "failed-check"
    $fixture.Report.checks.preflight_ok = $false
    Save-Report $fixture
    Assert-Failure (Invoke-Gate $fixture) "false automated check"
    Write-Host "PASS: false automated check is rejected"

    $fixture = New-Fixture "dirty-repo"
    Set-Content -LiteralPath (Join-Path $fixture.Repo "dirty.txt") -Value "dirty" -Encoding UTF8
    Assert-Failure (Invoke-Gate $fixture) "dirty checkout"
    Write-Host "PASS: dirty checkout is rejected"

    $fixture = New-Fixture "output-collision"
    Assert-Failure (Invoke-Gate $fixture -Output $fixture.ReportPath) "output collision"
    Write-Host "PASS: evidence overwrite is rejected"

    Write-Host "BodyRig final acceptance gate tests: PASS"
    exit 0
} finally {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
