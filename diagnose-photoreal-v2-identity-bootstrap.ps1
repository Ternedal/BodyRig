param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [string]$ModelRoot = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [ValidateSet("cpu", "cuda", "cuda:0")][string]$Device = "cuda:0"
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

function Convert-ToWslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)
    if ($WindowsPath.StartsWith('/')) { return $WindowsPath }

    $pythonCode = @'
import sys
sys.path.insert(0, sys.argv[1])
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
print(make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4]))
'@

    $lines = @(& $script:WindowsPython -c $pythonCode $script:RepoRoot "wsl.exe" $Distribution $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
        throw "Could not convert Windows/UNC path with BodyRig WSL bridge: $WindowsPath | $($lines -join ' ')"
    }
    $value = ([string]$lines[0]).Trim()
    if ([string]::IsNullOrWhiteSpace($value) -or -not $value.StartsWith('/')) {
        throw "BodyRig WSL bridge returned an invalid path for: $WindowsPath"
    }
    return $value
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) {
    throw "LinuxPython must be an absolute Linux path."
}

$script:RepoRoot = (Resolve-Path $PSScriptRoot).Path
$script:WindowsPython = Need-File -Path (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") -Label "BodyRig Windows Python"
$repoRoot = $script:RepoRoot
$RunDirectory = Need-Directory -Path $RunDirectory -Label "Photoreal resumed run"
$request = Need-File -Path (Join-Path $RunDirectory "identity-extractor\request.json") -Label "Stage-7 identity request"
$tool = Need-File -Path (Join-Path $repoRoot "tools\photoreal_reference_identity_diagnostic.py") -Label "Identity diagnostic tool"

if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models"
}
$ModelRoot = Need-Directory -Path $ModelRoot -Label "Photoreal reference model root"
$output = Join-Path $RunDirectory "identity-reference-diagnostic.json"
if (Test-Path -LiteralPath $output) {
    throw "Identity diagnostic output already exists: $output"
}

# Reproduce the existing BodyRig WSL bridge semantics for diagnostics only:
# translate exactly nested source.resolved_path values, preserving all source
# identity, hashes, samples and authority fields from the original request.
# The shared converter handles drive-letter, SUBST/reparse and UNC/DrvFS paths.
$requestObject = Get-Content -LiteralPath $request -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ($null -eq $requestObject.sources -or @($requestObject.sources).Count -eq 0) {
    throw "Stage-7 identity request contains no sources."
}
foreach ($source in @($requestObject.sources)) {
    $raw = ([string]$source.resolved_path).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) { throw "Stage-7 source has no resolved_path." }
    $source.resolved_path = Convert-ToWslPath -WindowsPath $raw
}

$tempRequest = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-identity-diagnostic-request-{0}.json" -f [Guid]::NewGuid().ToString("N"))
$requestObject | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $tempRequest -Encoding UTF8

$wslTool = Convert-ToWslPath -WindowsPath $tool
$wslRequest = Convert-ToWslPath -WindowsPath $tempRequest
$wslModelRoot = Convert-ToWslPath -WindowsPath $ModelRoot
$wslOutput = Convert-ToWslPath -WindowsPath $output

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - STAGE 7 IDENTITY DIAGNOSTIC"
Write-Host "Run:        $RunDirectory"
Write-Host "Request:    $request"
Write-Host "Model root: $ModelRoot"
Write-Host "Device:     $Device"
Write-Host "Output:     $output"
Write-Host "Authority:  DIAGNOSTIC ONLY / FALSE"
Write-Host "============================================================"
Write-Host ""

try {
    & wsl.exe -d $Distribution -- $LinuxPython $wslTool `
        --request $wslRequest `
        --model-root $wslModelRoot `
        --device $Device `
        --out $wslOutput
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Stage-7 identity diagnostic failed with exit code $exitCode."
    }
} finally {
    Remove-Item -LiteralPath $tempRequest -Force -ErrorAction SilentlyContinue
}

$result = Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
Write-Host ""
Write-Host "Identity diagnostic: PASS"
Write-Host "Samples:    $($result.sample_count)"
Write-Host "Accepted:   $($result.accepted_count)"
Write-Host "Rejected:   $($result.rejected_count)"
Write-Host ""
Write-Host "Rejection/acceptance reasons:"
$result.reason_counts.PSObject.Properties | ForEach-Object {
    Write-Host ("  {0}: {1}" -f $_.Name, $_.Value)
}
Write-Host ""
Write-Host "Per-sample diagnostic:"
$result.samples | Select-Object source_key,timestamp_seconds,eye,candidate_count,face_candidate_count,accepted,reason | Format-Table -AutoSize -Wrap
Write-Host ""
Write-Host "Diagnostic output: $output"
