param(
    [Parameter(Mandatory = $true)][string]$SourceRun,
    [Parameter(Mandatory = $true)][string]$ProjectionAuthority,
    [string]$PerformerId = "42",
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

function Copy-Stage13Artifact {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $source = Need-File -Path (Join-Path $script:SourceRun $RelativePath) -Label $Label
    $destination = Join-Path $script:OutputRoot $RelativePath
    $parent = Split-Path -Parent $destination
    if (-not [string]::IsNullOrWhiteSpace($parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Copy-Item -LiteralPath $source -Destination $destination
    if ((Sha256 $source) -ne (Sha256 $destination)) { throw "Copied Stage-13 artifact changed bytes: $RelativePath" }
    $script:CopiedArtifactHashes[$RelativePath] = Sha256 $destination
    return $destination
}

function Write-Status {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][bool]$TeacherTrainingAuthorized,
        [Parameter(Mandatory = $true)][string[]]$Blockers,
        [int]$SourceBoundVerified = 0,
        [int]$CalibratedVerified = 0,
        [int]$Unresolved = 0
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
        resumed_from_stage13_run = $script:SourceRun
        source_rehash_skipped_explicitly = $true
        identity_bank_rebuild = $false
        identity_calibration_rebuild = $false
        source_bound_verified_observation_count = $SourceBoundVerified
        calibrated_verified_observation_count = $CalibratedVerified
        unresolved_observation_count = $Unresolved
        outputs = [ordered]@{
            dataset_plan = $script:PlanPath
            source_receipt = $script:ReceiptPath
            scan_plan = $script:ScanPlanPath
            model_set = $script:ModelSetPath
            identity_bank = $script:IdentityBankPath
            identity_calibration = $script:CalibrationPath
            frame_measurements = $script:FrameMeasurementsPath
            frame_authorized_observations = $script:AuthorizedObservationsPath
            frame_index = $script:FrameIndexPath
            stage14_resume_receipt = $script:ResumeReceiptPath
        }
    }
    $payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $script:StatusPath -Encoding UTF8
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "Photoreal Stage-14 resume is Windows/WSL-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") { throw "Photoreal Stage-14 resume must run from canonical main." }
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$Head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($Head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Photoreal Stage-14 resume requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }
if ([string]::IsNullOrWhiteSpace($PerformerId)) { throw "PerformerId is required." }
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) { throw "LinuxPython must be an absolute Linux path." }
if ($VisionDevice -notin @("cpu", "cuda", "cuda:0")) { throw "VisionDevice must be cpu, cuda or cuda:0." }

$SourceRun = Need-Directory -Path $SourceRun -Label "Stage-13 source run"
$ProjectionAuthority = Need-File -Path $ProjectionAuthority -Label "Projection authority"

$sourcePlan = Need-File -Path (Join-Path $SourceRun "dataset-plan.json") -Label "Stage-13 dataset plan"
$sourceReceipt = Need-File -Path (Join-Path $SourceRun "source-receipt.json") -Label "Stage-13 source receipt"
$sourceScanPlan = Need-File -Path (Join-Path $SourceRun "scan-plan.json") -Label "Stage-13 scan plan"
$sourceModelSet = Need-File -Path (Join-Path $SourceRun "model-set.json") -Label "Stage-13 model set"
$sourceIdentityBank = Need-File -Path (Join-Path $SourceRun "identity-bank.json") -Label "Stage-13 identity bank"
$sourceCalibration = Need-File -Path (Join-Path $SourceRun "identity-calibration.json") -Label "Stage-13 identity calibration"

$plan = Read-Json -Path $sourcePlan -Label "Stage-13 dataset plan"
if ([string]$plan.format -ne "bodyrig-photoreal-dataset-plan" -or -not (Test-NumericV1 -Value $plan.version)) { throw "Stage-13 dataset plan format/version mismatch." }
if ([string]$plan.performer_id -ne $PerformerId) { throw "Stage-13 dataset plan performer mismatch." }
if (-not (Test-StrictBoolean -Value $plan.build_only -Expected $true) -or -not (Test-StrictBoolean -Value $plan.runtime_dependency -Expected $false) -or -not (Test-StrictBoolean -Value $plan.production_activation -Expected $false)) { throw "Stage-13 dataset plan authority boundary is invalid." }

$receipt = Read-Json -Path $sourceReceipt -Label "Stage-13 source receipt"
if ([string]$receipt.format -ne "bodyrig-photoreal-source-receipt" -or -not (Test-NumericV1 -Value $receipt.version)) { throw "Stage-13 source receipt format/version mismatch." }
if ([string]$receipt.performer_id -ne $PerformerId) { throw "Stage-13 source receipt performer mismatch." }
if (-not (Test-StrictBoolean -Value $receipt.all_sources_readable -Expected $true) -or -not (Test-StrictBoolean -Value $receipt.all_sources_sha256_bound -Expected $true) -or -not (Test-StrictBoolean -Value $receipt.source_keys_path_specific -Expected $true) -or -not (Test-StrictBoolean -Value $receipt.production_activation -Expected $false)) { throw "Stage-13 source receipt is incomplete or crossed authority." }

$calibration = Read-Json -Path $sourceCalibration -Label "Stage-13 identity calibration"
if ([string]$calibration.format -ne "bodyrig-photoreal-identity-calibration" -or -not (Test-NumericV1 -Value $calibration.version)) { throw "Stage-13 identity calibration format/version mismatch." }
if ([string]$calibration.target_performer_id -ne $PerformerId) { throw "Stage-13 identity calibration performer mismatch." }
if (-not (Test-StrictBoolean -Value $calibration.teacher_training_authorized -Expected $false) -or -not (Test-StrictBoolean -Value $calibration.photoreal_acceptance_authority -Expected $false) -or -not (Test-StrictBoolean -Value $calibration.production_activation -Expected $false)) { throw "Stage-13 identity calibration crossed downstream authority." }

$authority = Read-Json -Path $ProjectionAuthority -Label "Projection authority"
if ([string]$authority.format -ne "bodyrig-photoreal-explicit-projection-authority" -or -not (Test-NumericV1 -Value $authority.version)) { throw "Projection authority format/version mismatch." }
if ([string]$authority.performer_id -ne $PerformerId) { throw "Projection authority performer mismatch." }
if (-not (Test-StrictBoolean -Value $authority.build_only -Expected $true) -or -not (Test-StrictBoolean -Value $authority.runtime_dependency -Expected $false) -or -not (Test-StrictBoolean -Value $authority.production_activation -Expected $false) -or @($authority.sources).Count -eq 0) { throw "Projection authority boundary is invalid." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython -PathType Leaf) { $Python = (Resolve-Path -LiteralPath $localPython).Path }
    else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python was not found." }
        $Python = $command.Source
    }
} else { $Python = Need-File -Path $BodyRigPython -Label "BodyRig Python" }

if ([string]::IsNullOrWhiteSpace($ModelRoot)) { $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models" }
$ModelRoot = Need-Directory -Path $ModelRoot -Label "Photoreal reference model root"
$adapter = Need-File -Path (Join-Path $repoRoot "tools\photoreal_reference_vision_adapter_mesh.py") -Label "Photoreal reference vision adapter"
$probe = Need-File -Path (Join-Path $repoRoot "tools\photoreal_reference_vision_probe.py") -Label "Photoreal reference vision probe"

if ([string]::IsNullOrWhiteSpace($RunRoot)) { $RunRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\overnight" }
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputRoot = Join-Path $RunRoot ("performer-{0}-{1}-resume14" -f $PerformerId, $stamp)
if (Test-Path -LiteralPath $OutputRoot) { throw "Stage-14 resume output already exists: $OutputRoot" }
New-Item -ItemType Directory -Path $OutputRoot | Out-Null

$CopiedArtifactHashes = [ordered]@{}
$PlanPath = Copy-Stage13Artifact -RelativePath "dataset-plan.json" -Label "Stage-13 dataset plan"
$ReceiptPath = Copy-Stage13Artifact -RelativePath "source-receipt.json" -Label "Stage-13 source receipt"
$ScanPlanPath = Copy-Stage13Artifact -RelativePath "scan-plan.json" -Label "Stage-13 scan plan"
$ModelSetPath = Copy-Stage13Artifact -RelativePath "model-set.json" -Label "Stage-13 model set"
$IdentityBankPath = Copy-Stage13Artifact -RelativePath "identity-bank.json" -Label "Stage-13 identity bank"
$CalibrationPath = Copy-Stage13Artifact -RelativePath "identity-calibration.json" -Label "Stage-13 identity calibration"

$ResumeReceiptPath = Join-Path $OutputRoot "stage14-resume-receipt.json"
$FrameAnalyzerWorkspace = Join-Path $OutputRoot "frame-analyzer"
$FrameMeasurementsPath = Join-Path $OutputRoot "frame-measurements.json"
$AuthorizedObservationsPath = Join-Path $OutputRoot "frame-authorized-observations.json"
$FrameIndexPath = Join-Path $OutputRoot "frame-index.json"
$StatusPath = Join-Path $OutputRoot "p0-status.json"

$resumeReceipt = [ordered]@{
    format = "bodyrig-photoreal-stage14-resume-receipt"
    version = 1
    bodyrig_revision = $Head
    performer_id = $PerformerId
    source_run = $SourceRun
    source_run_artifacts_sha256 = $CopiedArtifactHashes
    projection_authority = $ProjectionAuthority
    projection_authority_sha256 = Sha256 $ProjectionAuthority
    resume_stage = 14
    source_rehash_skipped_explicitly = $true
    identity_bank_rebuild = $false
    identity_calibration_rebuild = $false
    biometric_matching_authorized = ($calibration.identity_matching_authorized -eq $true)
    source_bound_identity_continues_independently = $true
    teacher_training_authorized = $false
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$resumeReceipt | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ResumeReceiptPath -Encoding UTF8

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-photoreal-resume14-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$identityConfig = Join-Path $tempRoot "identity-extractor-unused.json"
$frameConfig = Join-Path $tempRoot "frame-analyzer.json"
$priorPythonPath = $env:PYTHONPATH
$priorProjectionAuthority = [Environment]::GetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", "Process")
$finalExitCode = 1

try {
    [Environment]::SetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", $ProjectionAuthority, "Process")
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })

    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - RESUME FROM STAGE 14"
    Write-Host "Revision:          $Head"
    Write-Host "Performer:         $PerformerId"
    Write-Host "Source run:        $SourceRun"
    Write-Host "Output:            $OutputRoot"
    Write-Host "Source rehash:     NO"
    Write-Host "Identity rebuild:  NO"
    Write-Host "Calibration build: NO"
    Write-Host "Biometric match:   $(if ($calibration.identity_matching_authorized -eq $true) { 'AUTHORIZED' } else { 'BLOCKED / NOT REQUIRED FOR SOURCE-BOUND MEDIA' })"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"

    Write-Host ""
    Write-Host "=== PREFLIGHT: PINNED VISION STACK ==="
    $preflightArgs = @("-m","bodyrig.photoreal_reference_vision_preflight","--adapter-path",$adapter,"--probe-path",$probe,"--model-root",$ModelRoot,"--distribution",$Distribution,"--linux-python",$LinuxPython,"--device",$VisionDevice)
    $preflight = @(& $Python @preflightArgs 2>&1)
    $preflightExit = $LASTEXITCODE
    foreach ($line in $preflight) { Write-Host ([string]$line) }
    if ($preflightExit -ne 0) { throw "Photoreal reference vision preflight failed with exit code $preflightExit." }

    Write-Host ""
    Write-Host "=== PREFLIGHT: GENERATE FRAME ANALYZER CONFIG ==="
    $configArgs = @("-m","bodyrig.photoreal_reference_vision_config","--model-root",$ModelRoot,"--adapter-path",$adapter,"--windows-python",$Python,"--distribution",$Distribution,"--linux-python",$LinuxPython,"--device",$VisionDevice,"--identity-out",$identityConfig,"--frame-out",$frameConfig)
    $config = @(& $Python @configArgs 2>&1)
    $configExit = $LASTEXITCODE
    foreach ($line in $config) { Write-Host ([string]$line) }
    if ($configExit -ne 0) { throw "Photoreal frame analyzer config generation failed with exit code $configExit." }
    Need-File -Path $frameConfig -Label "Generated frame analyzer config" | Out-Null

    Invoke-PythonStage -Label "14/16 MEASURE ALL PLANNED FRAMES" -Arguments @("-m","bodyrig.photoreal_frame_analyzer_cli","--config",$frameConfig,"--scan-plan",$ScanPlanPath,"--workspace",$FrameAnalyzerWorkspace,"--out",$FrameMeasurementsPath) | Out-Null

    Invoke-PythonStage -Label "15/16 APPLY CORE SOURCE/IDENTITY AUTHORITY" -Arguments @("-m","bodyrig.photoreal_frame_identity_authority_cli","--plan",$PlanPath,"--measurements",$FrameMeasurementsPath,"--identity-bank",$IdentityBankPath,"--identity-calibration",$CalibrationPath,"--out",$AuthorizedObservationsPath) | Out-Null

    $indexExit = Invoke-PythonStage -Label "16/16 LEAKAGE + HELD-OUT COVERAGE GATE" -AllowedExitCodes @(0,2) -Arguments @("-m","bodyrig.photoreal_frame_index_cli","--plan",$PlanPath,"--receipt",$ReceiptPath,"--authorized-observations",$AuthorizedObservationsPath,"--out",$FrameIndexPath)

    $authorized = Read-Json -Path $AuthorizedObservationsPath -Label "Authorized frame observations"
    $rows = @($authorized.observations)
    $sourceBoundVerified = @($rows | Where-Object { $_.target_identity_verified -eq $true -and $_.identity_authority -eq "stash-single-performer-target-binding-v1" }).Count
    $calibratedVerified = @($rows | Where-Object { $_.target_identity_verified -eq $true -and $_.identity_authority -eq "calibrated-identity-bank-v1" }).Count
    $unresolved = @($rows | Where-Object { $_.target_identity_verified -ne $true }).Count

    $frameIndex = Read-Json -Path $FrameIndexPath -Label "Photoreal frame index"
    $trainingAuthorized = ($indexExit -eq 0 -and (Test-StrictBoolean -Value $frameIndex.teacher_training_authorized -Expected $true))
    $blockers = @($frameIndex.training_blockers | ForEach-Object { [string]$_ })
    if (-not $trainingAuthorized -and $blockers.Count -eq 0) { $blockers = @("Frame index did not grant teacher-training authority.") }

    Write-Status -Status $(if ($trainingAuthorized) { "teacher-training-authorized" } else { "frame-index-blocked" }) -TeacherTrainingAuthorized $trainingAuthorized -Blockers $blockers -SourceBoundVerified $sourceBoundVerified -CalibratedVerified $calibratedVerified -Unresolved $unresolved

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - STAGE 14 RESUME COMPLETE"
    Write-Host "Source-bound verified: $sourceBoundVerified"
    Write-Host "Calibrated verified:   $calibratedVerified"
    Write-Host "Unresolved:            $unresolved"
    Write-Host "Teacher training:      $(if ($trainingAuthorized) { 'AUTHORIZED' } else { 'BLOCKED' })"
    if ($blockers.Count -gt 0) { foreach ($blocker in $blockers) { Write-Host ("  blocker: {0}" -f $blocker) } }
    Write-Host "Photoreal accept:      FALSE"
    Write-Host "Production:            FALSE"
    Write-Host "Status:                $StatusPath"
    Write-Host "============================================================"
    $finalExitCode = $(if ($trainingAuthorized) { 0 } else { 2 })
}
catch {
    $message = $_.Exception.Message
    if (-not (Test-Path -LiteralPath $StatusPath -PathType Leaf)) { Write-Status -Status "stage14-resume-unexpected-failure" -TeacherTrainingAuthorized $false -Blockers @("Stage-14 resume failed unexpectedly: $message") }
    Write-Host ""
    Write-Host "BodyRig Photoreal Stage-14 resume: FAILED"
    Write-Host "Error:  $message"
    Write-Host "Output: $OutputRoot"
    Write-Host "Status: $StatusPath"
    $finalExitCode = 1
}
finally {
    $env:PYTHONPATH = $priorPythonPath
    [Environment]::SetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", $priorProjectionAuthority, "Process")
    if (Test-Path -LiteralPath $tempRoot -PathType Container) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}

exit $finalExitCode
