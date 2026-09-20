param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
    [string]$PortraitRoot = "",
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

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) {
    throw "LinuxPython must be an absolute Linux path."
}

$script:RepoRoot = (Resolve-Path $PSScriptRoot).Path
$script:WindowsPython = Need-File (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") "BodyRig Windows Python"

$dirty = @(git -C $script:RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -ne 0) { throw "Identity representation diagnostic requires a clean BodyRig checkout." }
$head = ([string](git -C $script:RepoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git HEAD."
}

$RunDirectory = Need-Directory $RunDirectory "Photoreal resumed run"
$ReviewRoot = Need-Directory $ReviewRoot "Identity group review root"
$bank = Need-File (Join-Path $RunDirectory "identity-bank.json") "Identity bank"
$request = Need-File (Join-Path $RunDirectory "identity-extractor\request.json") "Stage-7 identity request"
$attestation = Need-File (Join-Path $ReviewRoot "identity-group-attestation.json") "Identity group attestation"
$tool = Need-File (Join-Path $script:RepoRoot "tools\photoreal_identity_representation_diagnostic.py") "Identity representation diagnostic"

if ([string]::IsNullOrWhiteSpace($PortraitRoot)) {
    $PortraitRoot = Get-ChildItem -LiteralPath $RunDirectory -Directory |
        Where-Object {
            $_.Name -like 'portrait-seed-diagnostic-*' -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "portrait-seed-diagnostic.json") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "references\reference-set.json") -PathType Leaf)
        } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    if ([string]::IsNullOrWhiteSpace($PortraitRoot)) {
        throw "No completed portrait-seed diagnostic workspace was found under the run."
    }
}
$PortraitRoot = Need-Directory $PortraitRoot "Portrait seed diagnostic workspace"

if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models"
}
$ModelRoot = Need-Directory $ModelRoot "Photoreal reference model root"

$requestObject = Get-Content -LiteralPath $request -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ($null -eq $requestObject.sources -or @($requestObject.sources).Count -eq 0) {
    throw "Stage-7 identity request contains no sources."
}
foreach ($source in @($requestObject.sources)) {
    $raw = ([string]$source.resolved_path).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) { throw "Stage-7 source has no resolved_path." }
    $source.resolved_path = Convert-ToWslPath -WindowsPath $raw
}

$tempRequest = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-identity-representation-request-{0}.json" -f [Guid]::NewGuid().ToString("N"))
$requestObject | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $tempRequest -Encoding UTF8

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$output = Join-Path $RunDirectory ("identity-representation-diagnostic-{0}.json" -f $stamp)
if (Test-Path -LiteralPath $output) { throw "Identity representation diagnostic output already exists: $output" }

$wslRepo = Convert-ToWslPath $script:RepoRoot
$wslTool = Convert-ToWslPath $tool
$wslBank = Convert-ToWslPath $bank
$wslRequest = Convert-ToWslPath $tempRequest
$wslRequestOrigin = Convert-ToWslPath $request
$wslPortrait = Convert-ToWslPath $PortraitRoot
$wslReview = Convert-ToWslPath $ReviewRoot
$wslModelRoot = Convert-ToWslPath $ModelRoot
$wslOutput = Convert-ToWslPath $output

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - IDENTITY REPRESENTATION DIAGNOSTIC"
Write-Host "Revision:       $head"
Write-Host "Run:            $RunDirectory"
Write-Host "Review:         $ReviewRoot"
Write-Host "Attestation:    $attestation"
Write-Host "Portrait seed:  $PortraitRoot"
Write-Host "Device:         $Device"
Write-Host "FOV sweep:      110, 90, 75, 60 (face-centered)"
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
    "--identity-request", $wslRequest,
    "--identity-request-origin", $wslRequestOrigin,
    "--portrait-root", $wslPortrait,
    "--review-root", $wslReview,
    "--model-root", $wslModelRoot,
    "--device", $Device,
    "--out", $wslOutput
)

try {
    & wsl.exe @wslArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Identity representation diagnostic failed with exit code $LASTEXITCODE."
    }
} finally {
    Remove-Item -LiteralPath $tempRequest -Force -ErrorAction SilentlyContinue
}

$result = Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

Write-Host ""
Write-Host "Identity representation diagnostic: PASS"
Write-Host "References: $($result.reference_count)"
Write-Host "Human-attested groups: $($result.human_attested_group_count)"
Write-Host ""
Write-Host "Variant coherence:"
foreach ($name in @("bank-original","replay-grid-110","face-centered-110","face-centered-90","face-centered-75","face-centered-60")) {
    $variant = $result.variant_aggregates.$name
    if ($null -eq $variant) { continue }
    $lgo = $variant.leave_group_out_cosine
    $profile = $variant.profile_cosine
    $line = "{0,-20} coverage={1,6:P1}  LGO(min/med/max)={2}/{3}/{4}  profile(min/med/max)={5}/{6}/{7}" -f $name, [double]$variant.reference_coverage, $lgo.min, $lgo.median, $lgo.max, $profile.min, $profile.median, $profile.max
    Write-Host $line
}
Write-Host ""
Write-Host "Stereo pairs: $(@($result.stereo_pairs).Count)"
Write-Host "Diagnostic JSON: $output"
Write-Host "Authority: diagnostic-only; no identity matching, training, photoreal or production authority."
