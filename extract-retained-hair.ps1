param(
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$DonorObj,
    [Parameter(Mandatory = $true)][string]$OutputDir,
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
    throw "BodyRig retained hair extraction is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Retained hair extraction requires an exact clean BodyRig checkout." }

$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$reconstruction = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\reconstruction.json") -Label "Retained reconstruction authority"
$sourceMesh = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\meshes\000_reco.obj") -Label "Retained SiTH source mesh"
$DonorObj = Need-File -Path $DonorObj -Label "Hair extraction donor OBJ"
$extractScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_source_hair_extract.py") -Label "BodyRig source hair extraction bridge"

$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Hair extraction output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Hair extraction output must have a parent directory." }
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

$workspaceWsl = Convert-WindowsPathToWsl -Path $IdentityWorkspace
$donorWsl = Convert-WindowsPathToWsl -Path $DonorObj
$outputWsl = Convert-WindowsPathToWsl -Path $OutputDir
$scriptWsl = Convert-WindowsPathToWsl -Path $extractScript
$reconstructionShaBefore = Sha256 $reconstruction
$sourceShaBefore = Sha256 $sourceMesh

Write-Host "BodyRig retained source hair extraction"
Write-Host "Revision:       $head"
Write-Host "Reconstruction: $reconstructionShaBefore"
Write-Host "Source mesh:    $sourceShaBefore"
Write-Host "Donor OBJ:      $(Sha256 $DonorObj)"
Write-Host "SiTH rerun:     FALSE"
Write-Host "Production:     FALSE"
Write-Host ""

$run = Invoke-WslRaw -Arguments @(
    $venvPython,
    $scriptWsl,
    "--workspace", $workspaceWsl,
    "--donor-obj", $donorWsl,
    "--output-dir", $outputWsl
)
foreach ($line in $run.Lines) { Write-Host ([string]$line) }
if ($run.ExitCode -ne 0) { throw "Source hair extraction failed with exit code $($run.ExitCode)." }

if ((Sha256 $reconstruction) -ne $reconstructionShaBefore -or (Sha256 $sourceMesh) -ne $sourceShaBefore) {
    throw "Retained reconstruction/source bytes changed during hair extraction."
}
$evidencePath = Need-File -Path (Join-Path $OutputDir "source-hair-candidate.json") -Label "Source hair candidate evidence"
$hairObj = Need-File -Path (Join-Path $OutputDir "hair_source.obj") -Label "Source-derived hair OBJ"
try { $evidence = Get-Content -LiteralPath $evidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Source hair candidate evidence is unreadable." }
if ([string]$evidence.format -ne "bodyrig-source-hair-candidate" -or [int]$evidence.version -ne 1 -or
    $evidence.sourceDerived -ne $true -or $evidence.generativeGeometry -ne $false -or
    $evidence.bodyTopologyModified -ne $false -or $evidence.comparisonOnly -ne $true -or
    $evidence.humanReviewRequired -ne $true -or $evidence.productionReady -ne $false) {
    throw "Source hair candidate evidence violates the high-fidelity authority boundary."
}
if ([string]$evidence.sourceReconstructionSha256 -ne $reconstructionShaBefore -or
    [string]$evidence.sourceMeshSha256 -ne $sourceShaBefore -or
    [string]$evidence.hairObjSha256 -ne (Sha256 $hairObj)) {
    throw "Source hair candidate evidence does not bind exact retained/output bytes."
}

Write-Host ""
Write-Host "BodyRig retained source hair extraction: CANDIDATE PASS"
Write-Host "Hair OBJ:       $hairObj"
Write-Host "Faces:          $([int]$evidence.selectedFaceCount)"
Write-Host "Vertices:       $([int]$evidence.selectedVertexCount)"
Write-Host "Distance p95:   $([double]$evidence.sourceToDonorDistanceP95)"
Write-Host "Binding:        head-accessory review only"
Write-Host "Human review:   REQUIRED"
Write-Host "Production:     FALSE"
Write-Host "SiTH rerun:     FALSE"
exit 0
