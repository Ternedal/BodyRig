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

function Read-Json {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $resolved = Need-File -Path $Path -Label $Label
    try {
        return Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    } catch {
        throw "$Label is not valid JSON: $resolved"
    }
}

function Machine-Evidence-Binding {
    param([Parameter(Mandatory = $true)]$Evidence)

    return [ordered]@{
        format = $Evidence.format
        version = $Evidence.version
        runtime_review_plan_sha256 = $Evidence.runtime_review_plan_sha256
        target_device_family = $Evidence.target_device_family
        target_device_model = $Evidence.target_device_model
        physical_device_observed = $Evidence.physical_device_observed
        installed_student_artifacts = @($Evidence.installed_student_artifacts)
        observed_refresh_hz = $Evidence.observed_refresh_hz
        p95_frame_time_ms = $Evidence.p95_frame_time_ms
        stereo_rendering_observed = $Evidence.stereo_rendering_observed
        vr_safe_frame_pacing_observed = $Evidence.vr_safe_frame_pacing_observed
        installed_student_hashes_verified_on_device = $Evidence.installed_student_hashes_verified_on_device
    }
}

function Assert-HumanEvidenceMatchesPrefill {
    param(
        [Parameter(Mandatory = $true)][string]$MachinePrefill,
        [Parameter(Mandatory = $true)][string]$HumanEvidence
    )

    $prefill = Read-Json -Path $MachinePrefill -Label "Quest2 machine-prefilled evidence"
    $human = Read-Json -Path $HumanEvidence -Label "Quest2 human-reviewed evidence"

    if ($human.operator_supplied -isnot [bool] -or $human.operator_supplied -ne $true) {
        throw "Existing Quest2 human-review evidence is not explicitly operator supplied."
    }
    if (
        $human.confirm_physical_device_review_complete -isnot [bool] -or
        $human.confirm_physical_device_review_complete -ne $true
    ) {
        throw "Existing Quest2 human-review evidence is not explicitly complete."
    }

    $prefillBinding = Machine-Evidence-Binding -Evidence $prefill
    $humanBinding = Machine-Evidence-Binding -Evidence $human
    $prefillCanonical = $prefillBinding | ConvertTo-Json -Depth 100 -Compress
    $humanCanonical = $humanBinding | ConvertTo-Json -Depth 100 -Compress
    if ($humanCanonical -cne $prefillCanonical) {
        throw "Existing Quest2 human-review evidence does not match the exact current machine prefill."
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

if (Test-Path -LiteralPath $finalReceipt -PathType Leaf) {
    Write-Host "Existing final Quest2 physical review receipt detected; the full evidence chain will be strictly revalidated without rewriting it."
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
    "-MachineProbe", $MachineProbe,
    "-ReuseExisting"
) -Label "Quest2 machine evidence prefill"

$machinePrefill = Need-File -Path $machinePrefill -Label "Quest2 machine-prefilled evidence"

Write-Host ""
Write-Host "Machine-safe evidence is ready."
Write-Host "The next stage is the explicit human in-headset visual review."
Write-Host ""

if (Test-Path -LiteralPath $humanEvidence -PathType Leaf) {
    Assert-HumanEvidenceMatchesPrefill -MachinePrefill $machinePrefill -HumanEvidence $humanEvidence
    $humanEvidence = Need-File -Path $humanEvidence -Label "Quest2 human-reviewed evidence"
    Write-Host "Existing human review evidence revalidated against the exact machine prefill; skipping interactive review."
} else {
    Invoke-BodyRigOperator -Pwsh $pwsh -Script $humanReviewScript -Arguments @(
        "-MachinePrefill", $machinePrefill
    ) -Label "Quest2 human physical review"

    $humanEvidence = Need-File -Path $humanEvidence -Label "Quest2 human-reviewed evidence"
}

$recorderArgs = @(
    "-RuntimeReviewWorkspace", $RuntimeReviewWorkspace,
    "-Evidence", $humanEvidence,
    "-ReuseExisting"
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
