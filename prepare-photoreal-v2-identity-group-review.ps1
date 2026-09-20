param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [string]$PortraitRoot = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python"
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
import sys
sys.path.insert(0, sys.argv[1])
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
print(make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4]))
'@
    $lines = @(& $script:WindowsPython -c $pythonCode $script:RepoRoot "wsl.exe" $Distribution $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
        throw "Could not convert path with BodyRig WSL bridge: $WindowsPath | $($lines -join ' ')"
    }
    $value = ([string]$lines[0]).Trim()
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
if ($dirty.Count -ne 0) { throw "Identity group review requires a clean BodyRig checkout." }
$head = ([string](git -C $script:RepoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git HEAD."
}

$RunDirectory = Need-Directory $RunDirectory "Photoreal resumed run"
$bank = Need-File (Join-Path $RunDirectory "identity-bank.json") "Identity bank"
$request = Need-File (Join-Path $RunDirectory "identity-extractor\request.json") "Stage-7 identity request"

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

$requestObject = Get-Content -LiteralPath $request -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ($null -eq $requestObject.sources -or @($requestObject.sources).Count -eq 0) {
    throw "Stage-7 identity request contains no sources."
}
foreach ($source in @($requestObject.sources)) {
    $raw = ([string]$source.resolved_path).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) { throw "Stage-7 source has no resolved_path." }
    $source.resolved_path = Convert-ToWslPath -WindowsPath $raw
}

$tempRequest = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-identity-group-review-request-{0}.json" -f [Guid]::NewGuid().ToString("N"))
$requestObject | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $tempRequest -Encoding UTF8

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$output = Join-Path $RunDirectory ("identity-group-review-{0}" -f $stamp)
if (Test-Path -LiteralPath $output) { throw "Identity group review output already exists: $output" }

$wslRepo = Convert-ToWslPath $script:RepoRoot
$wslBank = Convert-ToWslPath $bank
$wslRequest = Convert-ToWslPath $tempRequest
$wslPortrait = Convert-ToWslPath $PortraitRoot
$wslOutput = Convert-ToWslPath $output

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - IDENTITY GROUP HUMAN REVIEW PREP"
Write-Host "Revision:      $head"
Write-Host "Run:           $RunDirectory"
Write-Host "Identity bank: $bank"
Write-Host "Portrait seed: $PortraitRoot"
Write-Host "Output:        $output"
Write-Host "Authority:     REVIEW CANDIDATES ONLY / FALSE"
Write-Host "Production:    FALSE"
Write-Host "============================================================"
Write-Host ""

$wslArgs = @(
    "-d", $Distribution, "--", "env",
    "PYTHONPATH=$wslRepo",
    "BODYRIG_REVISION=$head",
    $LinuxPython, "-m", "bodyrig.photoreal_identity_group_review", "prepare",
    "--identity-bank", $wslBank,
    "--identity-request", $wslRequest,
    "--portrait-root", $wslPortrait,
    "--output-dir", $wslOutput
)

try {
    & wsl.exe @wslArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Identity group review preparation failed with exit code $LASTEXITCODE."
    }
} finally {
    Remove-Item -LiteralPath $tempRequest -Force -ErrorAction SilentlyContinue
}

$manifest = Need-File (Join-Path $output "identity-group-review-candidates.json") "Identity group review manifest"
$privateIndex = Need-File (Join-Path $output "private-review-index.json") "Private identity group review index"
$reviewIndex = Need-File (Join-Path $output "review-index.html") "Identity group review HTML"

$result = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
Write-Host ""
Write-Host "Identity group review preparation: READY"
Write-Host "Groups:       $($result.group_count)"
Write-Host "Human review: REQUIRED"
Write-Host "Review HTML:  $reviewIndex"
Write-Host "Manifest:     $manifest"
Write-Host "Private:      $privateIndex"
Write-Host "Authority:    FALSE until explicit complete human attestation"
Write-Host "Production:   FALSE"
