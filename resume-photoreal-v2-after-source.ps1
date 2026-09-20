param(
    [Parameter(Mandatory = $true)][string]$SourceRun,
    [Parameter(Mandatory = $true)][string]$ProjectionAuthority,
    [string]$PerformerId = "42",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$RunRoot = "",
    [string]$ModelRoot = "",
    [string]$BodyRigPython = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$VisionDevice = "cuda:0"
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

function Test-NumericV1 {
    param([AllowNull()]$Value)
    if ($null -eq $Value -or $Value -is [bool]) { return $false }
    try { $typeCode = [Type]::GetTypeCode($Value.GetType()) } catch { return $false }
    $numericTypes = @([TypeCode]::Byte,[TypeCode]::Decimal,[TypeCode]::Double,[TypeCode]::Int16,[TypeCode]::Int32,[TypeCode]::Int64,[TypeCode]::SByte,[TypeCode]::Single,[TypeCode]::UInt16,[TypeCode]::UInt32,[TypeCode]::UInt64)
    if ($numericTypes -notcontains $typeCode) { return $false }
    $number = [double]$Value
    return (-not [double]::IsNaN($number)) -and (-not [double]::IsInfinity($number)) -and $number -eq 1.0
}

function Test-StrictBoolean {
    param([AllowNull()]$Value,[Parameter(Mandatory = $true)][bool]$Expected)
    return ($Value -is [bool]) -and ([bool]$Value -eq $Expected)
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

function Restore-SavedStashCredential {
    param(
        [Parameter(Mandatory = $true)][string]$EnvironmentName,
        [string]$RequestedUrl = ""
    )
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($EnvironmentName, "Process"))) {
        return $null
    }
    if ($EnvironmentName -ne "STASH_API_KEY") { return $null }
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { return $null }

    $configPath = Join-Path $env:LOCALAPPDATA "BodyRig\config\stash.json"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { return $null }
    $config = Read-Json -Path $configPath -Label "Saved Stash config"
    if ([string]$config.format -ne "bodyrig-local-stash-config" -or -not (Test-NumericV1 -Value $config.version)) {
        throw "Saved Stash config has an unexpected format/version: $configPath"
    }
    $savedUrl = ([string]$config.url).Trim()
    if ([string]::IsNullOrWhiteSpace($savedUrl) -or [string]::IsNullOrWhiteSpace([string]$config.api_key_dpapi)) {
        throw "Saved Stash config lacks URL or protected API key: $configPath"
    }
    if (-not [string]::IsNullOrWhiteSpace($RequestedUrl) -and -not [string]::Equals($RequestedUrl.Trim(), $savedUrl, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Saved Stash config URL '$savedUrl' does not match requested Stash URL '$RequestedUrl'."
    }

    $secure = ConvertTo-SecureString ([string]$config.api_key_dpapi)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        if ([string]::IsNullOrWhiteSpace($apiKey)) {
            throw "Saved Stash API key could not be decrypted for this Windows user."
        }
        [Environment]::SetEnvironmentVariable($EnvironmentName, $apiKey, "Process")
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    return $savedUrl
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
        resumed_from_verified_source_run = $script:SourceRun
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
            source_resume_receipt = $script:ResumeReceiptPath
        }
    }
    $payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $script:StatusPath -Encoding UTF8
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$Head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($Head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Photoreal resume requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }
if ([string]::IsNullOrWhiteSpace($PerformerId)) { throw "PerformerId is required." }
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) { throw "LinuxPython must be an absolute Linux path." }
if ($VisionDevice -notin @("cpu", "cuda", "cuda:0")) { throw "VisionDevice must be cpu, cuda or cuda:0." }

$SourceRun = Need-Directory -Path $SourceRun -Label "Verified source run"
$ProjectionAuthority = Need-File -Path $ProjectionAuthority -Label "Projection authority"

$sourceInventory = Need-File -Path (Join-Path $SourceRun "source-inventory.json") -Label "Verified source inventory"
$sourcePathMap = Need-File -Path (Join-Path $SourceRun "source-path-map.json") -Label "Verified source path map"
$sourcePlan = Need-File -Path (Join-Path $SourceRun "dataset-plan.json") -Label "Verified dataset plan"
$sourceReceipt = Need-File -Path (Join-Path $SourceRun "source-receipt.json") -Label "Verified source receipt"
$sourceSpatialProbe = Need-File -Path (Join-Path $SourceRun "spatial-metadata-probe.json") -Label "Verified spatial metadata probe"

$plan = Read-Json -Path $sourcePlan -Label "Verified dataset plan"
if ([string]$plan.format -ne "bodyrig-photoreal-dataset-plan" -or -not (Test-NumericV1 -Value $plan.version)) {
    throw "Verified dataset plan format/version mismatch."
}
if ([string]$plan.performer_id -ne $PerformerId) { throw "Verified dataset plan performer mismatch." }
if (-not (Test-StrictBoolean -Value $plan.build_only -Expected $true) -or -not (Test-StrictBoolean -Value $plan.runtime_dependency -Expected $false) -or -not (Test-StrictBoolean -Value $plan.production_activation -Expected $false)) {
    throw "Verified dataset plan authority boundary is invalid."
}

$receipt = Read-Json -Path $sourceReceipt -Label "Verified source receipt"
if ([string]$receipt.format -ne "bodyrig-photoreal-source-receipt" -or -not (Test-NumericV1 -Value $receipt.version)) {
    throw "Verified source receipt format/version mismatch."
}
if ([string]$receipt.performer_id -ne $PerformerId) { throw "Verified source receipt performer mismatch." }
if (-not (Test-StrictBoolean -Value $receipt.all_sources_readable -Expected $true) -or -not (Test-StrictBoolean -Value $receipt.all_sources_sha256_bound -Expected $true) -or -not (Test-StrictBoolean -Value $receipt.source_keys_path_specific -Expected $true)) {
    throw "Verified source receipt is incomplete."
}
if (-not (Test-StrictBoolean -Value $receipt.build_only -Expected $true) -or -not (Test-StrictBoolean -Value $receipt.runtime_dependency -Expected $false) -or -not (Test-StrictBoolean -Value $receipt.production_activation -Expected $false)) {
    throw "Verified source receipt authority boundary is invalid."
}

$pathMap = Read-Json -Path $sourcePathMap -Label "Verified source path map"
if ([string]$pathMap.format -ne "bodyrig-local-stash-path-map" -or [string]$pathMap.status -ne "PASS" -or [string]$pathMap.performer_id -ne $PerformerId -or -not (Test-StrictBoolean -Value $pathMap.production_activation -Expected $false)) {
    throw "Verified source path map is invalid."
}

$spatialProbe = Read-Json -Path $sourceSpatialProbe -Label "Verified spatial metadata probe"
if ([string]$spatialProbe.format -ne "bodyrig-photoreal-spatial-container-probe" -or [string]$spatialProbe.status -ne "PASS" -or [string]$spatialProbe.performer_id -ne $PerformerId -or -not (Test-StrictBoolean -Value $spatialProbe.diagnostic_only -Expected $true) -or -not (Test-StrictBoolean -Value $spatialProbe.production_activation -Expected $false)) {
    throw "Verified spatial metadata probe is invalid."
}

$authority = Read-Json -Path $ProjectionAuthority -Label "Projection authority"
if ([string]$authority.format -ne "bodyrig-photoreal-explicit-projection-authority" -or -not (Test-NumericV1 -Value $authority.version)) {
    throw "Projection authority format/version mismatch."
}
if ([string]$authority.performer_id -ne $PerformerId) { throw "Projection authority performer mismatch." }
if (-not (Test-StrictBoolean -Value $authority.build_only -Expected $true) -or -not (Test-StrictBoolean -Value $authority.runtime_dependency -Expected $false) -or -not (Test-StrictBoolean -Value $authority.production_activation -Expected $false)) {
    throw "Projection authority boundary is invalid."
}
if (@($authority.sources).Count -eq 0) { throw "Projection authority contains no sources." }

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

if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models"
}
$ModelRoot = Need-Directory -Path $ModelRoot -Label "Photoreal reference model root"
$adapter = Need-File -Path (Join-Path $repoRoot "tools\photoreal_reference_vision_adapter_mesh.py") -Label "Photoreal reference vision mesh adapter"
$probe = Need-File -Path (Join-Path $repoRoot "tools\photoreal_reference_vision_probe.py") -Label "Photoreal reference vision probe"

if ([string]::IsNullOrWhiteSpace($RunRoot)) {
    $RunRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\overnight"
}
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
[IO.Directory]::CreateDirectory($RunRoot) | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputRoot = Join-Path $RunRoot ("performer-{0}-{1}-resume4" -f $PerformerId, $stamp)
if (Test-Path -LiteralPath $OutputRoot) { throw "Resume output root already exists: $OutputRoot" }
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$InventoryPath = Join-Path $OutputRoot "source-inventory.json"
$GeneratedSourcePathMap = Join-Path $OutputRoot "source-path-map.json"
$GeneratedCalibrationPathMap = Join-Path $OutputRoot "calibration-path-map.json"
$PlanPath = Join-Path $OutputRoot "dataset-plan.json"
$ReceiptPath = Join-Path $OutputRoot "source-receipt.json"
$SpatialMetadataProbePath = Join-Path $OutputRoot "spatial-metadata-probe.json"
$ResumeReceiptPath = Join-Path $OutputRoot "source-resume-receipt.json"
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

Copy-Item -LiteralPath $sourceInventory -Destination $InventoryPath
Copy-Item -LiteralPath $sourcePathMap -Destination $GeneratedSourcePathMap
Copy-Item -LiteralPath $sourcePlan -Destination $PlanPath
Copy-Item -LiteralPath $sourceReceipt -Destination $ReceiptPath
Copy-Item -LiteralPath $sourceSpatialProbe -Destination $SpatialMetadataProbePath
$PathMap = $GeneratedSourcePathMap

$artifactHashes = [ordered]@{}
foreach ($path in @($InventoryPath,$GeneratedSourcePathMap,$PlanPath,$ReceiptPath,$SpatialMetadataProbePath)) {
    $artifactHashes[[IO.Path]::GetFileName($path)] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
$resumeReceipt = [ordered]@{
    format = "bodyrig-photoreal-source-resume-receipt"
    version = 1
    bodyrig_revision = $Head
    performer_id = $PerformerId
    source_run = $SourceRun
    projection_authority = $ProjectionAuthority
    projection_authority_sha256 = (Get-FileHash -LiteralPath $ProjectionAuthority -Algorithm SHA256).Hash.ToLowerInvariant()
    copied_source_artifacts_sha256 = $artifactHashes
    resume_stage = 4
    source_rehash_skipped_explicitly = $true
    teacher_training_authorized = $false
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$resumeReceipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ResumeReceiptPath -Encoding UTF8

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-photoreal-resume-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$identityConfig = Join-Path $tempRoot "identity-extractor.json"
$frameConfig = Join-Path $tempRoot "frame-analyzer.json"

$originalProjectionAuthority = [Environment]::GetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", "Process")
$originalApiKey = [Environment]::GetEnvironmentVariable($ApiKeyEnv, "Process")
$restoredSavedCredential = $false
$priorPythonPath = $env:PYTHONPATH
$finalExitCode = 1
try {
    $savedStashUrl = Restore-SavedStashCredential -EnvironmentName $ApiKeyEnv -RequestedUrl $StashUrl
    if (-not [string]::IsNullOrWhiteSpace([string]$savedStashUrl)) {
        $restoredSavedCredential = $true
        if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$savedStashUrl }
    }
    if ([string]::IsNullOrWhiteSpace($StashUrl)) {
        $stashConfig = Read-Json -Path (Join-Path $env:LOCALAPPDATA "BodyRig\config\stash.json") -Label "Saved Stash config"
        $StashUrl = ([string]$stashConfig.url).Trim()
    }
    if ([string]::IsNullOrWhiteSpace($StashUrl)) { throw "StashUrl is required." }
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($ApiKeyEnv, "Process"))) {
        throw "Stash API key environment variable '$ApiKeyEnv' is missing."
    }

    [Environment]::SetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", $ProjectionAuthority, "Process")
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })

    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - RESUME AFTER VERIFIED SOURCE"
    Write-Host "Revision:          $Head"
    Write-Host "Performer:         $PerformerId"
    Write-Host "Source run:        $SourceRun"
    Write-Host "Output:            $OutputRoot"
    Write-Host "Projection auth:   $ProjectionAuthority"
    Write-Host "Resume stage:      4/16"
    Write-Host "Source rehash:     SKIPPED EXPLICITLY"
    Write-Host "Photoreal accept:  FALSE"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"

    Write-Host ""
    Write-Host "=== RESUME PREFLIGHT: PINNED VISION STACK ==="
    $preflightOutput = @(& $Python -m bodyrig.photoreal_reference_vision_preflight `
        --adapter-path $adapter `
        --probe-path $probe `
        --model-root $ModelRoot `
        --distribution $Distribution `
        --linux-python $LinuxPython `
        --device $VisionDevice 2>&1)
    $preflightExit = $LASTEXITCODE
    foreach ($line in $preflightOutput) { Write-Host ([string]$line) }
    if ($preflightExit -ne 0) { throw "Photoreal reference vision preflight failed with exit code $preflightExit." }

    Write-Host ""
    Write-Host "=== RESUME PREFLIGHT: GENERATE EXACT MEASUREMENT CONFIGS ==="
    $configOutput = @(& $Python -m bodyrig.photoreal_reference_vision_config `
        --model-root $ModelRoot `
        --adapter-path $adapter `
        --windows-python $Python `
        --distribution $Distribution `
        --linux-python $LinuxPython `
        --device $VisionDevice `
        --identity-out $identityConfig `
        --frame-out $frameConfig 2>&1)
    $configExit = $LASTEXITCODE
    foreach ($line in $configOutput) { Write-Host ([string]$line) }
    if ($configExit -ne 0) { throw "Photoreal reference vision config generation failed with exit code $configExit." }
    Need-File -Path $identityConfig -Label "Generated identity extractor config" | Out-Null
    Need-File -Path $frameConfig -Label "Generated frame analyzer config" | Out-Null

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

    Invoke-PythonStage -Label "6/16 PIN ANALYZER MODEL SET" -Arguments @(
        "-m", "bodyrig.photoreal_model_set_cli",
        "--root", $ModelRoot,
        "--out", $ModelSetPath
    ) | Out-Null

    Invoke-PythonStage -Label "7/16 EXTRACT TRUSTED TARGET IDENTITY" -Arguments @(
        "-m", "bodyrig.photoreal_identity_extractor_cli",
        "--config", $identityConfig,
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

    Invoke-PythonStage -Label "9B/16 PROVE EXACT CALIBRATION PATH MAP" -Arguments @(
        "-m", "bodyrig.photoreal_inventory_path_map_cli",
        "--inventory", $InventoryPath,
        "--negative-inventory", $NegativeInventoryPath,
        "--out", $GeneratedCalibrationPathMap,
        "--stash-url", $StashUrl
    ) | Out-Null
    $CalibrationPathMap = Need-File -Path $GeneratedCalibrationPathMap -Label "Generated calibration path map"

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
        "--config", $identityConfig,
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
        Write-Host "Identity calibration is unavailable for ambiguous/multi-person sources."
        Write-Host "Continuing because source-authoritative single-performer bindings are resolved independently."
        foreach ($blocker in $calibrationBlockers) {
            Write-Host "Calibration advisory: $blocker"
        }
        Write-Host "Ambiguous sources without calibrated matching will remain unresolved and cannot become teacher-eligible."
    }

    Invoke-PythonStage -Label "14/16 MEASURE ALL PLANNED FRAMES" -Arguments @(
        "-m", "bodyrig.photoreal_frame_analyzer_cli",
        "--config", $frameConfig,
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
    Write-Host "BODYRIG PHOTOREAL V2 - RESUMED P0 COMPLETE"
    Write-Host "Revision:          $Head"
    Write-Host "Output:            $OutputRoot"
    Write-Host "Teacher training:  $(if ($trainingAuthorized) { 'AUTHORIZED' } else { 'BLOCKED' })"
    Write-Host "Human visual gate: REQUIRED LATER"
    Write-Host "Photoreal accept:  FALSE"
    Write-Host "Production:        FALSE"
    Write-Host "Status:            $StatusPath"
    Write-Host "============================================================"
    $finalExitCode = $(if ($trainingAuthorized) { 0 } else { 2 })
}
catch {
    $message = $_.Exception.Message
    if (-not (Test-Path -LiteralPath $StatusPath -PathType Leaf)) {
        Write-Status -Status "resume-unexpected-failure" -TeacherTrainingAuthorized $false -Blockers @(
            "Resumed P0 failed unexpectedly: $message"
        )
    }
    Write-Host ""
    Write-Host "BodyRig Photoreal resumed P0: FAILED"
    Write-Host "Error:  $message"
    Write-Host "Output: $OutputRoot"
    Write-Host "Status: $StatusPath"
    $finalExitCode = 1
}
finally {
    $env:PYTHONPATH = $priorPythonPath
    [Environment]::SetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", $originalProjectionAuthority, "Process")
    if ($restoredSavedCredential) {
        [Environment]::SetEnvironmentVariable($ApiKeyEnv, $originalApiKey, "Process")
    }
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit $finalExitCode
