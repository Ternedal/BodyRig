param(
    [Parameter(Mandatory = $true)]
    [string[]]$Source,

    [string]$BodyId = "bodyrig-acceptance",
    [string]$Name = "BodyRig Acceptance",
    [string]$TrackId = "",
    [string]$RecoveryRoot = "",
    [string]$BodyRigPython = "",
    [string]$OutputDir = "",
    [switch]$AllowCpu
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$FourDRevision = "efe18deff163b29dff87ddbd575fa29b716a356c"
$PhalpRevision = "96f7e6c09fb858ec3f597d59246c151ab4394bc3"
$SmplFileName = "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl"

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-ExactPath {
    param(
        [Parameter(Mandatory = $true)][string]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actualFull = Resolve-FullPath $Actual
    $expectedFull = Resolve-FullPath $Expected
    if (-not [string]::Equals($actualFull.TrimEnd('\', '/'), $expectedFull.TrimEnd('\', '/'), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label does not match the managed recovery layout. Expected: $expectedFull | Actual: $actualFull"
    }
    return $actualFull
}

if ([string]::IsNullOrWhiteSpace($RecoveryRoot)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is unavailable; pass -RecoveryRoot explicitly."
    }
    $RecoveryRoot = Join-Path $env:LOCALAPPDATA "BodyRig\recovery"
}
$RecoveryRoot = Resolve-FullPath $RecoveryRoot
if (-not (Test-Path -LiteralPath $RecoveryRoot -PathType Container)) {
    throw "Managed BodyRig recovery root not found: $RecoveryRoot. Run .\setup-recovery-windows.ps1 first."
}

$summaryPath = Join-Path $RecoveryRoot "bodyrig-recovery-environment.json"
if (-not (Test-Path -LiteralPath $summaryPath -PathType Leaf)) {
    throw "Managed recovery environment summary not found: $summaryPath. Run .\setup-recovery-windows.ps1 first."
}

try {
    $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
} catch {
    throw "Managed recovery environment summary is not valid JSON: $summaryPath"
}

$expectedFields = @(
    "format",
    "version",
    "root",
    "external_python",
    "four_d_humans_repo",
    "four_d_humans_revision",
    "phalp_repo",
    "phalp_revision",
    "smpl_expected_path",
    "smpl_present"
)
if (@(Compare-Object -ReferenceObject $expectedFields -DifferenceObject @($summary.PSObject.Properties.Name)).Count -ne 0) {
    throw "Managed recovery environment summary fields do not match BodyRig recovery environment v1."
}
if ([string]$summary.format -ne "bodyrig-recovery-environment" -or [int]$summary.version -ne 1) {
    throw "Unsupported managed recovery environment format/version."
}

$summaryRoot = Assert-ExactPath -Actual ([string]$summary.root) -Expected $RecoveryRoot -Label "Recovery root"
if ([string]$summary.four_d_humans_revision -ne $FourDRevision) {
    throw "Managed recovery summary 4D-Humans revision does not match BodyRig pin $FourDRevision."
}
if ([string]$summary.phalp_revision -ne $PhalpRevision) {
    throw "Managed recovery summary PHALP revision does not match BodyRig pin $PhalpRevision."
}
if ($summary.smpl_present -ne $true) {
    throw "Managed recovery environment reports that the required SMPL model is missing. Rerun setup-recovery-windows.ps1 with -SmplModelPath."
}

$expectedExternalPython = Join-Path (Join-Path $RecoveryRoot "conda-env") "python.exe"
$expectedFourDHumansRepo = Join-Path $RecoveryRoot "4D-Humans"
$expectedPhalpRepo = Join-Path $RecoveryRoot "PHALP"
$expectedSmplPath = Join-Path (Join-Path $expectedFourDHumansRepo "data") $SmplFileName

$externalPython = Assert-ExactPath -Actual ([string]$summary.external_python) -Expected $expectedExternalPython -Label "Recovery Python"
$fourDHumansRepo = Assert-ExactPath -Actual ([string]$summary.four_d_humans_repo) -Expected $expectedFourDHumansRepo -Label "4D-Humans repo"
$phalpRepo = Assert-ExactPath -Actual ([string]$summary.phalp_repo) -Expected $expectedPhalpRepo -Label "PHALP repo"
$smplExpectedPath = Assert-ExactPath -Actual ([string]$summary.smpl_expected_path) -Expected $expectedSmplPath -Label "SMPL model"

if (-not (Test-Path -LiteralPath $externalPython -PathType Leaf)) {
    throw "Managed recovery Python is missing: $externalPython"
}
if (-not (Test-Path -LiteralPath $fourDHumansRepo -PathType Container)) {
    throw "Managed 4D-Humans checkout is missing: $fourDHumansRepo"
}
if (-not (Test-Path -LiteralPath $phalpRepo -PathType Container)) {
    throw "Managed PHALP checkout is missing: $phalpRepo"
}
if (-not (Test-Path -LiteralPath $smplExpectedPath -PathType Leaf)) {
    throw "Managed recovery summary says SMPL is present, but the file is missing: $smplExpectedPath"
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$validateScript = Join-Path $repoRoot "validate-rig.ps1"
if (-not (Test-Path -LiteralPath $validateScript -PathType Leaf)) {
    throw "BodyRig validate-rig.ps1 not found: $validateScript"
}

$validateArgs = @{
    Source = $Source
    ExternalPython = $externalPython
    FourDHumansRepo = $fourDHumansRepo
    BodyId = $BodyId
    Name = $Name
}
if (-not [string]::IsNullOrWhiteSpace($TrackId)) { $validateArgs.TrackId = $TrackId }
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $validateArgs.BodyRigPython = $BodyRigPython }
if (-not [string]::IsNullOrWhiteSpace($OutputDir)) { $validateArgs.OutputDir = $OutputDir }
if ($AllowCpu) { $validateArgs.AllowCpu = $true }

Write-Host "BodyRig physical Gate A"
Write-Host "Managed recovery root: $summaryRoot"
Write-Host "Source clips: $($Source.Count)"
Write-Host "Body id: $BodyId"
Write-Host ""

& $validateScript @validateArgs
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Write-Error "BodyRig physical Gate A failed with exit code $exitCode."
    exit $exitCode
}

Write-Host ""
Write-Host "BodyRig physical Gate A: PASS"
Write-Host "Renderer acceptance remains pending until the same accepted runtime is proven on WindowsPlayer and Quest-class hardware."
exit 0
