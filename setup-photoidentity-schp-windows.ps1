param(
    [string]$RuntimeRoot = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Executable {
    param([string]$Value,[string]$Fallback,[string]$Label)
    $candidate = if ([string]::IsNullOrWhiteSpace($Value)) { $Fallback } else { $Value }
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "$Label executable not found: $candidate" }
    return $command.Source
}
function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$Executable,[Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Step)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE." }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig SCHP runtime provisioning is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not establish exact BodyRig Git authority before SCHP provisioning."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "SCHP provisioning requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = Need-Executable -Value "" -Fallback "python" -Label "BodyRig Python" }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "BodyRig Python could not prove checkout-bound imports." }
$actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports from a different checkout: $actualModule"
}

if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $base = [string]$env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($base)) { throw "LOCALAPPDATA is required for the default isolated SCHP runtime." }
    $RuntimeRoot = Join-Path $base "BodyRig\runtimes\schp-atr18-v1"
}
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$runtimePython = Join-Path $RuntimeRoot "venv\Scripts\python.exe"
$receiptPath = Join-Path $RuntimeRoot "runtime.json"
$modelDir = Join-Path $RuntimeRoot "model"
$modelPath = Join-Path $modelDir "schp-atr-18-int8-static.onnx"

if (Test-Path -LiteralPath $RuntimeRoot) {
    Write-Host "Existing SCHP runtime found; validating instead of mutating it."
    Invoke-Checked -Executable $BodyRigPython -Arguments @("-m","bodyrig.photoidentity_schp_preflight","--runtime-root",$RuntimeRoot) -Step "Existing SCHP runtime preflight"
    Write-Host "BodyRig SCHP runtime: READY | $RuntimeRoot"
    exit 0
}

$contractCode = @'
import json
from bodyrig.photoidentity_schp_contract import *
print(json.dumps({
  "model_repository": MODEL_REPOSITORY,
  "model_revision": MODEL_REVISION,
  "model_file": MODEL_FILE,
  "model_sha256": MODEL_SHA256,
  "model_size": MODEL_SIZE,
  "model_url": MODEL_URL,
  "upstream_repository": UPSTREAM_REPOSITORY,
  "upstream_revision": UPSTREAM_REVISION,
}, separators=(",", ":")))
'@
$contractRaw = @(& $BodyRigPython -c $contractCode 2>&1)
if ($LASTEXITCODE -ne 0 -or $contractRaw.Count -ne 1) { throw "Could not read the pinned SCHP contract from the checkout." }
try { $contract = ([string]$contractRaw[0]) | ConvertFrom-Json -Depth 10 }
catch { throw "Pinned SCHP contract returned unreadable JSON." }

$created = $false
try {
    New-Item -ItemType Directory -Path $RuntimeRoot | Out-Null
    $created = $true
    New-Item -ItemType Directory -Path $modelDir | Out-Null

    Write-Host "BodyRig SCHP isolated runtime provisioning"
    Write-Host "Runtime:  $RuntimeRoot"
    Write-Host "Model:    $([string]$contract.model_repository) @ $([string]$contract.model_revision)"
    Write-Host "SHA-256:  $([string]$contract.model_sha256)"
    Write-Host "Policy:   external weights are downloaded locally; BodyRig does not redistribute them"
    Write-Host ""

    Invoke-Checked -Executable $BodyRigPython -Arguments @("-m","venv",(Join-Path $RuntimeRoot "venv")) -Step "Create isolated SCHP Python venv"
    $runtimePython = Need-File -Path $runtimePython -Label "Isolated SCHP Python"
    Invoke-Checked -Executable $runtimePython -Arguments @(
        "-m","pip","install","--disable-pip-version-check","--no-input",
        "numpy==2.2.6","onnxruntime==1.22.1","Pillow==11.3.0"
    ) -Step "Install pinned SCHP runtime packages"

    $temporaryModel = Join-Path $modelDir (".download-" + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        Invoke-WebRequest -Uri ([string]$contract.model_url) -OutFile $temporaryModel -MaximumRedirection 10
        if (-not (Test-Path -LiteralPath $temporaryModel -PathType Leaf)) { throw "SCHP model download produced no file." }
        $length = (Get-Item -LiteralPath $temporaryModel).Length
        if ($length -ne [long]$contract.model_size) {
            throw "SCHP model size mismatch after download: expected $([long]$contract.model_size), got $length"
        }
        $actualHash = (Get-FileHash -LiteralPath $temporaryModel -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne ([string]$contract.model_sha256).ToLowerInvariant()) {
            throw "SCHP model SHA-256 mismatch after download: expected $([string]$contract.model_sha256), got $actualHash"
        }
        Move-Item -LiteralPath $temporaryModel -Destination $modelPath
    } finally {
        Remove-Item -LiteralPath $temporaryModel -Force -ErrorAction SilentlyContinue
    }

    $receipt = [ordered]@{
        format = "bodyrig-photoidentity-schp-runtime"
        version = 1
        model_repository = [string]$contract.model_repository
        model_revision = [string]$contract.model_revision
        model_file = [string]$contract.model_file
        model_sha256 = ([string]$contract.model_sha256).ToLowerInvariant()
        model_size = [long]$contract.model_size
        upstream_repository = [string]$contract.upstream_repository
        upstream_revision = [string]$contract.upstream_revision
        weights_redistributed_by_bodyrig = $false
        onnxruntime_version = "1.22.1"
        numpy_version = "2.2.6"
        pillow_version = "11.3.0"
    }
    $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding utf8NoBOM

    Invoke-Checked -Executable $BodyRigPython -Arguments @("-m","bodyrig.photoidentity_schp_preflight","--runtime-root",$RuntimeRoot) -Step "Fresh SCHP runtime preflight"
    Write-Host "BodyRig SCHP runtime provisioning: PASS"
    Write-Host "Runtime: $RuntimeRoot"
} catch {
    if ($created) {
        Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
