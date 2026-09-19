param(
    [Parameter(Mandatory = $true)][string]$NewRun,
    [Parameter(Mandatory = $true)][string]$VerifiedSourceRun,
    [string]$StashUrl = "",
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
$NewRun = Need-Directory -Path $NewRun -Label "New metadata run"
$VerifiedSourceRun = Need-Directory -Path $VerifiedSourceRun -Label "Previously verified source run"

$newInventory = Need-File -Path (Join-Path $NewRun "source-inventory.json") -Label "New source inventory"
$newPathMap = Need-File -Path (Join-Path $NewRun "source-path-map.json") -Label "New source path map"
Need-File -Path (Join-Path $NewRun "dataset-plan.json") -Label "New dataset plan" | Out-Null
$priorInventory = Need-File -Path (Join-Path $VerifiedSourceRun "source-inventory.json") -Label "Prior verified source inventory"
$priorReceipt = Need-File -Path (Join-Path $VerifiedSourceRun "source-receipt.json") -Label "Prior verified source receipt"

$newReceipt = Join-Path $NewRun "source-receipt.json"
$rebindProof = Join-Path $NewRun "source-receipt-rebind-proof.json"
$spatialProbe = Join-Path $NewRun "spatial-metadata-probe.json"
foreach ($path in @($newReceipt, $rebindProof, $spatialProbe)) {
    if (Test-Path -LiteralPath $path) { throw "Output already exists; refusing to overwrite: $path" }
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $BodyRigPython = (Resolve-Path -LiteralPath $localPython).Path
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python was not found." }
        $BodyRigPython = $command.Source
    }
} else {
    $BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
}

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    $configPath = Join-Path $env:LOCALAPPDATA "BodyRig\config\stash.json"
    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20
        $StashUrl = [string]$config.url
    }
}
if ([string]::IsNullOrWhiteSpace($StashUrl)) { throw "StashUrl or STASH_URL is required." }

$priorPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })

    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - REBIND VERIFIED SOURCE RECEIPT"
    Write-Host "New metadata run:     $NewRun"
    Write-Host "Verified source run:  $VerifiedSourceRun"
    Write-Host "Source rehash:        SKIPPED EXPLICITLY"
    Write-Host "Teacher training:     FALSE"
    Write-Host "Photoreal acceptance: FALSE"
    Write-Host "Production:           FALSE"
    Write-Host "============================================================"
    Write-Host ""

    $rebindArgs = @("-m","bodyrig.photoreal_source_receipt_rebind_cli","--prior-inventory",$priorInventory,"--prior-receipt",$priorReceipt,"--new-inventory",$newInventory,"--new-path-map",$newPathMap,"--out",$newReceipt,"--proof-out",$rebindProof,"--stash-url",$StashUrl)
    & $BodyRigPython @rebindArgs
    if ($LASTEXITCODE -ne 0) { throw "Source receipt rebind failed with exit code $LASTEXITCODE." }

    Write-Host ""
    Write-Host "=== REBUILD SPATIAL METADATA PROBE WITHOUT SOURCE REHASH ==="
    $probeArgs = @("-m","bodyrig.photoreal_spatial_metadata_probe_cli","--inventory",$newInventory,"--receipt",$newReceipt,"--out",$spatialProbe)
    & $BodyRigPython @probeArgs
    if ($LASTEXITCODE -ne 0) { throw "Spatial metadata probe failed with exit code $LASTEXITCODE." }

    Write-Host ""
    Write-Host "BodyRig Photoreal source metadata: READY"
    Write-Host "Receipt:       $newReceipt"
    Write-Host "Rebind proof:  $rebindProof"
    Write-Host "Spatial probe: $spatialProbe"
    Write-Host "Source rehash: SKIPPED EXPLICITLY"
    Write-Host "Production:    FALSE"
}
finally {
    $env:PYTHONPATH = $priorPythonPath
}
