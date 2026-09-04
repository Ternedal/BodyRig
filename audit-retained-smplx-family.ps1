param(
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$OutputFile,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Invoke-WslRaw {
    param([Parameter(Mandatory = $true)][object[]]$Arguments)
    $lines = @(& $WslExe -d $Distribution -- @Arguments 2>&1)
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Lines = $lines
        Text = ($lines -join "`n").Trim()
    }
}
function Convert-WindowsPathToWsl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $escaped = $Path.Replace('\', '\\')
    $result = Invoke-WslRaw -Arguments @("wslpath", "-a", "-u", $escaped)
    if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.Text)) {
        throw "WSL path translation failed for $Path`: $($result.Text)"
    }
    return $result.Text.Trim()
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig retained SMPL-X family audit is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Retained SMPL-X family audit requires an exact clean BodyRig checkout." }

$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Identity workspace"
$stage = Need-Directory -Path (Join-Path $IdentityWorkspace "sith-input-v1") -Label "Retained SiTH input"
$reconstruction = Need-File -Path (Join-Path $stage "reconstruction.json") -Label "Retained reconstruction authority"
$smplxObj = Need-File -Path (Join-Path $stage "smplx\000_smplx.obj") -Label "Retained fitted SMPL-X OBJ"
$fitParams = Need-File -Path (Join-Path $stage "smplx\000_fit.json") -Label "Retained SMPL-X fit params"
$auditScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_reconstruction_model_family_audit.py") -Label "BodyRig reconstruction family audit bridge"

$OutputFile = [IO.Path]::GetFullPath($OutputFile)
if (Test-Path -LiteralPath $OutputFile) { throw "SMPL-X family audit output already exists: $OutputFile" }
$outputParent = Split-Path -Parent $OutputFile
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "SMPL-X family audit output must have a parent directory." }
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null

$WslExeResolved = Get-Command $WslExe -ErrorAction SilentlyContinue
if ($null -eq $WslExeResolved) { throw "WSL executable not found: $WslExe" }
$WslExe = $WslExeResolved.Source
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $home = Invoke-WslRaw -Arguments @("/usr/bin/python3", "-c", "import pathlib; print(pathlib.Path.home().as_posix())")
    if ($home.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($home.Text)) {
        throw "Could not resolve WSL home directory: $($home.Text)"
    }
    $InstallRoot = "$($home.Text.Trim())/.local/share/bodyrig/sith"
}
if (-not $InstallRoot.StartsWith("/")) { throw "-InstallRoot must be an absolute Linux path." }
$InstallRoot = $InstallRoot.TrimEnd("/")
$venvPython = "$InstallRoot/.bodyrig-venv/bin/python"
$modelDir = "$InstallRoot/data/body_models/smplx"
foreach ($probePath in @($venvPython, "$modelDir/SMPLX_FEMALE.npz", "$modelDir/SMPLX_MALE.npz", "$modelDir/SMPLX_NEUTRAL.npz")) {
    $probe = Invoke-WslRaw -Arguments @("/usr/bin/test", "-f", $probePath)
    if ($probe.ExitCode -ne 0) { throw "Required SiTH/SMPL-X audit asset is missing: $probePath" }
}

$workspaceWsl = Convert-WindowsPathToWsl -Path $IdentityWorkspace
$outputWsl = Convert-WindowsPathToWsl -Path $OutputFile
$scriptWsl = Convert-WindowsPathToWsl -Path $auditScript
$reconstructionShaBefore = Sha256 $reconstruction
$smplxSha = Sha256 $smplxObj
$fitSha = Sha256 $fitParams

Write-Host "BodyRig retained SMPL-X family audit"
Write-Host "Revision:       $head"
Write-Host "Reconstruction: $reconstructionShaBefore"
Write-Host "SMPL-X OBJ:     $smplxSha"
Write-Host "Fit params:     $fitSha"
Write-Host "SiTH rerun:     FALSE"
Write-Host ""

$audit = Invoke-WslRaw -Arguments @(
    $venvPython,
    $scriptWsl,
    "--smplx-model-dir", $modelDir,
    "--bodyrig-workspace", $workspaceWsl,
    "--output", $outputWsl
)
foreach ($line in $audit.Lines) { Write-Host ([string]$line) }
if ($audit.ExitCode -ne 0) { throw "SMPL-X family audit failed with exit code $($audit.ExitCode)." }

$reconstructionShaAfter = Sha256 $reconstruction
if ($reconstructionShaAfter -ne $reconstructionShaBefore) {
    throw "Retained reconstruction authority changed during SMPL-X family audit."
}
if (-not (Test-Path -LiteralPath $OutputFile -PathType Leaf)) { throw "SMPL-X family audit did not publish JSON evidence." }
try { $evidence = Get-Content -LiteralPath $OutputFile -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "SMPL-X family audit JSON evidence is unreadable." }
if ([string]$evidence.format -ne "bodyrig-reconstruction-smplx-family-audit" -or [int]$evidence.version -ne 1) {
    throw "SMPL-X family audit JSON evidence has an unexpected contract."
}
if ([string]$evidence.retainedSmplxObjSha256 -ne $smplxSha -or [string]$evidence.retainedFitParamsSha256 -ne $fitSha) {
    throw "SMPL-X family audit JSON evidence does not bind the retained fit bytes."
}
if ($evidence.reconstructionRerun -ne $false -or $evidence.geometryModified -ne $false -or $evidence.productionReady -ne $false) {
    throw "SMPL-X family audit returned an invalid authority boundary."
}

Write-Host ""
Write-Host "Evidence:       $OutputFile"
Write-Host "Model family:   $([string]$evidence.authorityModelFamily)"
Write-Host "Human review:   REQUIRED"
Write-Host "Production:     FALSE"
Write-Host "SiTH rerun:     FALSE"
Write-Host "BodyRig retained SMPL-X family audit: PASS"
exit 0
