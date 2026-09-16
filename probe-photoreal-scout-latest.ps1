param(
    [string]$SearchRoot = "",
    [string]$ProbeRoot = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$replay = Join-Path $repoRoot "probe-photoreal-scout-authority.ps1"
if (-not (Test-Path -LiteralPath $replay -PathType Leaf)) {
    throw "Scout authority replay script not found: $replay"
}

if ([string]::IsNullOrWhiteSpace($SearchRoot)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is required when SearchRoot is not supplied."
    }
    $SearchRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\overnight"
} else {
    $SearchRoot = [IO.Path]::GetFullPath($SearchRoot)
}

if (-not (Test-Path -LiteralPath $SearchRoot -PathType Container)) {
    throw "Photoreal overnight search root not found: $SearchRoot"
}
$SearchRoot = (Resolve-Path -LiteralPath $SearchRoot).Path

$receipts = @(
    Get-ChildItem -LiteralPath $SearchRoot -Recurse -Filter "source-receipt.json" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending
)

$selectedRoot = $null
$selectedReceipt = $null
foreach ($receipt in $receipts) {
    $candidate = $receipt.Directory.FullName
    $inventory = Join-Path $candidate "source-inventory.json"
    $plan = Join-Path $candidate "dataset-plan.json"
    if ((Test-Path -LiteralPath $inventory -PathType Leaf) -and
        (Test-Path -LiteralPath $plan -PathType Leaf)) {
        $selectedRoot = $candidate
        $selectedReceipt = $receipt
        break
    }
}

if ([string]::IsNullOrWhiteSpace([string]$selectedRoot)) {
    throw "No replayable Photoreal P0 root with source-inventory.json, dataset-plan.json and source-receipt.json was found under: $SearchRoot"
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - AUTO-SELECT READ-ONLY REPLAY"
Write-Host "Search root:       $SearchRoot"
Write-Host "Selected P0 root:  $selectedRoot"
Write-Host "Receipt modified:  $($selectedReceipt.LastWriteTimeUtc.ToString('o')) UTC"
Write-Host "Selection policy:  latest complete authority triplet"
Write-Host "Mutation:          FALSE"
Write-Host "============================================================"

$replayArgs = @{
    OutputRoot = $selectedRoot
}
if (-not [string]::IsNullOrWhiteSpace($ProbeRoot)) {
    $replayArgs["ProbeRoot"] = $ProbeRoot
}
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $replayArgs["BodyRigPython"] = $BodyRigPython
}

& $replay @replayArgs
