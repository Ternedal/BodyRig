param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
    [string]$ModelRoot = "",
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
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(([string]$lines[0]).Trim()))
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
    throw "Temporal person consistency diagnostic requires a clean BodyRig checkout."
}
$head = ([string](git -C $script:RepoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git HEAD."
}

$RunDirectory = Need-Directory $RunDirectory "Photoreal resumed run"
$ReviewRoot = Need-Directory $ReviewRoot "Human review root"
$bank = Need-File (Join-Path $RunDirectory "identity-bank.json") "Anchor bank"
$identityRequest = Need-File (Join-Path $RunDirectory "identity-extractor\request.json") "Stage-7 request"
$calibrationRequest = Need-File (Join-Path $RunDirectory "identity-calibration-extractor\request.json") "Stage-13 request"
$negativeObservations = Need-File (Join-Path $RunDirectory "identity-calibration-extractor\output\negative-observations.json") "Comparison observations"
$attestation = Need-File (Join-Path $ReviewRoot "identity-group-attestation.json") "Human group attestation"
$tool = Need-File (Join-Path $script:RepoRoot "tools\photoreal_temporal_person_consistency_diagnostic.py") "Temporal person consistency diagnostic"

if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models"
}
$ModelRoot = Need-Directory $ModelRoot "Photoreal reference model root"

$tempIdentityRequest = $null
$tempCalibrationRequest = $null
try {
    $tempIdentityRequest = New-WslTransportRequest -SourceRequest $identityRequest -Prefix "temporal-person-consistency-stage7"
    $tempCalibrationRequest = New-WslTransportRequest -SourceRequest $calibrationRequest -Prefix "temporal-person-consistency-stage13"

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $output = Join-Path $RunDirectory ("temporal-person-consistency-diagnostic-{0}.json" -f $stamp)
    if (Test-Path -LiteralPath $output) {
        throw "Temporal person consistency output already exists: $output"
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
    $wslOutput = Convert-ToWslPath $output

    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - TEMPORAL PERSON CONSISTENCY"
    Write-Host "Revision:       $head"
    Write-Host "Run:            $RunDirectory"
    Write-Host "Review:         $ReviewRoot"
    Write-Host "Attestation:    $attestation"
    Write-Host "Device:         $Device"
    Write-Host "Window:         -0.20/-0.10/0/+0.10/+0.20 sec"
    Write-Host "Signals:        bbox / pose / crop appearance"
    Write-Host "Face matching:  NO"
    Write-Host "Face embedding: NO"
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
        "--device", $Device,
        "--out", $wslOutput
    )

    & wsl.exe @wslArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Temporal person consistency diagnostic failed with exit code $LASTEXITCODE."
    }

    $result = Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

    Write-Host ""
    Write-Host "Temporal person consistency diagnostic: PASS"
    Write-Host "Uses face recognition: $($result.uses_face_recognition)"
    Write-Host "Uses face embeddings:  $($result.uses_face_embedding)"
    Write-Host "Biometric decision:    $($result.uses_biometric_identity_decision)"
    Write-Host ""

    foreach ($entry in @(
        [PSCustomObject]@{ Label = "attested-target"; Summary = $result.target_anchor_summary },
        [PSCustomObject]@{ Label = "comparison"; Summary = $result.comparison_anchor_summary }
    )) {
        $s = $entry.Summary
        Write-Host (
            "{0,-16} coverage={1:P1} ({2}/{3})" -f
            $entry.Label,
            [double]$s.coverage,
            $s.available_anchor_count,
            $s.anchor_count
        )
        if ($null -ne $s.median_bbox_iou) {
            Write-Host (
                "  bbox IoU min/med/max:       {0} / {1} / {2}" -f
                $s.median_bbox_iou.min,
                $s.median_bbox_iou.median,
                $s.median_bbox_iou.max
            )
        }
        if ($null -ne $s.median_appearance_cosine) {
            Write-Host (
                "  appearance min/med/max:     {0} / {1} / {2}" -f
                $s.median_appearance_cosine.min,
                $s.median_appearance_cosine.median,
                $s.median_appearance_cosine.max
            )
        }
        if ($null -ne $s.median_pose_distance) {
            Write-Host (
                "  pose-distance min/med/max:  {0} / {1} / {2}" -f
                $s.median_pose_distance.min,
                $s.median_pose_distance.median,
                $s.median_pose_distance.max
            )
        }
        if ($null -ne $s.median_center_shift) {
            Write-Host (
                "  center-shift min/med/max:   {0} / {1} / {2}" -f
                $s.median_center_shift.min,
                $s.median_center_shift.median,
                $s.median_center_shift.max
            )
        }
    }

    Write-Host ""
    Write-Host "Diagnostic JSON: $output"
    Write-Host "Authority: diagnostic-only; no biometric identity matching or production authority."
} finally {
    if ($null -ne $tempIdentityRequest) {
        Remove-Item -LiteralPath $tempIdentityRequest -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $tempCalibrationRequest) {
        Remove-Item -LiteralPath $tempCalibrationRequest -Force -ErrorAction SilentlyContinue
    }
}
