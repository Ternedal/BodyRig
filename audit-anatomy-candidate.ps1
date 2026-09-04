param(
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$CandidateDonorObj,
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
    throw "BodyRig anatomy candidate audit is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Anatomy candidate audit requires an exact clean BodyRig checkout." }

$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Identity workspace"
$stage = Need-Directory -Path (Join-Path $IdentityWorkspace "sith-input-v1") -Label "Retained SiTH input"
$reconstruction = Need-File -Path (Join-Path $stage "reconstruction.json") -Label "Retained reconstruction authority"
$sourceObj = Need-File -Path (Join-Path $stage "meshes\000_reco.obj") -Label "Retained SiTH source mesh"
$CandidateDonorObj = Need-File -Path $CandidateDonorObj -Label "Candidate donor OBJ"
$auditScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_anatomy_geometry_audit.py") -Label "BodyRig anatomy audit bridge"

$OutputFile = [IO.Path]::GetFullPath($OutputFile)
if (Test-Path -LiteralPath $OutputFile) { throw "Anatomy candidate audit output already exists: $OutputFile" }
$outputParent = Split-Path -Parent $OutputFile
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Anatomy candidate audit output must have a parent directory." }
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

$donorWsl = Convert-WindowsPathToWsl -Path $CandidateDonorObj
$sourceWsl = Convert-WindowsPathToWsl -Path $sourceObj
$outputWsl = Convert-WindowsPathToWsl -Path $OutputFile
$scriptWsl = Convert-WindowsPathToWsl -Path $auditScript

$reconstructionShaBefore = Sha256 $reconstruction
$sourceShaBefore = Sha256 $sourceObj
$donorSha = Sha256 $CandidateDonorObj

Write-Host "BodyRig anatomy candidate audit"
Write-Host "Revision:       $head"
Write-Host "Reconstruction: $reconstructionShaBefore"
Write-Host "Candidate OBJ:  $donorSha"
Write-Host "Source OBJ:     $sourceShaBefore"
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
if ($audit.ExitCode -notin @(0, 2)) { throw "Anatomy candidate audit failed with exit code $($audit.ExitCode)." }

if ((Sha256 $reconstruction) -ne $reconstructionShaBefore -or (Sha256 $sourceObj) -ne $sourceShaBefore) {
    throw "Retained reconstruction/source bytes changed during anatomy candidate audit."
}
if (-not (Test-Path -LiteralPath $OutputFile -PathType Leaf)) { throw "Anatomy candidate audit did not publish JSON evidence." }
try { $evidence = Get-Content -LiteralPath $OutputFile -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Anatomy candidate audit JSON evidence is unreadable." }
if ([string]$evidence.format -ne "bodyrig-anatomy-geometry-audit" -or [int]$evidence.version -ne 1) {
    throw "Anatomy candidate audit JSON evidence has an unexpected contract."
}
if ([string]$evidence.donorObjSha256 -ne $donorSha -or [string]$evidence.sourceObjSha256 -ne $sourceShaBefore) {
    throw "Anatomy candidate audit evidence does not bind candidate/source bytes."
}
if ($evidence.humanReviewRequired -ne $true) { throw "Anatomy candidate audit incorrectly removed human review authority." }

Write-Host ""
Write-Host "Evidence:       $OutputFile"
Write-Host "Gross anatomy:  $([bool]$evidence.grossAnatomyPass)"
Write-Host "Human review:   REQUIRED"
Write-Host "Production:     FALSE"
Write-Host "SiTH rerun:     FALSE"

if ($audit.ExitCode -eq 2 -or $evidence.grossAnatomyPass -ne $true) {
    Write-Host "BodyRig anatomy candidate audit: GROSS MISMATCH"
    exit 2
}
Write-Host "BodyRig anatomy candidate audit: GROSS PASS (human anatomy review still required)"
exit 0
