param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$PathMap = "",
    [string]$BodyRigPython = "",
    [double]$EvalFraction = 0.20,
    [string]$SplitSeed = "bodyrig-photoreal-v2",
    [string]$ModelRoot = "",
    [string]$IdentityExtractorConfig = "",
    [string]$FrameAnalyzerConfig = "",
    [switch]$SourceOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    } catch {
        throw "$Label is unreadable JSON: $Path"
    }
}

function Test-StrictBoolean {
    param(
        [AllowNull()]$Value,
        [Parameter(Mandatory = $true)][bool]$Expected
    )
    return ($Value -is [bool]) -and ([bool]$Value -eq $Expected)
}

function Write-Status {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][bool]$TeacherTrainingAuthorized,
        [Parameter(Mandatory = $true)][string[]]$Blockers
    )
    $payload = [ordered]@{
        format = "bodyrig-photoreal-p0-status"
        version = 1
        bodyrig_revision = $script:Head
        performer_id = $PerformerId
        status = $Status
        teacher_training_authorized = $TeacherTrainingAuthorized
        blockers = @($Blockers)
        human_visual_acceptance_required = $true
        photoreal_acceptance_authority = $false
        production_activation = $false
        outputs = [ordered]@{
            source_inventory = $script:InventoryPath
            dataset_plan = $script:PlanPath
            source_receipt = $script:ReceiptPath
            spatial_metadata_probe = $script:SpatialMetadataProbePath
            scan_plan = $script:ScanPlanPath
            identity_bootstrap = $script:IdentityBootstrapPath
            model_set = $script:ModelSetPath
            identity_bank = $script:IdentityBankPath
            identity_negative_inventory = $script:NegativeInventoryPath
            identity_negative_receipt = $script:NegativeReceiptPath
            identity_calibration_plan = $script:CalibrationPlanPath
            identity_calibration = $script:CalibrationPath
            frame_measurements = $script:FrameMeasurementsPath
            frame_authorized_observations = $script:AuthorizedObservationsPath
            frame_index = $script:FrameIndexPath
        }
    }
    $payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $script:StatusPath -Encoding UTF8
}

function Invoke-PythonStage {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int[]]$AllowedExitCodes = @(0)
    )
    Write-Host ""
    Write-Host "=== $Label ==="
    $stageOutput = @(& $script:Python @Arguments)
    $code = $LASTEXITCODE
    foreach ($line in $stageOutput) { Write-Host ([string]$line) }
    if ($AllowedExitCodes -notcontains $code) {
        throw "$Label failed with exit code $code."
    }
    return $code
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$Head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($Head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Photoreal P0 requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($PerformerId)) { throw "PerformerId is required." }
if ($EvalFraction -lt 0.10 -or $EvalFraction -gt 0.40) { throw "EvalFraction must be in 0.10..0.40." }
if ([string]::IsNullOrWhiteSpace($SplitSeed)) { throw "SplitSeed is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $Python = (Resolve-Path -LiteralPath $localPython).Path
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python was not found." }
        $Python = $command.Source
    }
} else {
    $Python = Need-File -Path $BodyRigPython -Label "BodyRig Python"
}

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    $stashConfigPath = Join-Path $env:LOCALAPPDATA "BodyRig\config\stash.json"
    if (Test-Path -LiteralPath $stashConfigPath -PathType Leaf) {
        $stashConfig = Read-Json -Path $stashConfigPath -Label "BodyRig Stash config"
        $StashUrl = [string]$stashConfig.url
    }
}
if ([string]::IsNullOrWhiteSpace($StashUrl)) { throw "StashUrl or STASH_URL is required." }
if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($ApiKeyEnv))) {
    throw "Stash API key environment variable '$ApiKeyEnv' is missing in this PowerShell process."
}

$PathMapWasExplicit = -not [string]::IsNullOrWhiteSpace($PathMap)
if ($PathMapWasExplicit) {
    $PathMap = Need-File -Path $PathMap -Label "Explicit Stash path map"
}

$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) { throw "Photoreal P0 output root already exists: $OutputRoot" }
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$InventoryPath = Join-Path $OutputRoot "source-inventory.json"
$GeneratedSourcePathMap = Join-Path $OutputRoot "source-path-map.json"
$GeneratedCalibrationPathMap = Join-Path $OutputRoot "calibration-path-map.json"
$PlanPath = Join-Path $OutputRoot "dataset-plan.json"
$ReceiptPath = Join-Path $OutputRoot "source-receipt.json"
$SpatialMetadataProbePath = Join-Path $OutputRoot "spatial-metadata-probe.json"
$ScanPlanPath = Join-Path $OutputRoot "scan-plan.json"
$IdentityBootstrapPath = Join-Path $OutputRoot "identity-bootstrap-plan.json"
$ModelSetPath = Join-Path $OutputRoot "model-set.json"
$IdentityExtractWorkspace = Join-Path $OutputRoot "identity-extractor"
$IdentityObservationsPath = Join-Path $IdentityExtractWorkspace "output\identity-observations.json"
$IdentityBankPath = Join-Path $OutputRoot "identity-bank.json"
$NegativeInventoryPath = Join-Path $OutputRoot "identity-negative-inventory.json"
$NegativeReceiptPath = Join-Path $OutputRoot "identity-negative-receipt.json"
$CalibrationPlanPath = Join-Path $OutputRoot "identity-calibration-plan.json"
$CalibrationExtractWorkspace = Join-Path $OutputRoot "identity-calibration-extractor"
$NegativeObservationsPath = Join-Path $CalibrationExtractWorkspace "output\negative-observations.json"
$CalibrationPath = Join-Path $OutputRoot "identity-calibration.json"
$FrameAnalyzerWorkspace = Join-Path $OutputRoot "frame-analyzer"
$FrameMeasurementsPath = Join-Path $OutputRoot "frame-measurements.json"
$AuthorizedObservationsPath = Join-Path $OutputRoot "frame-authorized-observations.json"
$FrameIndexPath = Join-Path $OutputRoot "frame-index.json"
$StatusPath = Join-Path $OutputRoot "p0-status.json"

if (-not $SourceOnly) {
    $ModelRoot = Need-Directory -Path $ModelRoot -Label "Photoreal analyzer model root"
    $IdentityExtractorConfig = Need-File -Path $IdentityExtractorConfig -Label "Photoreal identity extractor config"
    $FrameAnalyzerConfig = Need-File -Path $FrameAnalyzerConfig -Label "Photoreal frame analyzer config"
}

$pathMapDisplay = $(if ($PathMapWasExplicit) { $PathMap } else { "EXACT INVENTORY-DERIVED" })
Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P0"
Write-Host "Revision:          $Head"
Write-Host "Performer:         $PerformerId"
Write-Host "Output:            $OutputRoot"
Write-Host "Stash:             $StashUrl"
Write-Host "Path map:          $pathMapDisplay"
Write-Host "Mode:              $(if ($SourceOnly) { 'SOURCE-ONLY / NO TRAINING AUTHORITY' } else { 'FULL P0' })"
Write-Host "Reconstruction:    FALSE"
Write-Host "Photoreal accept:  FALSE"
Write-Host "Production:        FALSE"
Write-Host "============================================================"

$priorPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })

    Write-Host ""
    Write-Host "=== 1/16 EXHAUSTIVE STASH INVENTORY ==="
    & (Join-Path $repoRoot "photoreal-stash-inventory.ps1") `
        -PerformerId $PerformerId `
        -OutputPath $InventoryPath `
        -StashUrl $StashUrl `
        -ApiKeyEnv $ApiKeyEnv `
        -BodyRigPython $Python

    if (-not $PathMapWasExplicit) {
        Invoke-PythonStage -Label "1B/16 PROVE EXACT SOURCE PATH MAP" -Arguments @(
            "-m", "bodyrig.photoreal_inventory_path_map_cli",
            "--inventory", $InventoryPath,
            "--out", $GeneratedSourcePathMap,
            "--stash-url", $StashUrl
        ) | Out-Null
        $PathMap = Need-File -Path $GeneratedSourcePathMap -Label "Generated exhaustive source path map"
    }

    Invoke-PythonStage -Label "2/16 LEAKAGE-SAFE DATASET PLAN" -Arguments @(
        "-m", "bodyrig.photoreal_dataset_plan_cli", $InventoryPath,
        "--out", $PlanPath,
        "--eval-fraction", ([string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:0.####}", $EvalFraction)),
        "--seed", $SplitSeed
    ) | Out-Null

    Invoke-PythonStage -Label "3/16 BYTE-VERIFY COMPLETE SOURCE UNIVERSE" -Arguments @(
        "-m", "bodyrig.photoreal_source_verify_cli", $InventoryPath,
        "--path-map", $PathMap,
        "--out", $ReceiptPath,
        "--stash-url", $StashUrl
    ) | Out-Null

    Invoke-PythonStage -Label "3B/16 SPATIAL METADATA PROBE (DIAGNOSTIC ONLY)" -Arguments @(
        "-m", "bodyrig.photoreal_spatial_metadata_probe_cli",
        "--inventory", $InventoryPath,
        "--receipt", $ReceiptPath,
        "--out", $SpatialMetadataProbePath
    ) | Out-Null

    Invoke-PythonStage -Label "4/16 DETERMINISTIC SCOUT PLAN" -Arguments @(
        "-m", "bodyrig.photoreal_scan_plan_cli",
        "--plan", $PlanPath,
        "--receipt", $ReceiptPath,
        "--out", $ScanPlanPath
    ) | Out-Null

    Invoke-PythonStage -Label "5/16 TRAIN-ONLY IDENTITY BOOTSTRAP" -Arguments @(
        "-m", "bodyrig.photoreal_identity_bootstrap_cli",
        "--scan-plan", $ScanPlanPath,
        "--out", $IdentityBootstrapPath
    ) | Out-Null

    if ($SourceOnly) {
        Write-Status -Status "source-ready-no-training-authority" -TeacherTrainingAuthorized $false -Blockers @(
            "SourceOnly mode explicitly disables identity calibration, frame authority and teacher-training authority."
        )
        Write-Host ""
        Write-Host "BodyRig Photoreal P0: SOURCE READY ONLY"
        Write-Host "Teacher training: BLOCKED"
        Write-Host "Status:           $StatusPath"
        exit 2
    }

    Invoke-PythonStage -Label "6/16 PIN ANALYZER MODEL SET" -Arguments @(
        "-m", "bodyrig.photoreal_model_set_cli",
        "--root", $ModelRoot,
        "--out", $ModelSetPath
    ) | Out-Null

    Invoke-PythonStage -Label "7/16 EXTRACT TRUSTED TARGET IDENTITY" -Arguments @(
        "-m", "bodyrig.photoreal_identity_extractor_cli",
        "--config", $IdentityExtractorConfig,
        "--bootstrap", $IdentityBootstrapPath,
        "--model-set", $ModelSetPath,
        "--workspace", $IdentityExtractWorkspace
    ) | Out-Null
    Need-File -Path $IdentityObservationsPath -Label "Identity observations" | Out-Null

    Invoke-PythonStage -Label "8/16 BUILD TRAIN-ONLY IDENTITY BANK" -Arguments @(
        "-m", "bodyrig.photoreal_identity_bank_cli",
        "--bootstrap", $IdentityBootstrapPath,
        "--model-set", $ModelSetPath,
        "--observations", $IdentityObservationsPath,
        "--out", $IdentityBankPath
    ) | Out-Null

    Invoke-PythonStage -Label "9/16 DISCOVER SOURCE-AUTHORITATIVE NEGATIVES" -Arguments @(
        "-m", "bodyrig.photoreal_identity_negative_inventory_cli",
        "--target-performer-id", $PerformerId,
        "--out", $NegativeInventoryPath,
        "--stash-url", $StashUrl,
        "--api-key-env", $ApiKeyEnv
    ) | Out-Null

    $CalibrationPathMap = $PathMap
    if (-not $PathMapWasExplicit) {
        Invoke-PythonStage -Label "9B/16 PROVE EXACT CALIBRATION PATH MAP" -Arguments @(
            "-m", "bodyrig.photoreal_inventory_path_map_cli",
            "--inventory", $InventoryPath,
            "--negative-inventory", $NegativeInventoryPath,
            "--out", $GeneratedCalibrationPathMap,
            "--stash-url", $StashUrl
        ) | Out-Null
        $CalibrationPathMap = Need-File -Path $GeneratedCalibrationPathMap -Label "Generated calibration path map"
    }

    Invoke-PythonStage -Label "10/16 BYTE-VERIFY NEGATIVE CALIBRATION SOURCES" -Arguments @(
        "-m", "bodyrig.photoreal_identity_negative_verify_cli",
        "--inventory", $NegativeInventoryPath,
        "--path-map", $CalibrationPathMap,
        "--out", $NegativeReceiptPath,
        "--stash-url", $StashUrl
    ) | Out-Null

    Invoke-PythonStage -Label "11/16 BUILD IDENTITY CALIBRATION PLAN" -Arguments @(
        "-m", "bodyrig.photoreal_identity_calibration_plan_cli",
        "--identity-bank", $IdentityBankPath,
        "--negative-receipt", $NegativeReceiptPath,
        "--out", $CalibrationPlanPath
    ) | Out-Null

    Invoke-PythonStage -Label "12/16 EXTRACT SAME-MODEL NEGATIVE IDENTITIES" -Arguments @(
        "-m", "bodyrig.photoreal_identity_calibration_extractor_cli",
        "--config", $IdentityExtractorConfig,
        "--plan", $CalibrationPlanPath,
        "--model-set", $ModelSetPath,
        "--workspace", $CalibrationExtractWorkspace
    ) | Out-Null
    Need-File -Path $NegativeObservationsPath -Label "Identity negative observations" | Out-Null

    $calibrationExit = Invoke-PythonStage -Label "13/16 DERIVE IDENTITY THRESHOLD" -AllowedExitCodes @(0, 2) -Arguments @(
        "-m", "bodyrig.photoreal_identity_calibration_cli",
        "--identity-bank", $IdentityBankPath,
        "--plan", $CalibrationPlanPath,
        "--negative-observations", $NegativeObservationsPath,
        "--out", $CalibrationPath
    )
    if ($calibrationExit -eq 2) {
        $calibration = Read-Json -Path $CalibrationPath -Label "Identity calibration"
        $calibrationBlockers = @($calibration.calibration_blockers | ForEach-Object { [string]$_ })
        Write-Host ""
        Write-Host "Identity calibration: BLOCKED FOR BIOMETRIC MATCHING"
        Write-Host "Source-bound identity: CONTINUING"
        if ($calibrationBlockers.Count -gt 0) {
            foreach ($blocker in $calibrationBlockers) {
                Write-Host ("  calibration blocker: {0}" -f $blocker)
            }
        }
        Write-Host "Reason: single-performer Stash sources are independently authorized by source binding."
        Write-Host "Ambiguous/multi-person frames remain unresolved without calibrated matching."
    }

    Invoke-PythonStage -Label "14/16 MEASURE ALL PLANNED FRAMES" -Arguments @(
        "-m", "bodyrig.photoreal_frame_analyzer_cli",
        "--config", $FrameAnalyzerConfig,
        "--scan-plan", $ScanPlanPath,
        "--workspace", $FrameAnalyzerWorkspace,
        "--out", $FrameMeasurementsPath
    ) | Out-Null

    Invoke-PythonStage -Label "15/16 APPLY CORE IDENTITY AUTHORITY" -Arguments @(
        "-m", "bodyrig.photoreal_frame_identity_authority_cli",
        "--plan", $PlanPath,
        "--measurements", $FrameMeasurementsPath,
        "--identity-bank", $IdentityBankPath,
        "--identity-calibration", $CalibrationPath,
        "--out", $AuthorizedObservationsPath
    ) | Out-Null

    $indexExit = Invoke-PythonStage -Label "16/16 LEAKAGE + HELD-OUT COVERAGE GATE" -AllowedExitCodes @(0, 2) -Arguments @(
        "-m", "bodyrig.photoreal_frame_index_cli",
        "--plan", $PlanPath,
        "--receipt", $ReceiptPath,
        "--authorized-observations", $AuthorizedObservationsPath,
        "--out", $FrameIndexPath
    )

    $frameIndex = Read-Json -Path $FrameIndexPath -Label "Photoreal frame index"
    $trainingAuthorized = ($indexExit -eq 0 -and (Test-StrictBoolean -Value $frameIndex.teacher_training_authorized -Expected $true))
    $blockers = @($frameIndex.training_blockers | ForEach-Object { [string]$_ })
    if (-not $trainingAuthorized -and $blockers.Count -eq 0) {
        $blockers = @("Frame index did not grant teacher-training authority.")
    }
    Write-Status `
        -Status $(if ($trainingAuthorized) { "teacher-training-authorized" } else { "frame-index-blocked" }) `
        -TeacherTrainingAuthorized $trainingAuthorized `
        -Blockers $blockers

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - P0 COMPLETE"
    Write-Host "Revision:          $Head"
    Write-Host "Teacher training:  $(if ($trainingAuthorized) { 'AUTHORIZED' } else { 'BLOCKED' })"
    Write-Host "Human visual gate: REQUIRED LATER"
    Write-Host "Photoreal accept:  FALSE"
    Write-Host "Production:        FALSE"
    Write-Host "Status:            $StatusPath"
    Write-Host "============================================================"
    exit $(if ($trainingAuthorized) { 0 } else { 2 })
} finally {
    $env:PYTHONPATH = $priorPythonPath
}
