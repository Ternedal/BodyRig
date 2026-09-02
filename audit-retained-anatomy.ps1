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
    throw "BodyRig retained anatomy audit is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Retained anatomy audit requires an exact clean BodyRig checkout." }

$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Identity workspace"
$stage = Need-Directory -Path (Join-Path $IdentityWorkspace "sith-input-v1") -Label "Retained SiTH input"
$reconstruction = Need-File -Path (Join-Path $stage "reconstruction.json") -Label "Retained reconstruction authority"
$donorObj = Need-File -Path (Join-Path $stage "smplx\000_smplx.obj") -Label "Retained fitted SMPL-X OBJ"
$sourceObj = Need-File -Path (Join-Path $stage "meshes\000_reco.obj") -Label "Retained SiTH source mesh"
$auditScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_anatomy_geometry_audit.py") -Label "BodyRig anatomy audit bridge"

$OutputFile = [IO.Path]::GetFullPath($OutputFile)
if (Test-Path -LiteralPath $OutputFile) { throw "Anatomy audit output already exists: $OutputFile" }
$outputParent = Split-Path -Parent $OutputFile
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Anatomy audit output must have a parent directory." }
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
$pythonProbe = Invoke-WslRaw -Arguments @("/usr/bin/test", "-x", $venvPython)
if ($pythonProbe.ExitCode -ne 0) { throw "SiTH WSL Python not found or not executable: $venvPython" }

$donorWsl = Convert-WindowsPathToWsl -Path $donorObj
$sourceWsl = Convert-WindowsPathToWsl -Path $sourceObj
$outputWsl = Convert-WindowsPathToWsl -Path $OutputFile
$scriptWsl = Convert-WindowsPathToWsl -Path $auditScript

$reconstructionShaBefore = Sha256 $reconstruction
$donorSha = Sha256 $donorObj
$sourceSha = Sha256 $sourceObj

Write-Host "BodyRig retained anatomy audit"
Write-Host "Revision:       $head"
Write-Host "Reconstruction: $reconstructionShaBefore"
Write-Host "Donor OBJ:      $donorSha"
Write-Host "Source OBJ:     $sourceSha"
Write-Host "SiTH rerun:     FALSE"
Write-Host ""

$audit = Invoke-WslRaw -Arguments @(
    $venvPython,
    $scriptWsl,
    "--donor-obj", $donorWsl,
    "--source-obj", $sourceWsl,
    "--output", $outputWsl
)
foreach ($line in $audit.Lines) { Write-Host ([string]$line) }
if ($audit.ExitCode -notin @(0, 2)) {
    throw "Anatomy geometry audit failed with exit code $($audit.ExitCode)."
}

$reconstructionShaAfter = Sha256 $reconstruction
if ($reconstructionShaAfter -ne $reconstructionShaBefore) {
    throw "Retained reconstruction authority changed during anatomy audit."
}
if (-not (Test-Path -LiteralPath $OutputFile -PathType Leaf)) {
    throw "Anatomy geometry audit did not publish its JSON evidence."
}
try { $evidence = Get-Content -LiteralPath $OutputFile -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Anatomy geometry audit JSON evidence is unreadable." }
if ([string]$evidence.format -ne "bodyrig-anatomy-geometry-audit" -or [int]$evidence.version -ne 1) {
    throw "Anatomy geometry audit JSON evidence has an unexpected contract."
}
if ([string]$evidence.donorObjSha256 -ne $donorSha -or [string]$evidence.sourceObjSha256 -ne $sourceSha) {
    throw "Anatomy geometry audit JSON evidence does not bind the retained OBJ bytes."
}
if ($evidence.humanReviewRequired -ne $true) {
    throw "Anatomy geometry audit incorrectly removed human review authority."
}

Write-Host ""
Write-Host "Evidence:       $OutputFile"
Write-Host "Gross anatomy:  $([bool]$evidence.grossAnatomyPass)"
Write-Host "Human review:   REQUIRED"
Write-Host "Production:     FALSE"
Write-Host "SiTH rerun:     FALSE"

if ($audit.ExitCode -eq 2 -or $evidence.grossAnatomyPass -ne $true) {
    Write-Host "BodyRig retained anatomy audit: GROSS MISMATCH"
    exit 2
}
Write-Host "BodyRig retained anatomy audit: GROSS PASS (human anatomy review still required)"
exit 0
