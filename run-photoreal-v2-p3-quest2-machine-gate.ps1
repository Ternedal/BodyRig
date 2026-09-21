param(
    [Parameter(Mandatory = $true)][string]$RuntimeReviewWorkspace,
    [Parameter(Mandatory = $true)][string]$StudentOutputRoot,
    [string]$MachineGateRoot = "",
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Quest2 P3 machine gate is Windows-orchestrated."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the Quest2 P3 machine gate."
}

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

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-ChildOperator {
    param(
        [Parameter(Mandatory = $true)][string]$Pwsh,
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Write-Host ""
    Write-Host "=== $Label ==="
    $lines = @(
        & $Pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments 2>&1
    )
    $code = $LASTEXITCODE
    foreach ($line in $lines) {
        Write-Host ([string]$line)
    }
    if ($code -ne 0) {
        throw "$Label failed with exit code $code."
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 P3 machine gate requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$RuntimeReviewWorkspace = Need-Directory -Path $RuntimeReviewWorkspace -Label "P3 runtime review workspace"
$StudentOutputRoot = Need-Directory -Path $StudentOutputRoot -Label "Final P3 student output root"
$planPath = Need-File -Path (Join-Path $RuntimeReviewWorkspace "p3-device-runtime-review-plan.json") -Label "P3 runtime review plan"
$plan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    [string]$plan.format -ne "bodyrig-photoreal-p3-device-runtime-review-plan" -or
    $plan.version -is [bool] -or
    [double]$plan.version -ne 1.0 -or
    [string]$plan.target_device_family -ne "meta-quest" -or
    [string]$plan.target_device_model -ne "quest-2"
) {
    throw "P3 runtime review plan is not an exact Quest 2 plan."
}
$planSha = ([string]$plan.p3_device_runtime_review_plan_sha256).Trim().ToLowerInvariant()
if ($planSha -notmatch '^[0-9a-f]{64}$') {
    throw "P3 runtime review plan SHA-256 is invalid."
}

$pwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwshCommand) {
    throw "pwsh executable not found."
}
$pwsh = $pwshCommand.Source

$handoffScript = Need-File -Path (Join-Path $repoRoot "prepare-photoreal-v2-p3-quest2-device-handoff.ps1") -Label "P3 Quest2 device handoff operator"
$probeScript = Need-File -Path (Join-Path $repoRoot "run-photoreal-v2-p3-quest2-reference-probe.ps1") -Label "P3 Quest2 OpenXR reference probe operator"
$prefillScript = Need-File -Path (Join-Path $repoRoot "prepare-photoreal-v2-p3-quest2-physical-evidence-from-machine.ps1") -Label "P3 Quest2 physical-review prefill operator"

if ([string]::IsNullOrWhiteSpace($MachineGateRoot)) {
    $MachineGateRoot = Join-Path $RuntimeReviewWorkspace "p3-quest2-machine-gate"
} else {
    $MachineGateRoot = [IO.Path]::GetFullPath($MachineGateRoot)
}
if (Test-Path -LiteralPath $MachineGateRoot) {
    throw "Quest2 P3 machine gate workspace already exists: $MachineGateRoot"
}
New-Item -ItemType Directory -Path $MachineGateRoot | Out-Null
$MachineGateRoot = Need-Directory -Path $MachineGateRoot -Label "Quest2 P3 machine gate workspace"

$handoffRoot = Join-Path $MachineGateRoot "handoff"
$probeRoot = Join-Path $MachineGateRoot "reference-probe"
$prefillPath = Join-Path $MachineGateRoot "p3-physical-runtime-evidence.machine-prefill.json"
$gateReceiptPath = Join-Path $MachineGateRoot "p3-quest2-machine-gate.json"

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 P3 MACHINE GATE"
Write-Host "Revision:             $head"
Write-Host "Runtime review plan:  $planPath"
Write-Host "Plan SHA:             $planSha"
Write-Host "Student output:       $StudentOutputRoot"
Write-Host "Workspace:            $MachineGateRoot"
Write-Host "Human visual review:  REQUIRED AFTER MACHINE GATE"
Write-Host "Production:           FALSE"
Write-Host "============================================================"

$handoffArgs = @(
    "-RuntimeReviewWorkspace", $RuntimeReviewWorkspace,
    "-StudentOutputRoot", $StudentOutputRoot,
    "-DeviceSessionRoot", $handoffRoot
)
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    $handoffArgs += @("-AdbExe", $AdbExe)
}
if (-not [string]::IsNullOrWhiteSpace($Serial)) {
    $handoffArgs += @("-Serial", $Serial)
}
Invoke-ChildOperator -Pwsh $pwsh -Script $handoffScript -Arguments $handoffArgs -Label "1/3 EXACT QUEST2 BYTE HANDOFF"

$handoffReceipt = Need-File -Path (Join-Path $handoffRoot "p3-quest2-device-handoff.json") -Label "P3 Quest2 device handoff receipt"

$probeArgs = @(
    "-RuntimeReviewWorkspace", $RuntimeReviewWorkspace,
    "-StudentOutputRoot", $StudentOutputRoot,
    "-DeviceHandoffReceipt", $handoffReceipt,
    "-ProbeWorkspace", $probeRoot
)
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) {
    $probeArgs += @("-UnityExe", $UnityExe)
}
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    $probeArgs += @("-AdbExe", $AdbExe)
}
if (-not [string]::IsNullOrWhiteSpace($Serial)) {
    $probeArgs += @("-Serial", $Serial)
}
Invoke-ChildOperator -Pwsh $pwsh -Script $probeScript -Arguments $probeArgs -Label "2/3 PHYSICAL QUEST2 OPENXR MACHINE PROBE"

$machineProbe = Need-File -Path (Join-Path $probeRoot "p3-quest2-machine-probe.json") -Label "P3 Quest2 machine probe"
$probeSummary = Need-File -Path (Join-Path $probeRoot "p3-quest2-reference-probe-summary.json") -Label "P3 Quest2 reference probe summary"

$prefillArgs = @(
    "-RuntimeReviewWorkspace", $RuntimeReviewWorkspace,
    "-MachineProbe", $machineProbe,
    "-Output", $prefillPath
)
Invoke-ChildOperator -Pwsh $pwsh -Script $prefillScript -Arguments $prefillArgs -Label "3/3 MACHINE-SAFE HUMAN REVIEW PREFILL"

$prefillPath = Need-File -Path $prefillPath -Label "P3 physical review machine prefill"
$prefill = Get-Content -LiteralPath $prefillPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    [string]$prefill.format -ne "bodyrig-photoreal-p3-physical-runtime-evidence" -or
    $prefill.version -is [bool] -or
    [double]$prefill.version -ne 1.0 -or
    $prefill.operator_supplied -isnot [bool] -or
    $prefill.operator_supplied -ne $false -or
    $prefill.physical_device_observed -isnot [bool] -or
    $prefill.physical_device_observed -ne $true -or
    $prefill.stereo_rendering_observed -isnot [bool] -or
    $prefill.stereo_rendering_observed -ne $true -or
    $prefill.vr_safe_frame_pacing_observed -isnot [bool] -or
    $prefill.vr_safe_frame_pacing_observed -ne $true -or
    $prefill.installed_student_hashes_verified_on_device -isnot [bool] -or
    $prefill.installed_student_hashes_verified_on_device -ne $true -or
    $prefill.confirm_physical_device_review_complete -isnot [bool] -or
    $prefill.confirm_physical_device_review_complete -ne $false
) {
    throw "Quest2 P3 machine gate produced a non-canonical human review prefill."
}
foreach ($visual in @($prefill.visual_results)) {
    if ([string]$visual.decision -ne "REVIEW_REQUIRED") {
        throw "Quest2 P3 machine gate unexpectedly manufactured a human visual decision."
    }
}

$gateReceipt = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-machine-gate"
    version = 1
    bodyrig_revision = $head
    p3_device_runtime_review_plan_sha256 = $planSha
    p3_quest2_device_handoff_sha256 = Sha256 $handoffReceipt
    p3_quest2_machine_probe_sha256 = Sha256 $machineProbe
    p3_quest2_reference_probe_summary_sha256 = Sha256 $probeSummary
    p3_physical_runtime_evidence_prefill_sha256 = Sha256 $prefillPath
    target_device_family = "meta-quest"
    target_device_model = "quest-2"
    physical_machine_gate_complete = $true
    installed_student_hashes_verified_on_device = $true
    stereo_rendering_observed = $true
    vr_safe_frame_pacing_observed = $true
    human_runtime_visual_acceptance_required = $true
    physical_device_review_complete = $false
    runtime_acceptance_authority = $false
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$gateReceipt | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $gateReceiptPath -Encoding UTF8
$gateReceiptPath = Need-File -Path $gateReceiptPath -Label "P3 Quest2 machine gate receipt"

Write-Host ""
Write-Host "============================================================"
Write-Host "QUEST2 P3 MACHINE GATE: COMPLETE"
Write-Host "Exact byte handoff:        PASS"
Write-Host "OpenXR runtime load:       PASS"
Write-Host "Installed hashes:          PASS"
Write-Host "Stereo rendering:          PASS"
Write-Host "VR-safe frame pacing:      PASS"
Write-Host "Human visual review:       REQUIRED"
Write-Host "Runtime acceptance:        FALSE"
Write-Host "Photoreal acceptance:      FALSE"
Write-Host "Production:                FALSE"
Write-Host "============================================================"
Write-Host "Machine gate receipt: $gateReceiptPath"
Write-Host "Human review prefill: $prefillPath"
Write-Host ""
Write-Host "Next: complete the eight REVIEW_REQUIRED visual decisions in Quest 2,"
Write-Host "set operator_supplied=true and confirm_physical_device_review_complete=true,"
Write-Host "then run record-photoreal-v2-p3-quest2-physical-runtime-review.ps1."
exit 0
