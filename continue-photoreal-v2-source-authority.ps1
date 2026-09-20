param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [string]$OutputRoot = "",
    [string]$ModelRoot = "",
    [string]$BodyRigPython = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [ValidateSet("cpu","cuda","cuda:0")][string]$VisionDevice = "cuda:0",
    [string]$PerformerId = "42"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-Json {
    param([string]$Path,[string]$Label)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 }
    catch { throw "$Label is unreadable JSON: $Path" }
}

function Invoke-PythonStage {
    param([string]$Label,[string[]]$Arguments,[int[]]$AllowedExitCodes = @(0))
    Write-Host ""
    Write-Host "=== $Label ==="
    $lines = @(& $script:Python @Arguments 2>&1)
    $code = $LASTEXITCODE
    foreach ($line in $lines) { Write-Host ([string]$line) }
    if ($AllowedExitCodes -notcontains $code) { throw "$Label failed with exit code $code." }
    return $code
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchName = ([string](& git -C $repoRoot branch --show-current)).Trim()
if ($LASTEXITCODE -ne 0 -or $branchName -ne "main") { throw "Continuation requires canonical main." }
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw "Continuation requires a clean checkout." }
$Head = ([string](& git -C $repoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $Head -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve exact BodyRig HEAD." }

$RunDirectory = Need-Directory $RunDirectory "Blocked P0 run"
$required = @(
    "dataset-plan.json",
    "source-receipt.json",
    "scan-plan.json",
    "model-set.json",
    "identity-bank.json",
    "identity-calibration.json",
    "source-resume-receipt.json"
)
foreach ($name in $required) { Need-File (Join-Path $RunDirectory $name) "Required artifact $name" | Out-Null }

$plan = Read-Json (Join-Path $RunDirectory "dataset-plan.json") "Dataset plan"
if ([string]$plan.performer_id -ne $PerformerId) { throw "Dataset plan performer mismatch." }
$calibration = Read-Json (Join-Path $RunDirectory "identity-calibration.json") "Identity calibration"
if ([string]$calibration.target_performer_id -ne $PerformerId) { throw "Calibration performer mismatch." }
if ($calibration.identity_matching_authorized -ne $false -or $calibration.match_threshold_calibrated -ne $false -or $null -ne $calibration.match_threshold) {
    throw "This continuation is only for a persisted uncalibrated identity result."
}

$resumeReceipt = Read-Json (Join-Path $RunDirectory "source-resume-receipt.json") "Source resume receipt"
$ProjectionAuthority = Need-File ([string]$resumeReceipt.projection_authority) "Projection authority"

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }
if ([string]::IsNullOrWhiteSpace($ModelRoot)) { $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models" }
$ModelRoot = Need-Directory $ModelRoot "Reference model root"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $Python = (Resolve-Path -LiteralPath $candidate).Path }
    else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python not found." }
        $Python = $command.Source
    }
} else {
    $Python = Need-File $BodyRigPython "BodyRig Python"
}
$script:Python = $Python

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputRoot = "$RunDirectory-sourceauth-$stamp"
}
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) { throw "Output already exists: $OutputRoot" }
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$reusedHashes = [ordered]@{}
foreach ($name in $required) {
    $source = Join-Path $RunDirectory $name
    $destination = Join-Path $OutputRoot $name
    Copy-Item -LiteralPath $source -Destination $destination
    $before = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    $after = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($before -ne $after) { throw "Copied authority artifact changed: $name" }
    $reusedHashes[$name] = $before
}

$FrameAnalyzerWorkspace = Join-Path $OutputRoot "frame-analyzer"
$FrameMeasurementsPath = Join-Path $OutputRoot "frame-measurements.json"
$AuthorizedObservationsPath = Join-Path $OutputRoot "frame-authorized-observations.json"
$FrameIndexPath = Join-Path $OutputRoot "frame-index.json"
$StatusPath = Join-Path $OutputRoot "p0-status.json"
$ContinuationPath = Join-Path $OutputRoot "source-authority-continuation.json"

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-photoreal-sourceauth-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$identityConfig = Join-Path $tempRoot "identity.json"
$frameConfig = Join-Path $tempRoot "frame.json"
$adapter = Need-File (Join-Path $repoRoot "tools\photoreal_reference_vision_adapter.py") "Reference vision adapter"
$probe = Need-File (Join-Path $repoRoot "tools\photoreal_reference_vision_probe.py") "Reference vision probe"

$oldProjection = [Environment]::GetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", "Process")
$oldPythonPath = $env:PYTHONPATH
try {
    [Environment]::SetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", $ProjectionAuthority, "Process")
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$oldPythonPath" })

    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - CONTINUE FROM SOURCE AUTHORITY"
    Write-Host "Revision:          $Head"
    Write-Host "Performer:         $PerformerId"
    Write-Host "Input run:         $RunDirectory"
    Write-Host "Output:            $OutputRoot"
    Write-Host "Start stage:       14/16"
    Write-Host "Source rehash:     NO"
    Write-Host "Negative sampling: NO"
    Write-Host "Calibration rerun: NO"
    Write-Host "Source authority:  stash-single-performer-target-binding-v1"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"

    $preflightArgs = @(
        "-m","bodyrig.photoreal_reference_vision_preflight",
        "--adapter-path",$adapter,
        "--probe-path",$probe,
        "--model-root",$ModelRoot,
        "--distribution",$Distribution,
        "--linux-python",$LinuxPython,
        "--device",$VisionDevice
    )
    Invoke-PythonStage "PREFLIGHT PINNED VISION STACK" $preflightArgs | Out-Null

    $configArgs = @(
        "-m","bodyrig.photoreal_reference_vision_config",
        "--model-root",$ModelRoot,
        "--adapter-path",$adapter,
        "--windows-python",$Python,
        "--distribution",$Distribution,
        "--linux-python",$LinuxPython,
        "--device",$VisionDevice,
        "--identity-out",$identityConfig,
        "--frame-out",$frameConfig
    )
    Invoke-PythonStage "PREFLIGHT CURRENT FRAME ANALYZER CONFIG" $configArgs | Out-Null

    $measureArgs = @(
        "-m","bodyrig.photoreal_frame_analyzer_cli",
        "--config",$frameConfig,
        "--scan-plan",(Join-Path $OutputRoot "scan-plan.json"),
        "--workspace",$FrameAnalyzerWorkspace,
        "--out",$FrameMeasurementsPath
    )
    Invoke-PythonStage "14/16 MEASURE ALL PLANNED FRAMES" $measureArgs | Out-Null

    $authorityArgs = @(
        "-m","bodyrig.photoreal_frame_identity_authority_cli",
        "--plan",(Join-Path $OutputRoot "dataset-plan.json"),
        "--measurements",$FrameMeasurementsPath,
        "--identity-bank",(Join-Path $OutputRoot "identity-bank.json"),
        "--identity-calibration",(Join-Path $OutputRoot "identity-calibration.json"),
        "--out",$AuthorizedObservationsPath
    )
    Invoke-PythonStage "15/16 APPLY CORE SOURCE/IDENTITY AUTHORITY" $authorityArgs | Out-Null

    $indexArgs = @(
        "-m","bodyrig.photoreal_frame_index_cli",
        "--plan",(Join-Path $OutputRoot "dataset-plan.json"),
        "--receipt",(Join-Path $OutputRoot "source-receipt.json"),
        "--authorized-observations",$AuthorizedObservationsPath,
        "--out",$FrameIndexPath
    )
    $indexExit = Invoke-PythonStage "16/16 LEAKAGE + HELD-OUT COVERAGE GATE" $indexArgs @(0,2)

    $authorized = Read-Json $AuthorizedObservationsPath "Authorized observations"
    $frameIndex = Read-Json $FrameIndexPath "Frame index"
    $verified = @($authorized.observations | Where-Object { $_.target_identity_verified -eq $true }).Count
    $sourceVerified = @($authorized.observations | Where-Object { $_.target_identity_verified -eq $true -and [string]$_.identity_authority -eq "stash-single-performer-target-binding-v1" }).Count
    $calibratedVerified = @($authorized.observations | Where-Object { $_.target_identity_verified -eq $true -and [string]$_.identity_authority -eq "calibrated-identity-bank-v1" }).Count
    $unresolved = @($authorized.observations | Where-Object { $_.target_identity_verified -ne $true }).Count
    $trainingAuthorized = ($indexExit -eq 0 -and $frameIndex.teacher_training_authorized -eq $true)
    $blockers = @($frameIndex.training_blockers | ForEach-Object { [string]$_ })

    $status = [ordered]@{
        format = "bodyrig-photoreal-p0-status"
        version = 1
        bodyrig_revision = $Head
        performer_id = $PerformerId
        status = $(if ($trainingAuthorized) { "teacher-training-authorized" } else { "frame-index-blocked" })
        teacher_training_authorized = $trainingAuthorized
        blockers = $blockers
        human_visual_acceptance_required = $true
        photoreal_acceptance_authority = $false
        production_activation = $false
        outputs = [ordered]@{
            dataset_plan = (Join-Path $OutputRoot "dataset-plan.json")
            source_receipt = (Join-Path $OutputRoot "source-receipt.json")
            scan_plan = (Join-Path $OutputRoot "scan-plan.json")
            model_set = (Join-Path $OutputRoot "model-set.json")
            identity_bank = (Join-Path $OutputRoot "identity-bank.json")
            identity_calibration = (Join-Path $OutputRoot "identity-calibration.json")
            frame_measurements = $FrameMeasurementsPath
            frame_authorized_observations = $AuthorizedObservationsPath
            frame_index = $FrameIndexPath
        }
    }
    $status | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $StatusPath -Encoding UTF8

    $continuation = [ordered]@{
        format = "bodyrig-photoreal-source-authority-continuation"
        version = 1
        bodyrig_revision = $Head
        performer_id = $PerformerId
        input_run = $RunDirectory
        reused_artifacts_sha256 = $reusedHashes
        source_rehash_performed = $false
        negative_sampling_performed = $false
        identity_calibration_rerun = $false
        identity_matching_calibrated = $false
        source_authority = "stash-single-performer-target-binding-v1"
        observation_count = @($authorized.observations).Count
        target_identity_verified_count = $verified
        source_authority_verified_count = $sourceVerified
        calibrated_identity_verified_count = $calibratedVerified
        identity_unresolved_count = $unresolved
        teacher_training_authorized = $trainingAuthorized
        training_blockers = $blockers
        photoreal_acceptance_authority = $false
        production_activation = $false
    }
    $continuation | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ContinuationPath -Encoding UTF8

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "SOURCE AUTHORITY CONTINUATION COMPLETE"
    Write-Host "Verified total:    $verified"
    Write-Host "Source-bound:      $sourceVerified"
    Write-Host "Calibrated-match:  $calibratedVerified"
    Write-Host "Unresolved:        $unresolved"
    Write-Host "Teacher training:  $(if ($trainingAuthorized) { 'AUTHORIZED' } else { 'BLOCKED' })"
    foreach ($blocker in $blockers) { Write-Host "Blocker:           $blocker" }
    Write-Host "P0 status:         $StatusPath"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"
    exit $(if ($trainingAuthorized) { 0 } else { 2 })
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    [Environment]::SetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", $oldProjection, "Process")
    if (Test-Path -LiteralPath $tempRoot -PathType Container) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
