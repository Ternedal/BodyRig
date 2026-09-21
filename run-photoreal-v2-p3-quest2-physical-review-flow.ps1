param(
    [Parameter(Mandatory = $true)][string]$RuntimeReviewWorkspace,
    [Parameter(Mandatory = $true)][string]$MachineProbe,
    [string]$WindowsPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Invoke-BodyRigOperator {
    param(
        [Parameter(Mandatory = $true)][string]$Pwsh,
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    & $Pwsh -NoLogo -NoProfile -File $Script @Arguments
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        throw "$Label failed with exit code $code."
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Quest2 P3 physical review flow is Windows-orchestrated."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the Quest2 P3 physical review flow."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 P3 physical review flow requires an exact clean BodyRig checkout."
}

$RuntimeReviewWorkspace = Need-Directory -Path $RuntimeReviewWorkspace -Label "Quest2 runtime review workspace"
$MachineProbe = Need-File -Path $MachineProbe -Label "Quest2 machine probe"

$pwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwshCommand) {
    throw "PowerShell 7 executable 'pwsh' was not found."
}
$pwsh = $pwshCommand.Source

$prefillScript = Need-File -Path (Join-Path $repoRoot "prepare-photoreal-v2-p3-quest2-physical-evidence-from-machine.ps1") -Label "Quest2 machine-prefill operator"
$humanReviewScript = Need-File -Path (Join-Path $repoRoot "complete-photoreal-v2-p3-quest2-physical-evidence-review.ps1") -Label "Quest2 human-review operator"
$recorderScript = Need-File -Path (Join-Path $repoRoot "record-photoreal-v2-p3-quest2-physical-runtime-review.ps1") -Label "Quest2 physical-review recorder"

$machinePrefill = Join-Path $RuntimeReviewWorkspace "p3-physical-runtime-evidence.machine-prefill.json"
$humanEvidence = Join-Path $RuntimeReviewWorkspace "p3-physical-runtime-evidence.human-review.json"
$finalReceipt = Join-Path $RuntimeReviewWorkspace "p3-physical-runtime-review.json"

foreach ($path in @($machinePrefill, $humanEvidence, $finalReceipt)) {
    if (Test-Path -LiteralPath $path) {
        throw "Quest2 P3 physical review flow is create-only; output already exists: $path"
    }
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 PHYSICAL REVIEW FLOW"
Write-Host "Runtime review workspace: $RuntimeReviewWorkspace"
Write-Host "Machine probe:            $MachineProbe"
Write-Host "Machine evidence:         PREFILL ONLY"
Write-Host "Human visual review:      REQUIRED"
Write-Host "Final strict recorder:    REQUIRED"
Write-Host "Production activation:    FALSE"
Write-Host "============================================================"
Write-Host ""

Invoke-BodyRigOperator -Pwsh $pwsh -Script $prefillScript -Arguments @(
    "-RuntimeReviewWorkspace", $RuntimeReviewWorkspace,
    "-MachineProbe", $MachineProbe
) -Label "Quest2 machine evidence prefill"

$machinePrefill = Need-File -Path $machinePrefill -Label "Quest2 machine-prefilled evidence"

Write-Host ""
Write-Host "Machine-safe evidence is ready."
Write-Host "The next stage is the explicit human in-headset visual review."
Write-Host ""

Invoke-BodyRigOperator -Pwsh $pwsh -Script $humanReviewScript -Arguments @(
    "-MachinePrefill", $machinePrefill
) -Label "Quest2 human physical review"

$humanEvidence = Need-File -Path $humanEvidence -Label "Quest2 human-reviewed evidence"

$recorderArgs = @(
    "-RuntimeReviewWorkspace", $RuntimeReviewWorkspace,
    "-Evidence", $humanEvidence
)
if (-not [string]::IsNullOrWhiteSpace($WindowsPython)) {
    $recorderArgs += @("-WindowsPython", (Need-File -Path $WindowsPython -Label "Windows Python"))
}

Invoke-BodyRigOperator -Pwsh $pwsh -Script $recorderScript -Arguments $recorderArgs -Label "Quest2 strict physical review recorder"

$finalReceipt = Need-File -Path $finalReceipt -Label "Quest2 physical runtime review receipt"
$receipt = Get-Content -LiteralPath $finalReceipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

$status = ([string]$receipt.runtime_review_status).Trim().ToLowerInvariant()
if ($status -notin @("pass", "fail")) {
    throw "Quest2 physical runtime review receipt has invalid status: $status"
}
if ($receipt.production_activation -isnot [bool] -or $receipt.production_activation -ne $false) {
    throw "Quest2 physical runtime review flow crossed production authority."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG QUEST2 PHYSICAL REVIEW FLOW: $($status.ToUpperInvariant())"
Write-Host "Runtime acceptance:       $($receipt.runtime_acceptance_authority)"
Write-Host "Photoreal acceptance:     $($receipt.photoreal_acceptance_authority)"
Write-Host "Production activation:    FALSE"
Write-Host "Receipt:                  $finalReceipt"
Write-Host "============================================================"
exit 0
