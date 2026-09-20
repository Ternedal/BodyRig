param(
    [Parameter(Mandatory = $true)][string]$SourceRun,
    [string]$PerformerId = "42",
    [string]$RunRoot = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 }
    catch { throw "$Label is unreadable JSON: $Path" }
}

function Test-NumericV1 {
    param([AllowNull()]$Value)
    if ($null -eq $Value -or $Value -is [bool]) { return $false }
    try { $number = [double]$Value } catch { return $false }
    return (-not [double]::IsNaN($number)) -and (-not [double]::IsInfinity($number)) -and $number -eq 1.0
}

function Test-StrictBoolean {
    param([AllowNull()]$Value,[Parameter(Mandatory = $true)][bool]$Expected)
    return ($Value -is [bool]) -and ([bool]$Value -eq $Expected)
}

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath (Need-File -Path $Path -Label "Hash input") -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Copy-Evidence {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $resolved = Need-File -Path $Source -Label $Label
    Copy-Item -LiteralPath $resolved -Destination $Destination
    if ((Sha256 $resolved) -ne (Sha256 $Destination)) { throw "Copied evidence changed bytes: $Label" }
    return (Resolve-Path -LiteralPath $Destination).Path
}

function Invoke-PythonStage {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int[]]$AllowedExitCodes = @(0)
    )
    Write-Host ""
    Write-Host "=== $Label ==="
    $stageOutput = @(& $script:Python @Arguments 2>&1)
    $code = $LASTEXITCODE
    foreach ($line in $stageOutput) { Write-Host ([string]$line) }
    if ($AllowedExitCodes -notcontains $code) { throw "$Label failed with exit code $code." }
    return $code
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "Photoreal Stage-16 remediation is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Photoreal Stage-16 remediation must run from canonical main."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$Head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($Head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Photoreal Stage-16 remediation requires an exact clean BodyRig checkout." }

$SourceRun = Need-Directory -Path $SourceRun -Label "Blocked Stage-16 P0 root"
$sourceStatusPath = Need-File -Path (Join-Path $SourceRun "p0-status.json") -Label "Blocked P0 status"
$sourceIndexPath = Need-File -Path (Join-Path $SourceRun "frame-index.json") -Label "Blocked frame index"
$sourceStatus = Read-Json -Path $sourceStatusPath -Label "Blocked P0 status"
$sourceIndex = Read-Json -Path $sourceIndexPath -Label "Blocked frame index"

if ([string]$sourceStatus.format -ne "bodyrig-photoreal-p0-status" -or -not (Test-NumericV1 -Value $sourceStatus.version)) {
    throw "Blocked P0 status format/version mismatch."
}
if ([string]$sourceStatus.performer_id -ne $PerformerId) { throw "Blocked P0 status performer mismatch." }
if ([string]$sourceStatus.status -ne "frame-index-blocked" -or -not (Test-StrictBoolean -Value $sourceStatus.teacher_training_authorized -Expected $false)) {
    throw "Source P0 root is not a frame-index-blocked root."
}
$sourceBlockers = @($sourceStatus.blockers | ForEach-Object { [string]$_ })
if ($sourceBlockers.Count -ne 1 -or $sourceBlockers[0] -ne "cross-split perceptual near-duplicates detected") {
    throw "Stage-16 remediation only accepts a P0 root blocked solely by cross-split perceptual near-duplicates."
}

if ([string]$sourceIndex.format -ne "bodyrig-photoreal-frame-index" -or -not (Test-NumericV1 -Value $sourceIndex.version)) {
    throw "Blocked frame index format/version mismatch."
}
if ([string]$sourceIndex.performer_id -ne $PerformerId) { throw "Blocked frame index performer mismatch." }
if (-not (Test-StrictBoolean -Value $sourceIndex.teacher_training_authorized -Expected $false)) {
    throw "Blocked frame index unexpectedly authorizes teacher training."
}
if ([int]$sourceIndex.cross_split_near_duplicate_count -lt 1) {
    throw "Blocked frame index contains no cross-split near-duplicates to remediate."
}
if (@($sourceIndex.held_out_view_coverage_missing).Count -ne 0) {
    throw "Blocked frame index also lacks held-out view coverage; automatic near-duplicate remediation is not sufficient."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython -PathType Leaf) { $Python = (Resolve-Path -LiteralPath $localPython).Path }
    else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python was not found." }
        $Python = $command.Source
    }
} else {
    $Python = Need-File -Path $BodyRigPython -Label "BodyRig Python"
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }
if ([string]::IsNullOrWhiteSpace($RunRoot)) { $RunRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\overnight" }
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputRoot = Join-Path $RunRoot ("performer-{0}-{1}-resume16" -f $PerformerId, $stamp)
if (Test-Path -LiteralPath $OutputRoot) { throw "Stage-16 remediation output already exists: $OutputRoot" }
New-Item -ItemType Directory -Path $OutputRoot | Out-Null

$copyNames = @(
    "dataset-plan.json",
    "source-receipt.json",
    "scan-plan.json",
    "model-set.json",
    "identity-bank.json",
    "identity-calibration.json",
    "frame-measurements.json",
    "frame-authorized-observations.json"
)
$copiedHashes = [ordered]@{}
foreach ($name in $copyNames) {
    $destination = Join-Path $OutputRoot $name
    Copy-Evidence -Source (Join-Path $SourceRun $name) -Destination $destination -Label $name | Out-Null
    $copiedHashes[$name] = Sha256 $destination
}

$preIndex = Join-Path $OutputRoot "pre-remediation-frame-index.json"
$preStatus = Join-Path $OutputRoot "pre-remediation-p0-status.json"
Copy-Evidence -Source $sourceIndexPath -Destination $preIndex -Label "pre-remediation frame index" | Out-Null
Copy-Evidence -Source $sourceStatusPath -Destination $preStatus -Label "pre-remediation P0 status" | Out-Null

$PlanPath = Join-Path $OutputRoot "dataset-plan.json"
$ReceiptPath = Join-Path $OutputRoot "source-receipt.json"
$AuthorizedObservationsPath = Join-Path $OutputRoot "frame-authorized-observations.json"
$FrameIndexPath = Join-Path $OutputRoot "frame-index.json"
$StatusPath = Join-Path $OutputRoot "p0-status.json"
$RemediationReceiptPath = Join-Path $OutputRoot "stage16-remediation-receipt.json"

$priorPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })

try {
    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - RESUME FROM STAGE 16"
    Write-Host "Revision:          $Head"
    Write-Host "Performer:         $PerformerId"
    Write-Host "Source P0 root:    $SourceRun"
    Write-Host "Output:            $OutputRoot"
    Write-Host "Frame re-analysis: NO"
    Write-Host "Source rehash:     NO"
    Write-Host "Identity rebuild:  NO"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"

    $indexExit = Invoke-PythonStage -Label "16/16 LEAKAGE + HELD-OUT COVERAGE REMEDIATION" -AllowedExitCodes @(0,2) -Arguments @(
        "-m","bodyrig.photoreal_frame_index_cli",
        "--plan",$PlanPath,
        "--receipt",$ReceiptPath,
        "--authorized-observations",$AuthorizedObservationsPath,
        "--out",$FrameIndexPath
    )

    $frameIndex = Read-Json -Path $FrameIndexPath -Label "Remediated frame index"
    $trainingAuthorized = ($indexExit -eq 0 -and (Test-StrictBoolean -Value $frameIndex.teacher_training_authorized -Expected $true))
    $blockers = @($frameIndex.training_blockers | ForEach-Object { [string]$_ })
    if (-not $trainingAuthorized -and $blockers.Count -eq 0) { $blockers = @("Remediated frame index did not grant teacher-training authority.") }

    $authorized = Read-Json -Path $AuthorizedObservationsPath -Label "Authorized frame observations"
    $rows = @($authorized.observations)
    $sourceBoundVerified = @($rows | Where-Object { $_.target_identity_verified -eq $true -and $_.identity_authority -eq "stash-single-performer-target-binding-v1" }).Count
    $calibratedVerified = @($rows | Where-Object { $_.target_identity_verified -eq $true -and $_.identity_authority -eq "calibrated-identity-bank-v1" }).Count
    $unresolved = @($rows | Where-Object { $_.target_identity_verified -ne $true }).Count

    $status = [ordered]@{
        format = "bodyrig-photoreal-p0-status"
        version = 1
        bodyrig_revision = $Head
        performer_id = $PerformerId
        status = $(if ($trainingAuthorized) { "teacher-training-authorized" } else { "frame-index-blocked" })
        teacher_training_authorized = $trainingAuthorized
        blockers = @($blockers)
        human_visual_acceptance_required = $true
        photoreal_acceptance_authority = $false
        production_activation = $false
        resumed_from_stage16_run = $SourceRun
        source_rehash_skipped_explicitly = $true
        frame_reanalysis = $false
        identity_bank_rebuild = $false
        identity_calibration_rebuild = $false
        source_bound_verified_observation_count = $sourceBoundVerified
        calibrated_verified_observation_count = $calibratedVerified
        unresolved_observation_count = $unresolved
        outputs = [ordered]@{
            dataset_plan = $PlanPath
            source_receipt = $ReceiptPath
            scan_plan = (Join-Path $OutputRoot "scan-plan.json")
            model_set = (Join-Path $OutputRoot "model-set.json")
            identity_bank = (Join-Path $OutputRoot "identity-bank.json")
            identity_calibration = (Join-Path $OutputRoot "identity-calibration.json")
            frame_measurements = (Join-Path $OutputRoot "frame-measurements.json")
            frame_authorized_observations = $AuthorizedObservationsPath
            frame_index = $FrameIndexPath
            stage16_remediation_receipt = $RemediationReceiptPath
        }
    }

    $receipt = [ordered]@{
        format = "bodyrig-photoreal-stage16-remediation-receipt"
        version = 1
        bodyrig_revision = $Head
        performer_id = $PerformerId
        source_p0_root = $SourceRun
        source_p0_status_sha256 = Sha256 $sourceStatusPath
        source_frame_index_sha256 = Sha256 $sourceIndexPath
        copied_artifacts_sha256 = $copiedHashes
        prior_cross_split_near_duplicate_count = [int]$sourceIndex.cross_split_near_duplicate_count
        detected_cross_split_near_duplicate_count = [int]$frameIndex.cross_split_detected_near_duplicate_count
        quarantined_train_observation_count = [int]$frameIndex.cross_split_quarantined_train_observation_count
        remaining_cross_split_near_duplicate_count = [int]$frameIndex.cross_split_near_duplicate_count
        teacher_training_authorized = $trainingAuthorized
        human_visual_acceptance_required = $true
        photoreal_acceptance_authority = $false
        production_activation = $false
    }
    $receipt | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $RemediationReceiptPath -Encoding UTF8
    $status | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $StatusPath -Encoding UTF8

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - STAGE 16 REMEDIATION COMPLETE"
    Write-Host "Detected near-dupes:   $([int]$frameIndex.cross_split_detected_near_duplicate_count)"
    Write-Host "Train quarantined:     $([int]$frameIndex.cross_split_quarantined_train_observation_count)"
    Write-Host "Remaining near-dupes:  $([int]$frameIndex.cross_split_near_duplicate_count)"
    Write-Host "Eligible train:        $([int]$frameIndex.eligible_train_observation_count)"
    Write-Host "Eligible evaluation:   $([int]$frameIndex.eligible_evaluation_observation_count)"
    Write-Host "Teacher training:      $(if ($trainingAuthorized) { 'AUTHORIZED' } else { 'BLOCKED' })"
    if ($blockers.Count -gt 0) { foreach ($blocker in $blockers) { Write-Host ("  blocker: {0}" -f $blocker) } }
    Write-Host "Photoreal accept:      FALSE"
    Write-Host "Production:            FALSE"
    Write-Host "Status:                $StatusPath"
    Write-Host "============================================================"

    exit $(if ($trainingAuthorized) { 0 } else { 2 })
}
finally {
    $env:PYTHONPATH = $priorPythonPath
}
