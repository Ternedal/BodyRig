param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
    [string]$ModelRoot = "",
    [string]$DiagnosticRecognizerRoot = "",
    [switch]$AcceptInsightFaceResearchLicense,
    [switch]$OpenReview,
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
    throw "Negative identity confusion review requires a clean BodyRig checkout."
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
$tool = Need-File (Join-Path $script:RepoRoot "tools\photoreal_identity_negative_confusion_review.py") "Negative identity confusion review"
$setup = Need-File (Join-Path $script:RepoRoot "setup-photoreal-v2-identity-recognizer-diagnostic.ps1") "Diagnostic recognizer setup"

if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models"
}
$ModelRoot = Need-Directory $ModelRoot "Photoreal reference model root"

if ([string]::IsNullOrWhiteSpace($DiagnosticRecognizerRoot)) {
    $DiagnosticRecognizerRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\diagnostic-recognizers\antelopev2"
}
$recognizer = Join-Path $DiagnosticRecognizerRoot "glintr100.onnx"
$recognizerProvenance = Join-Path $DiagnosticRecognizerRoot "source-provenance.json"
if (
    -not (Test-Path -LiteralPath $recognizer -PathType Leaf) -or
    -not (Test-Path -LiteralPath $recognizerProvenance -PathType Leaf)
) {
    if (-not $AcceptInsightFaceResearchLicense) {
        throw "Pinned antelopev2 diagnostic recognizer is not installed. Re-run with -AcceptInsightFaceResearchLicense after reviewing and accepting the InsightFace pretrained-model research license."
    }
    & $setup -DiagnosticRoot $DiagnosticRecognizerRoot -AcceptInsightFaceResearchLicense
    if ($LASTEXITCODE -ne 0) {
        throw "Diagnostic recognizer setup failed with exit code $LASTEXITCODE."
    }
}
$DiagnosticRecognizerRoot = Need-Directory $DiagnosticRecognizerRoot "Pinned antelopev2 diagnostic recognizer root"
$recognizer = Need-File (Join-Path $DiagnosticRecognizerRoot "glintr100.onnx") "Pinned antelopev2 glintr100 recognizer"
$recognizerProvenance = Need-File (Join-Path $DiagnosticRecognizerRoot "source-provenance.json") "Pinned antelopev2 recognizer provenance"

$tempIdentityRequest = $null
$tempCalibrationRequest = $null
try {
    $tempIdentityRequest = New-WslTransportRequest -SourceRequest $identityRequest -Prefix "identity-negative-confusion"
    $tempCalibrationRequest = New-WslTransportRequest -SourceRequest $calibrationRequest -Prefix "calibration-negative-confusion"

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $output = Join-Path $RunDirectory ("identity-negative-confusion-review-{0}" -f $stamp)
    if (Test-Path -LiteralPath $output) {
        throw "Negative identity confusion review output already exists: $output"
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
    $wslDiagnosticRecognizerRoot = Convert-ToWslPath $DiagnosticRecognizerRoot
    $wslOutput = Convert-ToWslPath $output

    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - NEGATIVE IDENTITY CONFUSION REVIEW"
    Write-Host "Revision:       $head"
    Write-Host "Run:            $RunDirectory"
    Write-Host "Review:         $ReviewRoot"
    Write-Host "Attestation:    $attestation"
    Write-Host "Device:         $Device"
    Write-Host "Recognizers:    w600k_r50 + antelopev2/glintr100"
    Write-Host "Evidence:       exact 27 positive + persisted negative frames"
    Write-Host "Review crop:    aligned 112x112 recognizer input"
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
        "--diagnostic-recognizer-root", $wslDiagnosticRecognizerRoot,
        "--device", $Device,
        "--out", $wslOutput
    )

    & wsl.exe @wslArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Negative identity confusion review failed with exit code $LASTEXITCODE."
    }

    $jsonPath = Need-File (Join-Path $output "negative-confusion-review.json") "Negative confusion review JSON"
    $htmlPath = Need-File (Join-Path $output "review-index.html") "Negative confusion review HTML"
    $result = Get-Content -LiteralPath $jsonPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

    Write-Host ""
    Write-Host "Negative identity confusion review: PASS"
    Write-Host "Positive references: $($result.positive_reference_count)"
    Write-Host "Human-attested groups: $($result.human_attested_group_count)"
    Write-Host "Persisted negatives: $($result.negative_observation_count)"
    Write-Host ""
    Write-Host "Highest negative confusions:"
    foreach ($row in @($result.negative_reviews)) {
        Write-Host (
            "  negative={0} subject={1} | w600k target={2} nearest={3}:{4} | glintr100 target={5} nearest={6}:{7}" -f
            $row.negative_index,
            $row.subject_performer_id,
            $row.current_target_cosine,
            $row.current.nearest_group_id,
            $row.current.nearest_group_cosine,
            $row.alternate_target_cosine,
            $row.alternate.nearest_group_id,
            $row.alternate.nearest_group_cosine
        )
    }
    Write-Host ""
    Write-Host "Review HTML: $htmlPath"
    Write-Host "Review JSON: $jsonPath"
    Write-Host "Authority: diagnostic-only; visual review grants no identity matching, training, photoreal or production authority."

    if ($OpenReview) {
        Start-Process $htmlPath
    } else {
        Write-Host "Open with:"
        Write-Host ("  Start-Process `"{0}`"" -f $htmlPath)
    }
} finally {
    if ($null -ne $tempIdentityRequest) {
        Remove-Item -LiteralPath $tempIdentityRequest -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $tempCalibrationRequest) {
        Remove-Item -LiteralPath $tempCalibrationRequest -Force -ErrorAction SilentlyContinue
    }
}
