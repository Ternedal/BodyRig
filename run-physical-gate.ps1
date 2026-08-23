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

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $fullPath = Resolve-FullPath $Path
    $fullRoot = (Resolve-FullPath $Root).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label escapes the managed recovery root: $fullPath"
    }
    return $fullPath
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

$summaryRoot = Resolve-FullPath ([string]$summary.root)
if (-not [string]::Equals($summaryRoot.TrimEnd('\', '/'), $RecoveryRoot.TrimEnd('\', '/'), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Managed recovery environment summary root does not match the selected recovery root."
}
if ($summary.smpl_present -ne $true) {
    throw "Managed recovery environment reports that the required SMPL model is missing. Rerun setup-recovery-windows.ps1 with -SmplModelPath."
}

$externalPython = Assert-ChildPath -Path ([string]$summary.external_python) -Root $RecoveryRoot -Label "Recovery Python"
$fourDHumansRepo = Assert-ChildPath -Path ([string]$summary.four_d_humans_repo) -Root $RecoveryRoot -Label "4D-Humans repo"
$smplExpectedPath = Assert-ChildPath -Path ([string]$summary.smpl_expected_path) -Root $RecoveryRoot -Label "SMPL model"

if (-not (Test-Path -LiteralPath $externalPython -PathType Leaf)) {
    throw "Managed recovery Python is missing: $externalPython"
}
if (-not (Test-Path -LiteralPath $fourDHumansRepo -PathType Container)) {
    throw "Managed 4D-Humans checkout is missing: $fourDHumansRepo"
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
Write-Host "Managed recovery root: $RecoveryRoot"
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
