param(
    [Parameter(Mandatory = $true)]
    [string[]]$Source,

    [Parameter(Mandatory = $true)]
    [string]$ExternalPython,

    [Parameter(Mandatory = $true)]
    [string]$FourDHumansRepo,

    [Parameter(Mandatory = $true)]
    [string]$IdentityCaptureConfig,

    [Parameter(Mandatory = $true)]
    [string]$FitterConfig,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId,

    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 160)]
    [string]$Name,

    [string]$TrackId = "",
    [string]$OutputDir = "",
    [string]$PrivateWorkspace = "",
    [string]$BodyRigPython = "",
    [switch]$AllowCpu,
    [switch]$KeepPrivateWorkspace
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-InputDirectory {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ($Source.Count -lt 1 -or $Source.Count -gt 10) {
    throw "BodyRig accepts 1..10 source clips."
}

$resolvedSources = @()
foreach ($item in $Source) {
    $resolvedSources += Resolve-InputFile -Path $item -Label "Source clip"
}
$ExternalPython = Resolve-InputFile -Path $ExternalPython -Label "External recovery Python"
$FourDHumansRepo = Resolve-InputDirectory -Path $FourDHumansRepo -Label "4D-Humans repository"
$IdentityCaptureConfig = Resolve-InputFile -Path $IdentityCaptureConfig -Label "Identity capture config"
$FitterConfig = Resolve-InputFile -Path $FitterConfig -Label "High-fidelity fitter config"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $BodyRigPython = $venvPython
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) {
            throw "BodyRig Python not found. Create .venv or pass -BodyRigPython."
        }
        $BodyRigPython = $pythonCommand.Source
    }
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"

$stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path (Get-Location).Path "bodyrig-clone-$BodyId-$stamp"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) {
    throw "Clone output directory already exists; refusing cross-run reuse: $OutputDir"
}
New-Item -ItemType Directory -Path $OutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($PrivateWorkspace)) {
    $privateBase = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($privateBase)) {
        $privateBase = [System.IO.Path]::GetTempPath()
    }
    $PrivateWorkspace = Join-Path $privateBase ("BodyRig\identity-workspaces\$BodyId-$stamp-" + [Guid]::NewGuid().ToString("N"))
}
$PrivateWorkspace = [System.IO.Path]::GetFullPath($PrivateWorkspace)
if (Test-Path -LiteralPath $PrivateWorkspace) {
    throw "Private identity workspace already exists; refusing cross-run reuse: $PrivateWorkspace"
}

$preflightPath = Join-Path $OutputDir "bodyrig-recovery-preflight.json"
$proofPath = Join-Path $OutputDir "bodyrig-recovery-proof.json"
$identityPath = Join-Path $OutputDir "bodyrig-visual-identity.json"
$packagePath = Join-Path $OutputDir "$BodyId.mrbody"

$success = $false
try {
    Write-Host "BodyRig clone | $Name | $BodyId"
    Write-Host "Source clips: $($resolvedSources.Count)"
    Write-Host "Portable artifacts: $OutputDir"
    Write-Host "Private identity workspace: $PrivateWorkspace"
    Write-Host ""

    $preflightArgs = @(
        "-m", "bodyrig.preflight_cli",
        "--python", $ExternalPython,
        "--repo", $FourDHumansRepo,
        "--out", $preflightPath
    )
    if ($AllowCpu) { $preflightArgs += "--allow-cpu" }
    Invoke-Checked -Executable $BodyRigPython -Arguments $preflightArgs -Step "Recovery preflight"

    $recoverArgs = @(
        "-m", "bodyrig.recover_cli",
        "--python", $ExternalPython,
        "--repo", $FourDHumansRepo,
        "--out", $proofPath
    )
    if (-not [string]::IsNullOrWhiteSpace($TrackId)) {
        $recoverArgs += @("--track-id", $TrackId)
    }
    $recoverArgs += $resolvedSources
    Invoke-Checked -Executable $BodyRigPython -Arguments $recoverArgs -Step "Video recovery"

    $captureArgs = @(
        "-m", "bodyrig.identity_capture_cli",
        $proofPath
    )
    $captureArgs += $resolvedSources
    $captureArgs += @(
        "--config", $IdentityCaptureConfig,
        "--workspace", $PrivateWorkspace,
        "--out", $identityPath
    )
    Invoke-Checked -Executable $BodyRigPython -Arguments $captureArgs -Step "Visual identity capture"

    $fitArgs = @(
        "-m", "bodyrig.external_fitter_cli",
        $proofPath,
        "--identity-profile", $identityPath,
        "--identity-workspace", $PrivateWorkspace,
        "--config", $FitterConfig,
        "--body-id", $BodyId,
        "--name", $Name,
        "--out", $packagePath
    )
    Invoke-Checked -Executable $BodyRigPython -Arguments $fitArgs -Step "High-fidelity avatar fitting"

    $validateCode = @'
import hashlib, json, pathlib, sys
from bodyrig.package import validate_package
p = pathlib.Path(sys.argv[1]).resolve()
v = validate_package(p)
print(json.dumps({
  "body_id": v.manifest["id"],
  "package_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
  "payloads": list(v.payload_names),
  "pipeline": v.provenance["pipeline"],
}, separators=(",", ":")))
'@
    $validatedRaw = & $BodyRigPython -c $validateCode $packagePath
    if ($LASTEXITCODE -ne 0) {
        throw "Final .mrbody validation failed with exit code $LASTEXITCODE"
    }
    $validated = $validatedRaw | ConvertFrom-Json
    if ([string]$validated.body_id -ne $BodyId) {
        throw "Final .mrbody body id mismatch."
    }

    $success = $true
    Write-Host ""
    Write-Host "BodyRig clone: PASS"
    Write-Host "Package: $packagePath"
    Write-Host "Package SHA-256: $($validated.package_sha256)"
    Write-Host "Recovery proof: $proofPath"
    Write-Host "Visual identity profile: $identityPath"
} finally {
    if (-not $KeepPrivateWorkspace -and (Test-Path -LiteralPath $PrivateWorkspace -PathType Container)) {
        Remove-Item -LiteralPath $PrivateWorkspace -Recurse -Force -ErrorAction SilentlyContinue
        if ($success) {
            Write-Host "Private identity workspace deleted after successful package build."
        } else {
            Write-Host "Private identity workspace deleted after failed build."
        }
    } elseif ($KeepPrivateWorkspace -and (Test-Path -LiteralPath $PrivateWorkspace -PathType Container)) {
        Write-Host "Private identity workspace retained by explicit request: $PrivateWorkspace"
    }
}

if (-not $success) { exit 1 }
exit 0
