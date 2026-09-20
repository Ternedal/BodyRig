param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
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
function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
    catch { throw "$Label is unreadable JSON: $Path" }
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath (Need-File -Path $Path -Label "Hash input") -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Test-V1Version($Value) {
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }
}
function Invoke-CheckedScript {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][hashtable]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )
    & $Script @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig retained hair+eye runtime build is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Retained hair+eye runtime build requires an exact clean BodyRig checkout."
}

$PackagePath = Need-File -Path $PackagePath -Label "Retained candidate package"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$stage = Need-Directory -Path (Join-Path $IdentityWorkspace "sith-input-v1") -Label "Retained SiTH input"
$reconstructionPath = Need-File -Path (Join-Path $stage "reconstruction.json") -Label "Retained reconstruction evidence"
$authorityPath = Need-File -Path (Join-Path $stage "reconstruction-authority.json") -Label "Retained reconstruction authority"
$donorObj = Need-File -Path (Join-Path $stage "smplx\000_smplx.obj") -Label "Retained fitted donor OBJ"

$authority = Read-Json -Path $authorityPath -Label "Retained reconstruction authority"
if ([string]$authority.format -ne "bodyrig-sith-reconstruction-authority" -or -not (Test-V1Version $authority.version)) {
    throw "Retained reconstruction authority format/version mismatch."
}
$targetFamily = ([string]$authority.body_model_gender).Trim().ToLowerInvariant()
if ($targetFamily -notin @("female","male","neutral")) {
    throw "Retained reconstruction target model family is invalid: $targetFamily"
}
$reconstructionSha = Sha256 $reconstructionPath
if ([string]$authority.reconstruction_sha256 -ne $reconstructionSha) {
    throw "Retained reconstruction authority no longer binds reconstruction.json."
}
$packageSha = Sha256 $PackagePath
$authoritySha = Sha256 $authorityPath
$donorSha = Sha256 $donorObj

$hairScript = Need-File -Path (Join-Path $repoRoot "extract-retained-hair.ps1") -Label "Retained hair extraction operator"
$eyeScript = Need-File -Path (Join-Path $repoRoot "extract-eye-components.ps1") -Label "Eye geometry extraction operator"
$eyeAppearanceScript = Need-File -Path (Join-Path $repoRoot "extract-eye-appearance.ps1") -Label "Eye appearance extraction operator"
$runtimeScript = Need-File -Path (Join-Path $repoRoot "build-source-hair-eye-review-runtime.ps1") -Label "Hair+eye runtime operator"

$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Retained hair+eye runtime output already exists: $OutputDir" }
$parent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($parent)) { throw "OutputDir must have a parent directory." }
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$attempt = Join-Path $parent ("." + [IO.Path]::GetFileName($OutputDir) + ".partial-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attempt | Out-Null
$committed = $false

try {
    $hairDir = Join-Path $attempt "hair"
    $eyeDir = Join-Path $attempt "eyes"
    $appearanceDir = Join-Path $attempt "eye-appearance"
    $runtimeDir = Join-Path $attempt "runtime"

    $common = @{
        Distribution = $Distribution
        InstallRoot = $InstallRoot
        WslExe = $WslExe
    }

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "BODYRIG RETAINED HAIR + EYE RUNTIME BUILD"
    Write-Host "Revision:          $head"
    Write-Host "Package SHA:       $packageSha"
    Write-Host "Reconstruction:    $reconstructionSha"
    Write-Host "Target family:     $targetFamily"
    Write-Host "Intermediate render: SKIPPED"
    Write-Host "SiTH rerun:        FALSE"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"

    Write-Host ""
    Write-Host "=== 1/4 SOURCE HAIR ==="
    $hairArgs = $common.Clone()
    $hairArgs.IdentityWorkspace = $IdentityWorkspace
    $hairArgs.DonorObj = $donorObj
    $hairArgs.OutputDir = $hairDir
    Invoke-CheckedScript -Script $hairScript -Arguments $hairArgs -Label "Retained hair extraction"

    Write-Host ""
    Write-Host "=== 2/4 EYE GEOMETRY ==="
    $eyeArgs = $common.Clone()
    $eyeArgs.DonorObj = $donorObj
    $eyeArgs.TargetFamily = $targetFamily
    $eyeArgs.OutputDir = $eyeDir
    Invoke-CheckedScript -Script $eyeScript -Arguments $eyeArgs -Label "Eye geometry extraction"

    Write-Host ""
    Write-Host "=== 3/4 EYE APPEARANCE ==="
    $appearanceArgs = $common.Clone()
    $appearanceArgs.IdentityWorkspace = $IdentityWorkspace
    $appearanceArgs.DonorObj = $donorObj
    $appearanceArgs.TargetFamily = $targetFamily
    $appearanceArgs.OutputDir = $appearanceDir
    Invoke-CheckedScript -Script $eyeAppearanceScript -Arguments $appearanceArgs -Label "Eye appearance extraction"

    Write-Host ""
    Write-Host "=== 4/4 COMPOSE HAIR + EYE REVIEW RUNTIME ==="
    $runtimeArgs = $common.Clone()
    $runtimeArgs.PackagePath = $PackagePath
    $runtimeArgs.HairCandidateDir = $hairDir
    $runtimeArgs.EyeGeometryDir = $eyeDir
    $runtimeArgs.EyeAppearanceDir = $appearanceDir
    $runtimeArgs.CandidateWorkspace = $IdentityWorkspace
    $runtimeArgs.OutputDir = $runtimeDir
    Invoke-CheckedScript -Script $runtimeScript -Arguments $runtimeArgs -Label "Hair+eye runtime composition"

    $receiptPath = Need-File -Path (Join-Path $runtimeDir "source-hair-eye-review-runtime.json") -Label "Hair+eye runtime receipt"
    $vrmPath = Need-File -Path (Join-Path $runtimeDir "source-hair-eye-review.vrm") -Label "Hair+eye review VRM"
    $receipt = Read-Json -Path $receiptPath -Label "Hair+eye runtime receipt"
    if ([string]$receipt.format -ne "bodyrig-source-hair-eye-review-runtime" -or
        -not (Test-V1Version $receipt.version) -or
        [string]$receipt.bodyrigRevision -ne $head -or
        [string]$receipt.packageSha256 -ne $packageSha -or
        [string]$receipt.reviewVrmSha256 -ne (Sha256 $vrmPath) -or
        $receipt.sourceHairRuntimeApplied -ne $true -or
        $receipt.sourceEyeSurfaceApplied -ne $true -or
        [string]$receipt.cornealMaterialStatus -ne "runtime-applied" -or
        $receipt.comparisonOnly -ne $true -or
        $receipt.humanReviewRequired -ne $true -or
        $receipt.productionActivation -ne $false) {
        throw "Retained hair+eye runtime receipt violates the comparison-only authority boundary."
    }

    if ((Sha256 $PackagePath) -ne $packageSha -or
        (Sha256 $reconstructionPath) -ne $reconstructionSha -or
        (Sha256 $authorityPath) -ne $authoritySha -or
        (Sha256 $donorObj) -ne $donorSha) {
        throw "Retained package/reconstruction bytes changed during hair+eye runtime build."
    }

    $summary = [ordered]@{
        format = "bodyrig-retained-hair-eye-runtime-build"
        version = 1
        bodyrig_revision = $head
        package_sha256 = $packageSha
        reconstruction_sha256 = $reconstructionSha
        reconstruction_authority_sha256 = $authoritySha
        donor_obj_sha256 = $donorSha
        target_model_family = $targetFamily
        review_vrm_sha256 = Sha256 $vrmPath
        runtime_receipt_sha256 = Sha256 $receiptPath
        reconstruction_rerun = $false
        intermediate_render_skipped = $true
        comparison_only = $true
        human_review_required = $true
        production_activation = $false
    }
    $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $attempt "retained-hair-eye-runtime-build.json") -Encoding UTF8

    Move-Item -LiteralPath $attempt -Destination $OutputDir
    $committed = $true

    Write-Host ""
    Write-Host "RETAINED HAIR + EYE RUNTIME: READY"
    Write-Host "Runtime:          $(Join-Path $OutputDir 'runtime')"
    Write-Host "Intermediate render: SKIPPED"
    Write-Host "SiTH rerun:       FALSE"
    Write-Host "Production:       FALSE"
    exit 0
}
finally {
    if (-not $committed -and (Test-Path -LiteralPath $attempt -PathType Container)) {
        Remove-Item -LiteralPath $attempt -Recurse -Force -ErrorAction SilentlyContinue
    }
}
