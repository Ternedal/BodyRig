param(
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$DonorObj,
    [Parameter(Mandatory = $true)][string]$OutputFile,
    [Parameter(Mandatory = $true)][ValidateSet("female", "male", "neutral")][string]$Gender,
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
    throw "BodyRig exact anatomy bake scorer is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Exact anatomy bake scoring requires an exact clean BodyRig checkout." }

$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Identity workspace"
$DonorObj = Need-File -Path $DonorObj -Label "Donor OBJ"
$scoreScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_exact_anatomy_bake_score.py") -Label "Exact anatomy bake scoring bridge"

$OutputFile = [IO.Path]::GetFullPath($OutputFile)
if (Test-Path -LiteralPath $OutputFile) { throw "Exact anatomy bake score output already exists: $OutputFile" }
$outputParent = Split-Path -Parent $OutputFile
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Exact anatomy bake score output must have a parent directory." }
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
$familyLeaf = switch ($Gender) {
    "female" { "SMPLX_FEMALE.npz" }
    "male" { "SMPLX_MALE.npz" }
    default { "SMPLX_NEUTRAL.npz" }
}
foreach ($probePath in @($venvPython, "$InstallRoot/data/smplx_uv.obj", "$modelDir/$familyLeaf")) {
    $probe = Invoke-WslRaw -Arguments @("/usr/bin/test", "-f", $probePath)
    if ($probe.ExitCode -ne 0) { throw "Required exact anatomy bake scoring asset is missing: $probePath" }
}

$workspaceWsl = Convert-WindowsPathToWsl -Path $IdentityWorkspace
$donorWsl = Convert-WindowsPathToWsl -Path $DonorObj
$outputWsl = Convert-WindowsPathToWsl -Path $OutputFile
$scriptWsl = Convert-WindowsPathToWsl -Path $scoreScript

$reconstruction = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\reconstruction.json") -Label "Retained reconstruction authority"
$sourceObj = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\meshes\000_reco.obj") -Label "Retained source OBJ"
$reconstructionShaBefore = Sha256 $reconstruction
$sourceShaBefore = Sha256 $sourceObj
$donorShaBefore = Sha256 $DonorObj

Write-Host "BodyRig exact anatomy bake score"
Write-Host "Revision:       $head"
Write-Host "Gender:         $Gender"
Write-Host "Donor OBJ:      $donorShaBefore"
Write-Host "Reconstruction: $reconstructionShaBefore"
Write-Host "Source OBJ:     $sourceShaBefore"
Write-Host "Resolution:     1024x1024 (production)"
Write-Host "Mode:           read-only comparison"
Write-Host "SiTH rerun:     FALSE"
Write-Host ""

$run = Invoke-WslRaw -Arguments @(
    $venvPython,
    $scriptWsl,
    "--sith-repo", $InstallRoot,
    "--smplx-model-dir", $modelDir,
    "--bodyrig-workspace", $workspaceWsl,
    "--donor-obj", $donorWsl,
    "--gender", $Gender,
    "--output-file", $outputWsl
)
foreach ($line in $run.Lines) { Write-Host ([string]$line) }
if ($run.ExitCode -ne 0) { throw "Exact anatomy bake scoring failed with exit code $($run.ExitCode)." }

if ((Sha256 $reconstruction) -ne $reconstructionShaBefore -or
    (Sha256 $sourceObj) -ne $sourceShaBefore -or
    (Sha256 $DonorObj) -ne $donorShaBefore) {
    throw "Read-only exact anatomy bake scoring changed retained or donor bytes."
}

$OutputFile = Need-File -Path $OutputFile -Label "Exact anatomy bake score evidence"
try { $evidence = Get-Content -LiteralPath $OutputFile -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Exact anatomy bake score evidence is unreadable." }
if ([string]$evidence.format -ne "bodyrig-exact-anatomy-bake-score" -or [int]$evidence.version -ne 1) {
    throw "Exact anatomy bake score evidence has an unexpected contract."
}
if ($evidence.exactProductionBakePath -ne $true -or $evidence.comparisonOnly -ne $true -or
    $evidence.humanReviewRequired -ne $true -or $evidence.humanFidelityPass -ne $false -or
    $evidence.productionReady -ne $false -or $evidence.reconstructionRerun -ne $false) {
    throw "Exact anatomy bake score returned an invalid authority boundary."
}
if ([string]$evidence.donorSha256 -ne $donorShaBefore -or [string]$evidence.reconstructionSha256 -ne $reconstructionShaBefore) {
    throw "Exact anatomy bake score evidence does not bind scoring inputs."
}

$m = $evidence.metrics
Write-Host ""
Write-Host "Evidence:       $OutputFile"
Write-Host "P95/body:       $([double]$m.surface_distance_p95_body_ratio)"
Write-Host "Max/body:       $([double]$m.surface_distance_max_body_ratio)"
Write-Host "Normal mean:    $([double]$m.normal_alignment_mean)"
Write-Host "Normal p05:     $([double]$m.normal_alignment_p05)"
Write-Host "Low alignment:  $([double]$m.normal_low_alignment_ratio)"
Write-Host "Retry ratio:    $([double]$m.normal_retry_texel_ratio)"
Write-Host "Human review:   REQUIRED"
Write-Host "Production:     FALSE"
Write-Host "SiTH rerun:     FALSE"
Write-Host "BodyRig exact anatomy bake score: PASS (diagnostic only)"
exit 0
