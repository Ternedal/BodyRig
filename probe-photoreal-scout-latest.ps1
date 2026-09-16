param(
    [string]$SearchRoot = "",
    [string]$ProbeRoot = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Read-JsonObjectOrNull {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )
    try {
        $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
    if ($null -eq $value -or $value -is [System.Array]) {
        return $null
    }
    return $value
}

function Test-AuthorityTriplet {
    param(
        [Parameter(Mandatory = $true)][string]$CandidateRoot,
        [Parameter(Mandatory = $true)][string]$ReceiptPath
    )

    $inventoryPath = Join-Path $CandidateRoot "source-inventory.json"
    $planPath = Join-Path $CandidateRoot "dataset-plan.json"
    if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $planPath -PathType Leaf)) {
        return $false
    }

    $inventory = Read-JsonObjectOrNull -Path $inventoryPath
    $plan = Read-JsonObjectOrNull -Path $planPath
    $receipt = Read-JsonObjectOrNull -Path $ReceiptPath
    if ($null -eq $inventory -or $null -eq $plan -or $null -eq $receipt) {
        return $false
    }

    if ([string]$inventory.format -ne "bodyrig-photoreal-source-inventory" -or [int]$inventory.version -ne 1) {
        return $false
    }
    if ([string]$plan.format -ne "bodyrig-photoreal-dataset-plan" -or [int]$plan.version -ne 1) {
        return $false
    }
    if ([string]$receipt.format -ne "bodyrig-photoreal-source-receipt" -or [int]$receipt.version -ne 1) {
        return $false
    }

    if ($inventory.build_only -ne $true -or $inventory.runtime_dependency -ne $false -or $inventory.production_activation -ne $false) {
        return $false
    }
    if ($plan.build_only -ne $true -or $plan.runtime_dependency -ne $false -or $plan.production_activation -ne $false -or
        $plan.teacher_training_authorized -ne $false) {
        return $false
    }
    if ($receipt.all_sources_readable -ne $true -or $receipt.all_sources_sha256_bound -ne $true -or
        $receipt.source_keys_path_specific -ne $true -or $receipt.build_only -ne $true -or
        $receipt.runtime_dependency -ne $false -or $receipt.production_activation -ne $false) {
        return $false
    }
    return $true
}

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
    if (Test-AuthorityTriplet -CandidateRoot $candidate -ReceiptPath $receipt.FullName) {
        $selectedRoot = $candidate
        $selectedReceipt = $receipt
        break
    }
}

if ([string]::IsNullOrWhiteSpace([string]$selectedRoot)) {
    throw "No replayable Photoreal P0 root with a valid source-inventory.json, dataset-plan.json and source-receipt.json authority triplet was found under: $SearchRoot"
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - AUTO-SELECT READ-ONLY REPLAY"
Write-Host "Search root:       $SearchRoot"
Write-Host "Selected P0 root:  $selectedRoot"
Write-Host "Receipt modified:  $($selectedReceipt.LastWriteTimeUtc.ToString('o')) UTC"
Write-Host "Selection policy:  latest valid authority triplet"
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
