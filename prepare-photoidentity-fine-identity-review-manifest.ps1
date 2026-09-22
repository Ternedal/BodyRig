param(
    [Parameter(Mandatory = $true)][string]$SweepRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceCsv,
    [Parameter(Mandatory = $true)][string]$MarkerInventory,
    [string]$Output = "",
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

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Fine-identity manifest preparation requires an exact clean BodyRig checkout." }

$SweepRoot = Need-Directory -Path $SweepRoot -Label "Photoidentity sweep root"
$EvidenceCsv = Need-File -Path $EvidenceCsv -Label "Fine-identity evidence CSV"
$MarkerInventory = Need-File -Path $MarkerInventory -Label "Private distinctive-marker inventory"
if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $SweepRoot "private-fine-identity-review-manifest.json"
}
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = (Get-Command python -ErrorAction Stop).Source }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"

& $BodyRigPython -m bodyrig.photoidentity_fine_identity_review_manifest --sweep-root $SweepRoot --evidence-csv $EvidenceCsv --marker-inventory $MarkerInventory --output $Output
if ($LASTEXITCODE -ne 0) { throw "Fine-identity review manifest preparation failed with exit code $LASTEXITCODE." }

Write-Host ""
Write-Host "Private review manifest: $Output"
Write-Host "This file contains local source paths and must remain private."
