param(
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
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
    throw "BodyRig subject anatomy v3 refit is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Subject anatomy v3 refit requires an exact clean BodyRig checkout." }

$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Identity workspace"
$stage = Need-Directory -Path (Join-Path $IdentityWorkspace "sith-input-v1") -Label "Retained SiTH input"
$reconstruction = Need-File -Path (Join-Path $stage "reconstruction.json") -Label "Retained reconstruction authority"
$sourceObj = Need-File -Path (Join-Path $stage "meshes\000_reco.obj") -Label "Retained SiTH source mesh"
$retainedFit = Need-File -Path (Join-Path $stage "smplx\000_fit.json") -Label "Retained SMPL-X fit params"
$retainedDonor = Need-File -Path (Join-Path $stage "smplx\000_smplx.obj") -Label "Retained fitted SMPL-X OBJ"
$refitScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_subject_anatomy_refit_v3.py") -Label "BodyRig subject anatomy v3 bridge"

$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Subject anatomy v3 refit output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Subject anatomy v3 output must have a parent directory." }
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null

$WslExeResolved = Get-Command $WslExe -ErrorAction SilentlyContinue
if ($null -eq $WslExeResolved) { throw "WSL executable not found: $WslExe" }
$WslExe = $WslExeResolved.Source
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $wslHome = Invoke-WslRaw -Arguments @("/usr/bin/python3", "-c", "import pathlib; print(pathlib.Path.home().as_posix())")
    if ($wslHome.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($wslHome.Text)) {
        throw "Could not resolve WSL home directory: $($wslHome.Text)"
    }
    $InstallRoot = "$($wslHome.Text.Trim())/.local/share/bodyrig/sith"
}
if (-not $InstallRoot.StartsWith("/")) { throw "-InstallRoot must be an absolute Linux path." }
$InstallRoot = $InstallRoot.TrimEnd("/")
$venvPython = "$InstallRoot/.bodyrig-venv/bin/python"
$modelDir = "$InstallRoot/data/body_models/smplx"
$familyLeaf = switch ($TargetFamily) {
    "female" { "SMPLX_FEMALE.npz" }
    "male" { "SMPLX_MALE.npz" }
    default { "SMPLX_NEUTRAL.npz" }
}
foreach ($probePath in @($venvPython, "$modelDir/$familyLeaf", "$InstallRoot/recon/models/ops/mesh/closest_point.py", "$InstallRoot/recon/models/ops/mesh/per_face_normals.py")) {
    $probe = Invoke-WslRaw -Arguments @("/usr/bin/test", "-f", $probePath)
    if ($probe.ExitCode -ne 0) { throw "Required subject anatomy v3 asset is missing: $probePath" }
}

$workspaceWsl = Convert-WindowsPathToWsl -Path $IdentityWorkspace
$outputWsl = Convert-WindowsPathToWsl -Path $OutputDir
$scriptWsl = Convert-WindowsPathToWsl -Path $refitScript

$reconstructionShaBefore = Sha256 $reconstruction
$sourceShaBefore = Sha256 $sourceObj
$fitShaBefore = Sha256 $retainedFit
$donorShaBefore = Sha256 $retainedDonor

Write-Host "BodyRig subject anatomy refit v3"
Write-Host "Revision:       $head"
Write-Host "Target family:  $TargetFamily"
Write-Host "Reconstruction: $reconstructionShaBefore"
Write-Host "Source OBJ:     $sourceShaBefore"
Write-Host "Retained fit:   $fitShaBefore"
Write-Host "Retained donor: $donorShaBefore"
Write-Host "Normal authority: SiTH closest source triangle + face normal"
Write-Host "Mode:           comparison-only"
Write-Host "SiTH rerun:     FALSE"
Write-Host ""

$run = Invoke-WslRaw -Arguments @(
    $venvPython,
    $scriptWsl,
    "--sith-repo", $InstallRoot,
    "--smplx-model-dir", $modelDir,
    "--bodyrig-workspace", $workspaceWsl,
    "--target-family", $TargetFamily,
    "--output-dir", $outputWsl
)
foreach ($line in $run.Lines) { Write-Host ([string]$line) }
if ($run.ExitCode -ne 0) { throw "Subject anatomy v3 refit failed with exit code $($run.ExitCode)." }

if ((Sha256 $reconstruction) -ne $reconstructionShaBefore -or
    (Sha256 $sourceObj) -ne $sourceShaBefore -or
    (Sha256 $retainedFit) -ne $fitShaBefore -or
    (Sha256 $retainedDonor) -ne $donorShaBefore) {
    throw "Retained SiTH reconstruction bytes changed during subject anatomy v3 refit."
}

$evidencePath = Need-File -Path (Join-Path $OutputDir "subject-anatomy-refit.json") -Label "Subject anatomy v3 evidence"
$derivedObj = Need-File -Path (Join-Path $OutputDir "subject_smplx.obj") -Label "Derived subject SMPL-X OBJ"
$derivedFit = Need-File -Path (Join-Path $OutputDir "subject_fit.json") -Label "Derived subject fit params"
try { $evidence = Get-Content -LiteralPath $evidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Subject anatomy v3 evidence is unreadable." }

$expectedMethod = "explicit-family-smplx-betas-icp-bake-surface-normal-aware-to-retained-sith-source-v3"
$expectedNormalAuthority = "sith-closest-source-triangle-face-normal-v1"
$expectedSampleMethod = "deterministic-smplx-face-centroids-v1"
if ([string]$evidence.format -ne "bodyrig-subject-anatomy-refit" -or [int]$evidence.version -ne 1 -or [string]$evidence.method -ne $expectedMethod) {
    throw "Subject anatomy v3 evidence has an unexpected contract."
}
if ([string]$evidence.targetModelFamily -ne $TargetFamily) { throw "Subject anatomy v3 target-family evidence mismatch." }
if ([string]$evidence.normalAlignmentAuthority -ne $expectedNormalAuthority -or [string]$evidence.normalSampleMethod -ne $expectedSampleMethod) {
    throw "Subject anatomy v3 normal authority evidence mismatch."
}
if ([int]$evidence.normalSampleCount -lt 100) { throw "Subject anatomy v3 normal sample evidence is invalid." }
if ($evidence.retainedReconstructionModified -ne $false -or $evidence.reconstructionRerun -ne $false -or
    $evidence.generativeGeometry -ne $false -or $evidence.comparisonOnly -ne $true -or
    $evidence.humanReviewRequired -ne $true -or $evidence.productionReady -ne $false) {
    throw "Subject anatomy v3 returned an invalid authority boundary."
}
if ([string]$evidence.derivedSmplxObjSha256 -ne (Sha256 $derivedObj) -or
    [string]$evidence.derivedFitParamsSha256 -ne (Sha256 $derivedFit)) {
    throw "Subject anatomy v3 evidence does not bind derived candidate bytes."
}

Write-Host ""
Write-Host "Evidence:       $evidencePath"
Write-Host "Derived OBJ:    $derivedObj"
Write-Host "Derived fit:    $derivedFit"
Write-Host "Initial p95:    $([double]$evidence.initialDonorToSourceP95)"
Write-Host "Final p95:      $([double]$evidence.finalDonorToSourceP95)"
Write-Host "Initial RMS:    $([double]$evidence.initialDonorToSourceRms)"
Write-Host "Final RMS:      $([double]$evidence.finalDonorToSourceRms)"
Write-Host "Initial normal mean: $([double]$evidence.initialNormalAlignmentMean)"
Write-Host "Final normal mean:   $([double]$evidence.finalNormalAlignmentMean)"
Write-Host "Initial normal p05:  $([double]$evidence.initialNormalAlignmentP05)"
Write-Host "Final normal p05:    $([double]$evidence.finalNormalAlignmentP05)"
Write-Host "Normal samples:      $([int]$evidence.normalSampleCount)"
Write-Host "Non-regression: $([bool]$evidence.fitDidNotRegress)"
Write-Host "Human review:   REQUIRED"
Write-Host "Production:     FALSE"
Write-Host "SiTH rerun:     FALSE"

if ($evidence.fitDidNotRegress -ne $true) {
    Write-Host "BodyRig subject anatomy refit v3: CANDIDATE REGRESSED (evidence preserved)"
    exit 2
}
Write-Host "BodyRig subject anatomy refit v3: CANDIDATE PASS (comparison only)"
exit 0
