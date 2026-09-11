param(
    [Parameter(Mandatory = $true)][string]$SweepRoot,
    [Parameter(Mandatory = $true)][string[]]$QualityReceipt,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig multi-performer detail aggregation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ($QualityReceipt.Count -lt 1) { throw "At least one -QualityReceipt is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind multi-performer detail aggregation to exact BodyRig Git HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Multi-performer detail aggregation requires an exact clean BodyRig checkout."
}

$SweepRoot = Need-Directory -Path $SweepRoot -Label "Photoidentity sweep root"
$baseEvidence = Need-File -Path (Join-Path $SweepRoot "human-parsing-evidence\photoidentity-observations.json") -Label "Human-parsing observation evidence"
$baseReport = Need-File -Path (Join-Path $SweepRoot "human-parsing-evidence\photoidentity-evidence.json") -Label "Human-parsing sufficiency report"
if (Test-Path -LiteralPath (Join-Path $SweepRoot "multiperformer-detail-evidence")) {
    throw "Multi-performer detail evidence already exists; aggregation is create-only."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $BodyRigPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$actualRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualRaw.Count -ne 1) { throw "Could not verify checkout-bound BodyRig Python." }
$actualModule = [IO.Path]::GetFullPath(([string]$actualRaw[0]).Trim())
if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports from a different checkout: $actualModule"
}

$resolvedReceipts = @()
foreach ($value in $QualityReceipt) {
    $resolvedReceipts += Need-File -Path $value -Label "Target-crop source-detail quality receipt"
}
if (($resolvedReceipts | Sort-Object -Unique).Count -ne $resolvedReceipts.Count) {
    throw "Duplicate -QualityReceipt paths are not allowed."
}

Write-Host "BodyRig multi-performer detail aggregation"
Write-Host "Revision: $head"
Write-Host "Sweep root: $SweepRoot"
Write-Host "Quality receipts: $($resolvedReceipts.Count)"
Write-Host "Base observations: $baseEvidence"
Write-Host "Base report: $baseReport"
Write-Host "Renderer/reconstruction: NOT INVOKED"
Write-Host ""

$args = @("-m", "bodyrig.photoidentity_multiperformer_detail_aggregate", "--sweep-root", $SweepRoot)
foreach ($receipt in $resolvedReceipts) {
    $args += @("--quality-receipt", [string]$receipt)
}
& $BodyRigPython @args
if ($LASTEXITCODE -ne 0) { throw "Multi-performer detail aggregation failed with exit code $LASTEXITCODE." }

$receiptPath = Need-File -Path (Join-Path $SweepRoot "photoidentity-multiperformer-detail-aggregation.json") -Label "Multi-performer detail aggregation receipt"
$observationsPath = Need-File -Path (Join-Path $SweepRoot "multiperformer-detail-evidence\photoidentity-observations.json") -Label "Multi-performer detail observation evidence"
$reportPath = Need-File -Path (Join-Path $SweepRoot "multiperformer-detail-evidence\photoidentity-evidence.json") -Label "Multi-performer detail sufficiency report"
try {
    $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60
    $observations = Get-Content -LiteralPath $observationsPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60
    $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60
} catch { throw "Aggregated multi-performer detail evidence is unreadable JSON." }
if (
    [string]$receipt.bodyrig_revision -ne $head -or
    [string]$observations.bodyrig_revision -ne $head -or
    [string]$report.bodyrig_revision -ne $head -or
    [string]$receipt.prior_stage -ne "human-parsing" -or
    $receipt.source_grounded -ne $true -or
    $receipt.generic_guessing_permitted -ne $false -or
    $receipt.production_activation -ne $false
) {
    throw "Aggregated multi-performer detail evidence crossed revision/authority boundary."
}
$dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirtyAfter.Count -gt 0) {
    throw "Checkout changed during multi-performer detail aggregation."
}

Write-Host ""
Write-Host "BodyRig multi-performer detail aggregation: PASS"
Write-Host "Receipt: $receiptPath"
Write-Host "Updated sufficiency: $reportPath"
Write-Host "Source evidence sufficient: $([bool]$report.source_evidence_sufficient)"
Write-Host "Nail/anatomy authority: NOT CHANGED"
Write-Host "Production activation: FALSE"
