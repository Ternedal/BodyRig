$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$SourceGate = (Resolve-Path (Join-Path $PSScriptRoot "../run-physical-gate.ps1")).Path
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("bodyrig-physical-gate-tests-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

$FourDRevision = "efe18deff163b29dff87ddbd575fa29b716a356c"
$PhalpRevision = "96f7e6c09fb858ec3f597d59246c151ab4394bc3"
$SmplFileName = "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl"

function Assert-Success {
    param($Result, [string]$Case)
    if ($Result.ExitCode -ne 0) { throw "$Case expected PASS, got exit $($Result.ExitCode): $($Result.Output)" }
}
function Assert-Failure {
    param($Result, [string]$Case)
    if ($Result.ExitCode -eq 0) { throw "$Case expected FAIL, but gate returned success. Output: $($Result.Output)" }
}

function New-Fixture {
    param([Parameter(Mandatory = $true)][string]$Name)

    $fixtureRoot = Join-Path $TempRoot $Name
    $repo = Join-Path $fixtureRoot "repo"
    $recovery = Join-Path $fixtureRoot "recovery"
    $envDir = Join-Path $recovery "conda-env"
    $fourD = Join-Path $recovery "4D-Humans"
    $phalp = Join-Path $recovery "PHALP"
    $smplDir = Join-Path $fourD "data"
    $output = Join-Path $fixtureRoot "out"
    New-Item -ItemType Directory -Path $repo, $recovery, $envDir, $fourD, $phalp, $smplDir -Force | Out-Null

    Copy-Item -LiteralPath $SourceGate -Destination (Join-Path $repo "run-physical-gate.ps1")
    $externalPython = Join-Path $envDir "python.exe"
    $smplPath = Join-Path $smplDir $SmplFileName
    Set-Content -LiteralPath $externalPython -Value "fixture-python" -Encoding UTF8
    Set-Content -LiteralPath $smplPath -Value "fixture-smpl" -Encoding UTF8

    $stub = @'
param(
    [string[]]$Source,
    [string]$ExternalPython,
    [string]$FourDHumansRepo,
    [string]$TrackId = "",
    [string]$BodyId = "",
    [string]$Name = "",
    [string]$BodyRigPython = "",
    [string]$OutputDir = "",
    [switch]$AllowCpu
)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($OutputDir)) { throw "fixture requires OutputDir" }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
[ordered]@{
    source = @($Source)
    external_python = $ExternalPython
    four_d_humans_repo = $FourDHumansRepo
    track_id = $TrackId
    body_id = $BodyId
    name = $Name
    bodyrig_python = $BodyRigPython
    allow_cpu = [bool]$AllowCpu
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDir "capture.json") -Encoding UTF8
exit 0
'@
    Set-Content -LiteralPath (Join-Path $repo "validate-rig.ps1") -Value $stub -Encoding UTF8

    $summary = [ordered]@{
        format = "bodyrig-recovery-environment"
        version = 1
        root = $recovery
        external_python = $externalPython
        four_d_humans_repo = $fourD
        four_d_humans_revision = $FourDRevision
        phalp_repo = $phalp
        phalp_revision = $PhalpRevision
        smpl_expected_path = $smplPath
        smpl_present = $true
    }
    $summaryPath = Join-Path $recovery "bodyrig-recovery-environment.json"
    $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

    [pscustomobject]@{
        Repo = $repo
        Gate = Join-Path $repo "run-physical-gate.ps1"
        Recovery = $recovery
        ExternalPython = $externalPython
        FourD = $fourD
        Phalp = $phalp
        Smpl = $smplPath
        Summary = $summary
        SummaryPath = $summaryPath
        Output = $output
    }
}

function Save-Summary {
    param($Fixture)
    $Fixture.Summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Fixture.SummaryPath -Encoding UTF8
}

function Invoke-Gate {
    param($Fixture)
    $args = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $Fixture.Gate,
        "-RecoveryRoot", $Fixture.Recovery,
        "-Source", "person-a.mp4", "person-b.mp4",
        "-BodyId", "fixture-body",
        "-Name", "Fixture Body",
        "-TrackId", "track-7",
        "-BodyRigPython", "bodyrig-python-fixture",
        "-OutputDir", $Fixture.Output,
        "-AllowCpu"
    )
    $lines = @(&$Pwsh @args 2>&1)
    [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $lines -join [Environment]::NewLine }
}

try {
    $f = New-Fixture "pass"
    Assert-Success (Invoke-Gate $f) "valid managed recovery summary"
    $capture = Get-Content -LiteralPath (Join-Path $f.Output "capture.json") -Raw | ConvertFrom-Json
    if ([string]$capture.external_python -ne $f.ExternalPython -or [string]$capture.four_d_humans_repo -ne $f.FourD) { throw "managed paths were not forwarded exactly" }
    if ([string]$capture.body_id -ne "fixture-body" -or [string]$capture.track_id -ne "track-7" -or $capture.allow_cpu -ne $true) { throw "operator arguments were not forwarded" }
    if (@($capture.source).Count -ne 2) { throw "source list was not forwarded" }
    Write-Host "PASS: exact managed environment forwards to validate-rig"

    $f = New-Fixture "four-d-pin"
    $f.Summary.four_d_humans_revision = "0" * 40
    Save-Summary $f
    Assert-Failure (Invoke-Gate $f) "4D-Humans pin mismatch"
    Write-Host "PASS: 4D-Humans revision drift rejected"

    $f = New-Fixture "phalp-pin"
    $f.Summary.phalp_revision = "0" * 40
    Save-Summary $f
    Assert-Failure (Invoke-Gate $f) "PHALP pin mismatch"
    Write-Host "PASS: PHALP revision drift rejected"

    $f = New-Fixture "python-path"
    $alternate = Join-Path $f.Recovery "other-python.exe"
    Set-Content -LiteralPath $alternate -Value "fixture" -Encoding UTF8
    $f.Summary.external_python = $alternate
    Save-Summary $f
    Assert-Failure (Invoke-Gate $f) "recovery Python path substitution"
    Write-Host "PASS: recovery Python path substitution rejected"

    $f = New-Fixture "phalp-path"
    $alternate = Join-Path $f.Recovery "PHALP-other"
    New-Item -ItemType Directory -Path $alternate -Force | Out-Null
    $f.Summary.phalp_repo = $alternate
    Save-Summary $f
    Assert-Failure (Invoke-Gate $f) "PHALP path substitution"
    Write-Host "PASS: PHALP path substitution rejected"

    $f = New-Fixture "smpl-path"
    $alternate = Join-Path $f.Recovery $SmplFileName
    Set-Content -LiteralPath $alternate -Value "fixture" -Encoding UTF8
    $f.Summary.smpl_expected_path = $alternate
    Save-Summary $f
    Assert-Failure (Invoke-Gate $f) "SMPL path substitution"
    Write-Host "PASS: SMPL path substitution rejected"

    $f = New-Fixture "smpl-missing"
    $f.Summary.smpl_present = $false
    Save-Summary $f
    Assert-Failure (Invoke-Gate $f) "SMPL absent"
    Write-Host "PASS: missing SMPL state rejected"

    Write-Host "BodyRig managed physical gate tests: PASS"
} finally {
    if (Test-Path -LiteralPath $TempRoot) { Remove-Item -LiteralPath $TempRoot -Recurse -Force }
}
