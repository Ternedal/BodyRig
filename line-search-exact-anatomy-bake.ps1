param(
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$EndpointRefitDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][ValidateSet("female", "male", "neutral")][string]$Gender,
    [string]$Alphas = "",
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
    throw "BodyRig exact-bake anatomy line search is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Exact-bake anatomy line search requires an exact clean BodyRig checkout." }

$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Identity workspace"
$EndpointRefitDir = Need-Directory -Path $EndpointRefitDir -Label "V3 endpoint refit directory"
$retainedFit = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\smplx\000_fit.json") -Label "Retained SMPL-X fit"
$retainedDonor = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\smplx\000_smplx.obj") -Label "Retained SMPL-X donor"
$reconstruction = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\reconstruction.json") -Label "Retained reconstruction authority"
$sourceObj = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\meshes\000_reco.obj") -Label "Retained source OBJ"
$endpointFit = Need-File -Path (Join-Path $EndpointRefitDir "subject_fit.json") -Label "V3 endpoint fit"
$endpointDonor = Need-File -Path (Join-Path $EndpointRefitDir "subject_smplx.obj") -Label "V3 endpoint donor"
$endpointEvidence = Need-File -Path (Join-Path $EndpointRefitDir "subject-anatomy-refit.json") -Label "V3 endpoint evidence"
$lineSearchScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_subject_anatomy_line_search.py") -Label "Exact-bake anatomy line-search bridge"
$scoreScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_exact_anatomy_bake_score.py") -Label "Exact production bake scoring bridge"

$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Exact-bake anatomy line-search output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Exact-bake anatomy line-search output must have a parent directory." }
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
    if ($probe.ExitCode -ne 0) { throw "Required exact-bake anatomy line-search asset is missing: $probePath" }
}

$workspaceWsl = Convert-WindowsPathToWsl -Path $IdentityWorkspace
$endpointWsl = Convert-WindowsPathToWsl -Path $EndpointRefitDir
$outputWsl = Convert-WindowsPathToWsl -Path $OutputDir
$scriptWsl = Convert-WindowsPathToWsl -Path $lineSearchScript

$authorityFiles = @($reconstruction, $sourceObj, $retainedFit, $retainedDonor, $endpointFit, $endpointDonor, $endpointEvidence)
$before = @{}
foreach ($path in $authorityFiles) { $before[$path] = Sha256 $path }

Write-Host "BodyRig exact production-bake anatomy line search"
Write-Host "Revision:       $head"
Write-Host "Gender:         $Gender"
Write-Host "Retained donor: $($before[$retainedDonor])"
Write-Host "Endpoint donor: $($before[$endpointDonor])"
Write-Host "Endpoint:       V3 comparison-only refit"
Write-Host "Interpolation:  betas linear | translation linear | scale log-linear"
Write-Host "Scoring:        exact 1024x1024 production anatomy bake"
Write-Host "Mode:           bounded comparison only"
Write-Host "SiTH rerun:     FALSE"
Write-Host ""

$arguments = @(
    $venvPython,
    $scriptWsl,
    "--sith-repo", $InstallRoot,
    "--smplx-model-dir", $modelDir,
    "--bodyrig-workspace", $workspaceWsl,
    "--endpoint-dir", $endpointWsl,
    "--output-dir", $outputWsl,
    "--gender", $Gender
)
if (-not [string]::IsNullOrWhiteSpace($Alphas)) {
    $arguments += @("--alphas", $Alphas)
}
$run = Invoke-WslRaw -Arguments $arguments
foreach ($line in $run.Lines) { Write-Host ([string]$line) }
if ($run.ExitCode -ne 0) { throw "Exact-bake anatomy line search failed with exit code $($run.ExitCode)." }

foreach ($path in $authorityFiles) {
    if ((Sha256 $path) -ne $before[$path]) {
        throw "Exact-bake anatomy line search changed retained or endpoint authority bytes: $path"
    }
}

$summaryPath = Need-File -Path (Join-Path $OutputDir "line-search.json") -Label "Exact-bake anatomy line-search evidence"
try { $evidence = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
catch { throw "Exact-bake anatomy line-search evidence is unreadable." }
if ([string]$evidence.format -ne "bodyrig-subject-anatomy-exact-bake-line-search" -or [int]$evidence.version -ne 1) {
    throw "Exact-bake anatomy line-search evidence has an unexpected contract."
}
if ($evidence.exactProductionBakePath -ne $true -or $evidence.comparisonOnly -ne $true -or
    $evidence.humanReviewRequired -ne $true -or $evidence.humanFidelityPass -ne $false -or
    $evidence.productionReady -ne $false -or $evidence.reconstructionRerun -ne $false) {
    throw "Exact-bake anatomy line search returned an invalid authority boundary."
}
if ([string]$evidence.retainedSmplxObjSha256 -ne $before[$retainedDonor] -or
    [string]$evidence.endpointSmplxObjSha256 -ne $before[$endpointDonor]) {
    throw "Exact-bake anatomy line-search evidence does not bind geometry endpoints."
}

Write-Host ""
Write-Host "========== EXACT PRODUCTION BAKE LINE SEARCH =========="
$rows = foreach ($row in $evidence.rows) {
    [pscustomobject]@{
        Alpha      = [math]::Round([double]$row.alpha, 4)
        P95BodyPct = [math]::Round([double]$row.surface_distance_p95_body_ratio * 100, 4)
        MaxBodyPct = [math]::Round([double]$row.surface_distance_max_body_ratio * 100, 4)
        NormalMean = [math]::Round([double]$row.normal_alignment_mean, 6)
        NormalP05  = [math]::Round([double]$row.normal_alignment_p05, 6)
        LowPct     = [math]::Round([double]$row.normal_low_alignment_ratio * 100, 3)
        RetryPct   = [math]::Round([double]$row.normal_retry_texel_ratio * 100, 3)
    }
}
$rows | Format-Table -AutoSize
Write-Host ""
Write-Host "Evidence:       $summaryPath"
Write-Host "Human review:   REQUIRED"
Write-Host "Production:     FALSE"
Write-Host "SiTH rerun:     FALSE"
Write-Host "BodyRig exact production-bake anatomy line search: PASS (comparison only)"
exit 0
