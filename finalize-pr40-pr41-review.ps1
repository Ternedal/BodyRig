param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [string]$BodyRigPython = '',
    [string]$HistoricalSnapshots = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'The #40 -> #41 review finalizer is Windows-only.'
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ is required.' }

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Resolve-InputDirectory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect helper checkout status.' }
if ($dirty.Count -gt 0) { throw 'Review finalizer requires a clean helper checkout.' }

$WorkRoot = Resolve-InputDirectory -Path ([IO.Path]::GetFullPath($WorkRoot)) -Label '#40 work root'
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localVenv = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localVenv -PathType Leaf) { $BodyRigPython = $localVenv }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw 'BodyRig Python not found; pass -BodyRigPython from the installed rig checkout.' }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label 'BodyRig Python'

if ([string]::IsNullOrWhiteSpace($HistoricalSnapshots)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is unavailable; pass -HistoricalSnapshots.' }
    $HistoricalSnapshots = Join-Path $env:LOCALAPPDATA 'BodyRig\fidelity-baselines\integration-64aa-8a891565\snapshots'
}
$HistoricalSnapshots = Resolve-InputDirectory -Path $HistoricalSnapshots -Label 'Historical bad-baseline snapshots'

# The final comparison is allowed only after #40 was explicitly human-approved and sealed.
& (Join-Path $repoRoot 'invoke-pr40-physical-handoff.ps1') `
    -WorkRoot $WorkRoot `
    -Mode Verify `
    -BodyRigPython $BodyRigPython
if ($LASTEXITCODE -ne 0) { throw '#40 physical handoff verification failed before final A/B.' }

$receiptPath = Join-Path $WorkRoot 'handoff\pr40-physical-handoff.json'
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
$checkpointRel = [string]$receipt.checkpoint.path
$checkpointPath = Resolve-InputFile -Path (Join-Path $WorkRoot $checkpointRel.Replace('/', [IO.Path]::DirectorySeparatorChar)) -Label '#40 sealed checkpoint'
$checkpoint = Get-Content -LiteralPath $checkpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
$records = @($checkpoint.state.candidate_records)
if ($records.Count -ne 1 -or [string]$records[0].mode -ne 'full-reconstruction') {
    throw 'Sealed #40 checkpoint no longer describes exactly one full-reconstruction candidate.'
}
$record = $records[0]
$pr40Package = Resolve-InputFile -Path (Join-Path $WorkRoot ([string]$record.package_path).Replace('/', [IO.Path]::DirectorySeparatorChar)) -Label '#40 package'
$pr40Render = Resolve-InputDirectory -Path (Join-Path $WorkRoot ([string]$record.render_dir).Replace('/', [IO.Path]::DirectorySeparatorChar)) -Label '#40 render directory'
$pr40Snapshots = Resolve-InputDirectory -Path (Join-Path $pr40Render 'snapshots') -Label '#40 snapshots'

$pr41Dir = Resolve-InputDirectory -Path (Join-Path $WorkRoot 'pr41-clean-ab') -Label '#41 clean A/B output'
$pr41Package = Resolve-InputFile -Path (Join-Path $pr41Dir 'lauren-phillips-pr41-ab.mrbody') -Label '#41 package'
$pr41Snapshots = Resolve-InputDirectory -Path (Join-Path $pr41Dir 'comparison-render\snapshots') -Label '#41 snapshots'

$resultRoot = Join-Path $WorkRoot 'pr40-pr41-review'
if (Test-Path -LiteralPath $resultRoot) { throw "Final review output already exists: $resultRoot" }
New-Item -ItemType Directory -Path $resultRoot | Out-Null
$abEvidence = Join-Path $resultRoot 'pr40-pr41-ab-evidence.json'
$reviewBundle = Join-Path $resultRoot 'review-bundle'

try {
    & (Join-Path $repoRoot 'compare-fidelity-ab.ps1') `
        -LeftPackage $pr40Package `
        -RightPackage $pr41Package `
        -Output $abEvidence `
        -BodyRigPython $BodyRigPython
    if ($LASTEXITCODE -ne 0) { throw '#40 -> #41 clean appearance A/B failed.' }

    & (Join-Path $repoRoot 'build-fidelity-review-bundle.ps1') `
        -HistoricalRender $HistoricalSnapshots `
        -Pr40Render $pr40Snapshots `
        -Pr41Render $pr41Snapshots `
        -AbEvidence $abEvidence `
        -OutputDir $reviewBundle `
        -BodyRigPython $BodyRigPython
    if ($LASTEXITCODE -ne 0) { throw '#40 -> #41 physical review bundle failed.' }
} catch {
    if (Test-Path -LiteralPath $resultRoot -PathType Container) {
        Remove-Item -LiteralPath $resultRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}

$index = Resolve-InputFile -Path (Join-Path $reviewBundle 'index.html') -Label 'Final physical review page'
Write-Host '#40 -> #41 final evidence: PASS'
Write-Host "#40 package:  $pr40Package"
Write-Host "#41 package:  $pr41Package"
Write-Host "A/B evidence: $abEvidence"
Write-Host "Review page:  $index"
Write-Host 'NEXT: human face/skin/hair/appearance review remains mandatory. This finalizer does not grant production activation.'
exit 0
