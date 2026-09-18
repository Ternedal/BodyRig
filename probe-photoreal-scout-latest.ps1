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

function Test-HasFields {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string[]]$Fields
    )
    $names = @($Value.PSObject.Properties.Name)
    foreach ($field in $Fields) {
        if ($names -notcontains $field) {
            return $false
        }
    }
    return $true
}

function Test-StrictBoolean {
    param(
        [AllowNull()]$Value,
        [Parameter(Mandatory = $true)][bool]$Expected
    )
    return ($Value -is [bool]) -and ([bool]$Value -eq $Expected)
}

function Test-StrictInteger {
    param(
        [AllowNull()]$Value,
        [Parameter(Mandatory = $true)][long]$Expected
    )
    if ($Value -is [bool] -or $null -eq $Value) {
        return $false
    }
    $isIntegerType = (
        $Value -is [sbyte] -or
        $Value -is [byte] -or
        $Value -is [int16] -or
        $Value -is [uint16] -or
        $Value -is [int32] -or
        $Value -is [uint32] -or
        $Value -is [int64] -or
        $Value -is [uint64]
    )
    if (-not $isIntegerType) {
        return $false
    }
    try {
        return ([int64]$Value -eq $Expected)
    } catch {
        return $false
    }
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

    if (-not (Test-HasFields -Value $inventory -Fields @(
        "format", "version", "build_only", "runtime_dependency", "production_activation"
    ))) { return $false }
    if (-not (Test-HasFields -Value $plan -Fields @(
        "format", "version", "build_only", "runtime_dependency", "production_activation", "teacher_training_authorized"
    ))) { return $false }
    if (-not (Test-HasFields -Value $receipt -Fields @(
        "format", "version", "all_sources_readable", "all_sources_sha256_bound", "source_keys_path_specific",
        "build_only", "runtime_dependency", "production_activation"
    ))) { return $false }

    if ([string]$inventory.format -ne "bodyrig-photoreal-source-inventory" -or
        -not (Test-StrictInteger -Value $inventory.version -Expected 1)) {
        return $false
    }
    if ([string]$plan.format -ne "bodyrig-photoreal-dataset-plan" -or
        -not (Test-StrictInteger -Value $plan.version -Expected 1)) {
        return $false
    }
    if ([string]$receipt.format -ne "bodyrig-photoreal-source-receipt" -or
        -not (Test-StrictInteger -Value $receipt.version -Expected 1)) {
        return $false
    }

    if (-not (Test-StrictBoolean -Value $inventory.build_only -Expected $true) -or
        -not (Test-StrictBoolean -Value $inventory.runtime_dependency -Expected $false) -or
        -not (Test-StrictBoolean -Value $inventory.production_activation -Expected $false)) {
        return $false
    }
    if (-not (Test-StrictBoolean -Value $plan.build_only -Expected $true) -or
        -not (Test-StrictBoolean -Value $plan.runtime_dependency -Expected $false) -or
        -not (Test-StrictBoolean -Value $plan.production_activation -Expected $false) -or
        -not (Test-StrictBoolean -Value $plan.teacher_training_authorized -Expected $false)) {
        return $false
    }
    if (-not (Test-StrictBoolean -Value $receipt.all_sources_readable -Expected $true) -or
        -not (Test-StrictBoolean -Value $receipt.all_sources_sha256_bound -Expected $true) -or
        -not (Test-StrictBoolean -Value $receipt.source_keys_path_specific -Expected $true) -or
        -not (Test-StrictBoolean -Value $receipt.build_only -Expected $true) -or
        -not (Test-StrictBoolean -Value $receipt.runtime_dependency -Expected $false) -or
        -not (Test-StrictBoolean -Value $receipt.production_activation -Expected $false)) {
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