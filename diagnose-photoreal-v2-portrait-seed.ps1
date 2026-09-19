param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [string]$StashUrl = "http://192.168.1.21:9998",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$ModelRoot = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [ValidateSet("cpu", "cuda", "cuda:0")][string]$Device = "cuda:0",
    [ValidateRange(1,24)][int]$ReferenceLimit = 12
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
function Convert-ToWslPath {
    param([string]$WindowsPath)
    if ($WindowsPath.StartsWith("/")) { return $WindowsPath }
    $pythonCode = @'
import sys
sys.path.insert(0, sys.argv[1])
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
print(make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4]))
'@
    $lines = @(& $script:WindowsPython -c $pythonCode $script:RepoRoot "wsl.exe" $Distribution $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) { throw "Could not convert path with BodyRig WSL bridge: $WindowsPath | $($lines -join ' ')" }
    $value = ([string]$lines[0]).Trim()
    if ([string]::IsNullOrWhiteSpace($value) -or -not $value.StartsWith("/")) { throw "BodyRig WSL bridge returned invalid path: $WindowsPath" }
    return $value
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }
$script:RepoRoot = (Resolve-Path $PSScriptRoot).Path
$script:WindowsPython = Need-File (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") "BodyRig Windows Python"
$RunDirectory = Need-Directory $RunDirectory "Photoreal resumed run"
$bank = Need-File (Join-Path $RunDirectory "identity-bank.json") "Identity bank"
$tool = Need-File (Join-Path $script:RepoRoot "tools\photoreal_portrait_seed_diagnostic.py") "Portrait seed diagnostic tool"

$bankJson = Get-Content -LiteralPath $bank -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$performerId = ([string]$bankJson.performer_id).Trim()
if ([string]::IsNullOrWhiteSpace($performerId)) { throw "Identity bank performer id is missing." }

if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models"
}
$ModelRoot = Need-Directory $ModelRoot "Photoreal reference model root"

$workspace = Join-Path $RunDirectory "portrait-seed-diagnostic"
if (Test-Path -LiteralPath $workspace) { throw "Portrait seed diagnostic workspace already exists: $workspace" }
New-Item -ItemType Directory -Path $workspace | Out-Null
$references = Join-Path $workspace "references"
$referenceSet = Join-Path $references "reference-set.json"
$output = Join-Path $workspace "portrait-seed-diagnostic.json"

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - PORTRAIT SEED DIAGNOSTIC"
Write-Host "Run:          $RunDirectory"
Write-Host "Performer:    $performerId"
Write-Host "Stash:        $StashUrl"
Write-Host "Device:       $Device"
Write-Host "Reference max:$ReferenceLimit"
Write-Host "Authority:    DIAGNOSTIC ONLY / FALSE"
Write-Host "Production:   FALSE"
Write-Host "============================================================"
Write-Host ""

$priorEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONIOENCODING = "utf-8"
    & $script:WindowsPython -m bodyrig.stash_fidelity_reference_cli `
        --performer-id $performerId `
        --out $references `
        --url $StashUrl `
        --api-key-env $ApiKeyEnv `
        --limit $ReferenceLimit | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Stash portrait reference materialization failed with exit code $LASTEXITCODE." }
} finally {
    if ($null -eq $priorEncoding) { Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue } else { $env:PYTHONIOENCODING = $priorEncoding }
}

$referenceSet = Need-File $referenceSet "Frozen portrait reference set"
$wslTool = Convert-ToWslPath $tool
$wslBank = Convert-ToWslPath $bank
$wslReferenceSet = Convert-ToWslPath $referenceSet
$wslModelRoot = Convert-ToWslPath $ModelRoot
$wslOutput = Convert-ToWslPath $output

& wsl.exe -d $Distribution -- $LinuxPython $wslTool `
    --identity-bank $wslBank `
    --reference-set $wslReferenceSet `
    --model-root $wslModelRoot `
    --device $Device `
    --out $wslOutput
if ($LASTEXITCODE -ne 0) { throw "Portrait seed diagnostic failed with exit code $LASTEXITCODE." }

$result = Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
Write-Host ""
Write-Host "Portrait seed diagnostic: PASS"
Write-Host "Exclusive refs: $($result.exclusive_reference_count)"
Write-Host "Accepted seeds: $($result.accepted_exclusive_seed_count)"
Write-Host "Profile seeds:  $($result.accepted_profile_seed_count)"
Write-Host "Seed pairwise:  $($result.exclusive_seed_pairwise_cosine | ConvertTo-Json -Compress)"
Write-Host ""
Write-Host "Identity-bank groups vs portrait/exclusive seed:"
$result.group_summaries |
    Select-Object group_id,reference_count,exclusive_seed_centroid_cosine,profile_seed_centroid_cosine,source_keys |
    Format-Table -AutoSize -Wrap
Write-Host ""
Write-Host "Lowest seed match:"
$result.lowest_seed_match_group | Format-List
Write-Host ""
Write-Host "Diagnostic JSON: $output"
Write-Host "Authority: diagnostic-only; no matching, training, photoreal or production authority."
