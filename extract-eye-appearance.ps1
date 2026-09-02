param(
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$DonorObj,
    [Parameter(Mandatory = $true)][ValidateSet("female", "male", "neutral")][string]$TargetFamily,
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
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Lines = $lines; Text = ($lines -join "`n").Trim() }
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
    throw "BodyRig eye appearance extraction is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Eye appearance extraction requires an exact clean BodyRig checkout." }

$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$DonorObj = Need-File -Path $DonorObj -Label "Subject donor OBJ"
$stage = Need-Directory -Path (Join-Path $IdentityWorkspace "sith-input-v1") -Label "Retained SiTH input"
$reconstruction = Need-File -Path (Join-Path $stage "reconstruction.json") -Label "Retained reconstruction authority"
$sourceMesh = Need-File -Path (Join-Path $stage "meshes\000_reco.obj") -Label "Retained source mesh"
try { $reconstructionValue = Get-Content -LiteralPath $reconstruction -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Retained reconstruction authority is unreadable." }
$textureName = [string]$reconstructionValue.reconstruction.mesh_texture_name
if ([string]::IsNullOrWhiteSpace($textureName) -or [IO.Path]::GetFileName($textureName) -ne $textureName) {
    throw "Retained reconstruction texture reference is invalid."
}
$sourceTexture = Need-File -Path (Join-Path $stage ("meshes\" + $textureName)) -Label "Retained source texture"
$extractScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_eye_appearance_extract.py") -Label "BodyRig eye appearance bridge"

$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Eye appearance output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Eye appearance output must have a parent directory." }
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
foreach ($probePath in @($venvPython, "$modelDir/SMPLX_$($TargetFamily.ToUpperInvariant()).npz", "$InstallRoot/data/smplx_uv.obj")) {
    $probe = Invoke-WslRaw -Arguments @("/usr/bin/test", "-f", $probePath)
    if ($probe.ExitCode -ne 0) { throw "Required eye appearance asset is missing: $probePath" }
}

$workspaceWsl = Convert-WindowsPathToWsl -Path $IdentityWorkspace
$donorWsl = Convert-WindowsPathToWsl -Path $DonorObj
$outputWsl = Convert-WindowsPathToWsl -Path $OutputDir
$scriptWsl = Convert-WindowsPathToWsl -Path $extractScript

$reconstructionShaBefore = Sha256 $reconstruction
$sourceMeshShaBefore = Sha256 $sourceMesh
$sourceTextureShaBefore = Sha256 $sourceTexture
$donorShaBefore = Sha256 $DonorObj

Write-Host "BodyRig source-derived eye appearance discovery"
Write-Host "Revision:       $head"
Write-Host "Target family:  $TargetFamily"
Write-Host "Donor SHA:      $donorShaBefore"
Write-Host "Reconstruction: $reconstructionShaBefore"
Write-Host "Source texture: $sourceTextureShaBefore"
Write-Host "Iris identity:  REVIEW-PENDING"
Write-Host "Production:     FALSE"
Write-Host "SiTH rerun:     FALSE"
Write-Host ""

$run = Invoke-WslRaw -Arguments @(
    $venvPython,
    $scriptWsl,
    "--workspace", $workspaceWsl,
    "--donor-obj", $donorWsl,
    "--sith-repo", $InstallRoot,
    "--smplx-model-dir", $modelDir,
    "--target-family", $TargetFamily,
    "--output-dir", $outputWsl
)
foreach ($line in $run.Lines) { Write-Host ([string]$line) }
if ($run.ExitCode -ne 0) { throw "Eye appearance extraction failed with exit code $($run.ExitCode)." }

if ((Sha256 $reconstruction) -ne $reconstructionShaBefore -or
    (Sha256 $sourceMesh) -ne $sourceMeshShaBefore -or
    (Sha256 $sourceTexture) -ne $sourceTextureShaBefore -or
    (Sha256 $DonorObj) -ne $donorShaBefore) {
    throw "Retained source/donor bytes changed during eye appearance discovery."
}

$evidencePath = Need-File -Path (Join-Path $OutputDir "eye-appearance-candidate.json") -Label "Eye appearance evidence"
$bakePath = Need-File -Path (Join-Path $OutputDir "canonical_eye_source_bake.png") -Label "Canonical eye source bake"
$leftPath = Need-File -Path (Join-Path $OutputDir "left_eye_appearance.png") -Label "Left eye appearance crop"
$rightPath = Need-File -Path (Join-Path $OutputDir "right_eye_appearance.png") -Label "Right eye appearance crop"
try { $evidence = Get-Content -LiteralPath $evidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Eye appearance evidence is unreadable." }

if ([string]$evidence.format -ne "bodyrig-eye-appearance-candidate" -or [int]$evidence.version -ne 1 -or
    [string]$evidence.targetModelFamily -ne $TargetFamily -or
    [string]$evidence.donorObjSha256 -ne $donorShaBefore -or
    [string]$evidence.sourceReconstructionSha256 -ne $reconstructionShaBefore -or
    [string]$evidence.sourceMeshSha256 -ne $sourceMeshShaBefore -or
    [string]$evidence.sourceTextureSha256 -ne $sourceTextureShaBefore -or
    [string]$evidence.canonicalBakeSha256 -ne (Sha256 $bakePath) -or
    [string]$evidence.leftEyeAppearancePngSha256 -ne (Sha256 $leftPath) -or
    [string]$evidence.rightEyeAppearancePngSha256 -ne (Sha256 $rightPath) -or
    $evidence.sourceDerivedEyeSurfaceAppearance -ne $true -or
    $evidence.irisIdentityIsolated -ne $false -or
    [string]$evidence.irisAppearanceStatus -ne "review-pending" -or
    [string]$evidence.cornealMaterialStatus -ne "missing" -or
    [string]$evidence.eyelashStatus -ne "missing" -or
    [string]$evidence.componentStatus -ne "partial" -or
    $evidence.bodyTopologyModified -ne $false -or
    $evidence.generativeIdentitySynthesis -ne $false -or
    $evidence.comparisonOnly -ne $true -or
    $evidence.humanReviewRequired -ne $true -or
    $evidence.productionReady -ne $false) {
    throw "Eye appearance evidence violates the high-fidelity authority boundary."
}

Write-Host ""
Write-Host "BodyRig eye appearance discovery: PARTIAL CANDIDATE PASS"
Write-Host "Left crop:      $leftPath"
Write-Host "Right crop:     $rightPath"
Write-Host "Left mask px:   $([int]$evidence.leftMaskPixelCount)"
Write-Host "Right mask px:  $([int]$evidence.rightMaskPixelCount)"
Write-Host "Iris identity:  REVIEW-PENDING"
Write-Host "Cornea:         MISSING"
Write-Host "Eyelashes:      MISSING"
Write-Host "Human review:   REQUIRED"
Write-Host "Production:     FALSE"
Write-Host "SiTH rerun:     FALSE"
exit 0
