param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
    [string]$ModelRoot = "",
    [string]$CvlFaceRoot = "",
    [switch]$AcceptTrainingDatasetTerms,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [ValidateSet("cpu", "cuda", "cuda:0")][string]$Device = "cuda:0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Convert-ToWslPath {
    param([string]$WindowsPath)
    if ($WindowsPath.StartsWith('/')) { return $WindowsPath }

    $pythonCode = @'
import base64
import sys
sys.path.insert(0, sys.argv[1])
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
value = make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4])
print(base64.b64encode(value.encode("utf-8")).decode("ascii"))
'@
    $lines = @(& $script:WindowsPython -c $pythonCode $script:RepoRoot "wsl.exe" $Distribution $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
        throw "Could not convert path with BodyRig WSL bridge: $WindowsPath | $($lines -join ' ')"
    }
    $encoded = ([string]$lines[0]).Trim()
    try {
        $value = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
    } catch {
        throw "BodyRig WSL bridge returned invalid encoded path data: $WindowsPath"
    }
    if ([string]::IsNullOrWhiteSpace($value) -or -not $value.StartsWith('/')) {
        throw "BodyRig WSL bridge returned invalid path: $WindowsPath"
    }
    return $value
}

function New-WslTransportRequest {
    param(
        [string]$SourceRequest,
        [string]$Prefix
    )
    $requestObject = Get-Content -LiteralPath $SourceRequest -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    if ($null -eq $requestObject.sources -or @($requestObject.sources).Count -eq 0) {
        throw "$Prefix request contains no sources."
    }
    foreach ($source in @($requestObject.sources)) {
        $raw = ([string]$source.resolved_path).Trim()
        if ([string]::IsNullOrWhiteSpace($raw)) {
            throw "$Prefix source has no resolved_path."
        }
        $source.resolved_path = Convert-ToWslPath -WindowsPath $raw
    }
    $temp = Join-Path ([IO.Path]::GetTempPath()) (
        "bodyrig-{0}-{1}.json" -f $Prefix.ToLowerInvariant().Replace(" ", "-"), [Guid]::NewGuid().ToString("N")
    )
    $requestObject | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temp -Encoding UTF8
    return $temp
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required on Windows."
}
if ([string]::IsNullOrWhiteSpace($Distribution)) {
    throw "WSL distribution is required."
}
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) {
    throw "LinuxPython must be an absolute Linux path."
}

$script:RepoRoot = (Resolve-Path $PSScriptRoot).Path
$script:WindowsPython = Need-File (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") "BodyRig Windows Python"

$dirty = @(git -C $script:RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect BodyRig Git status."
}
if ($dirty.Count -ne 0) {
    throw "CVLFace AdaFace ViT diagnostic requires a clean BodyRig checkout."
}
$head = ([string](git -C $script:RepoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git HEAD."
}

$RunDirectory = Need-Directory $RunDirectory "Photoreal resumed run"
$ReviewRoot = Need-Directory $ReviewRoot "Identity group review root"
$bank = Need-File (Join-Path $RunDirectory "identity-bank.json") "Identity bank"
$identityRequest = Need-File (Join-Path $RunDirectory "identity-extractor\request.json") "Stage-7 identity request"
$calibrationRequest = Need-File (Join-Path $RunDirectory "identity-calibration-extractor\request.json") "Stage-13 calibration request"
$negativeObservations = Need-File (Join-Path $RunDirectory "identity-calibration-extractor\output\negative-observations.json") "Identity negative observations"
$attestation = Need-File (Join-Path $ReviewRoot "identity-group-attestation.json") "Identity group attestation"
$tool = Need-File (Join-Path $script:RepoRoot "tools\photoreal_identity_cvlface_adaface_vit_diagnostic.py") "CVLFace AdaFace ViT diagnostic"
$setup = Need-File (Join-Path $script:RepoRoot "setup-photoreal-v2-cvlface-adaface-vit-diagnostic.ps1") "CVLFace diagnostic setup"

if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models"
}
$ModelRoot = Need-Directory $ModelRoot "Photoreal reference model root"

if ([string]::IsNullOrWhiteSpace($CvlFaceRoot)) {
    $CvlFaceRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\diagnostic-recognizers\cvlface-adaface-vit-base-webface4m"
}
$cvlModel = Join-Path $CvlFaceRoot "model\model.safetensors"
$cvlProvenance = Join-Path $CvlFaceRoot "source-provenance.json"
$cvlFvcore = Join-Path $CvlFaceRoot "python\fvcore\__init__.py"
$cvlRuntimeReady = $false
if (
    (Test-Path -LiteralPath $cvlModel -PathType Leaf) -and
    (Test-Path -LiteralPath $cvlProvenance -PathType Leaf) -and
    (Test-Path -LiteralPath $cvlFvcore -PathType Leaf)
) {
    try {
        $cvlExisting = Get-Content -LiteralPath $cvlProvenance -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
        $cvlRuntimeReady = (
            $cvlExisting.runtime_dependency_profile -eq "cvlface-vit-runtime-v2" -and
            $cvlExisting.model_cuda_smoke_test -eq $true -and
            $cvlExisting.parallel_torch_install -eq $false
        )
    } catch {
        $cvlRuntimeReady = $false
    }
}
if (-not $cvlRuntimeReady) {
    if (-not $AcceptTrainingDatasetTerms) {
        throw "Pinned CVLFace diagnostic runtime is missing or stale. Re-run with -AcceptTrainingDatasetTerms after reviewing the model-card training-dataset license requirement."
    }
    & $setup -DiagnosticRoot $CvlFaceRoot -AcceptTrainingDatasetTerms -Distribution $Distribution -LinuxPython $LinuxPython
    if ($LASTEXITCODE -ne 0) {
        throw "CVLFace diagnostic setup/repair failed with exit code $LASTEXITCODE."
    }
}
$CvlFaceRoot = Need-Directory $CvlFaceRoot "Pinned CVLFace diagnostic root"
$cvlModel = Need-File (Join-Path $CvlFaceRoot "model\model.safetensors") "Pinned CVLFace model"
$cvlProvenance = Need-File (Join-Path $CvlFaceRoot "source-provenance.json") "Pinned CVLFace provenance"

$tempIdentityRequest = $null
$tempCalibrationRequest = $null
try {
    $tempIdentityRequest = New-WslTransportRequest -SourceRequest $identityRequest -Prefix "identity-cvlface-adaface-vit"
    $tempCalibrationRequest = New-WslTransportRequest -SourceRequest $calibrationRequest -Prefix "calibration-cvlface-adaface-vit"

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $output = Join-Path $RunDirectory ("identity-cvlface-adaface-vit-diagnostic-{0}.json" -f $stamp)
    if (Test-Path -LiteralPath $output) {
        throw "CVLFace AdaFace ViT diagnostic output already exists: $output"
    }

    $wslRepo = Convert-ToWslPath $script:RepoRoot
    $wslTool = Convert-ToWslPath $tool
    $wslBank = Convert-ToWslPath $bank
    $wslIdentityRequest = Convert-ToWslPath $tempIdentityRequest
    $wslIdentityRequestOrigin = Convert-ToWslPath $identityRequest
    $wslCalibrationRequest = Convert-ToWslPath $tempCalibrationRequest
    $wslCalibrationRequestOrigin = Convert-ToWslPath $calibrationRequest
    $wslNegativeObservations = Convert-ToWslPath $negativeObservations
    $wslReview = Convert-ToWslPath $ReviewRoot
    $wslModelRoot = Convert-ToWslPath $ModelRoot
    $wslCvlFaceRoot = Convert-ToWslPath $CvlFaceRoot
    $wslOutput = Convert-ToWslPath $output

    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - CVLFACE ADAFACE VIT DIAGNOSTIC"
    Write-Host "Revision:       $head"
    Write-Host "Run:            $RunDirectory"
    Write-Host "Review:         $ReviewRoot"
    Write-Host "Attestation:    $attestation"
    Write-Host "Device:         $Device"
    Write-Host "Current:        buffalo_l / w600k_r50 / ResNet50@WebFace600K"
    Write-Host "Alternate:      CVLFace / AdaFace / ViT-Base@WebFace4M"
    Write-Host "Evidence:       exact 27 positive + persisted negative frames"
    Write-Host "Source rehash:  NO"
    Write-Host "Authority:      DIAGNOSTIC ONLY / FALSE"
    Write-Host "Production:     FALSE"
    Write-Host "============================================================"
    Write-Host ""

    $wslArgs = @(
        "-d", $Distribution, "--", "env",
        "PYTHONPATH=$wslRepo",
        "BODYRIG_REVISION=$head",
        $LinuxPython, $wslTool,
        "--identity-bank", $wslBank,
        "--identity-request", $wslIdentityRequest,
        "--identity-request-origin", $wslIdentityRequestOrigin,
        "--calibration-request", $wslCalibrationRequest,
        "--calibration-request-origin", $wslCalibrationRequestOrigin,
        "--negative-observations", $wslNegativeObservations,
        "--review-root", $wslReview,
        "--model-root", $wslModelRoot,
        "--cvlface-root", $wslCvlFaceRoot,
        "--device", $Device,
        "--out", $wslOutput
    )

    & wsl.exe @wslArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CVLFace AdaFace ViT diagnostic failed with exit code $LASTEXITCODE."
    }

    $result = Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

    Write-Host ""
    Write-Host "CVLFace AdaFace ViT diagnostic: PASS"
    Write-Host "Positive references: $($result.positive_reference_count)"
    Write-Host "Human-attested groups: $($result.human_attested_group_count)"
    Write-Host "Persisted negatives: $($result.negative_observation_count)"
    Write-Host ""
    Write-Host "Recognizer scoring:"
    foreach ($name in @("bank-w600k-r50","cvlface-adaface-vit-base-webface4m")) {
        $variant = $result.variants.$name
        if ($null -eq $variant) { continue }
        Write-Host ("{0,-36} pos={1,6:P1} neg={2,6:P1}" -f $name, [double]$variant.positive_reference_coverage, [double]$variant.negative_observation_coverage)
        foreach ($model in @("current-reference-weighted","group-balanced-centroid-lgo","nearest-group-prototype")) {
            $score = $variant.scoring_models.$model
            if ($null -eq $score) { continue }
            Write-Host ("  {0,-30} floor={1} ceiling={2} margin={3} meets={4}" -f $model, $score.positive_floor, $score.negative_ceiling, $score.observed_separation_margin, $score.would_meet_margin)
        }
    }

    Write-Host ""
    Write-Host "Diagnostic JSON: $output"
    Write-Host "License: model-card training-dataset terms remain operator-reviewed; diagnostic only."
    Write-Host "Authority: diagnostic-only; no identity matching, training, photoreal or production authority."
} finally {
    if ($null -ne $tempIdentityRequest) {
        Remove-Item -LiteralPath $tempIdentityRequest -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $tempCalibrationRequest) {
        Remove-Item -LiteralPath $tempCalibrationRequest -Force -ErrorAction SilentlyContinue
    }
}
