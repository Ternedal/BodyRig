param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$WslExe = "wsl.exe",
    [switch]$SkipBuild
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
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40 }
    catch { throw "$Label is unreadable JSON: $Path" }
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
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
function Resolve-BodyRigPython {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$Requested)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { return Need-File -Path $Requested -Label "BodyRig Python" }
    $local = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $local -PathType Leaf) { return (Resolve-Path -LiteralPath $local).Path }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "BodyRig Python was not found." }
    return $command.Source
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig retained hair+eye preview is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Retained hair+eye preview requires an exact clean BodyRig checkout."
}

$PackagePath = Need-File -Path $PackagePath -Label "Candidate .mrbody package"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$BodyRigPython = Resolve-BodyRigPython -RepoRoot $repoRoot -Requested $BodyRigPython

$stage = Need-Directory -Path (Join-Path $IdentityWorkspace "sith-input-v1") -Label "Retained SiTH input"
$reconstructionPath = Need-File -Path (Join-Path $stage "reconstruction.json") -Label "Retained reconstruction evidence"
$reconstructionAuthorityPath = Need-File -Path (Join-Path $stage "reconstruction-authority.json") -Label "Retained reconstruction authority"
$sourceMeshPath = Need-File -Path (Join-Path $stage "meshes\000_reco.obj") -Label "Retained source mesh"
$donorObj = Need-File -Path (Join-Path $stage "smplx\000_smplx.obj") -Label "Retained fitted donor OBJ"
$fitParams = Need-File -Path (Join-Path $stage "smplx\000_fit.json") -Label "Retained fitted donor parameters"
$reconstructionAuthority = Read-Json -Path $reconstructionAuthorityPath -Label "Retained reconstruction authority"
if ([string]$reconstructionAuthority.format -ne "bodyrig-sith-reconstruction-authority" -or -not (Test-V1Version $reconstructionAuthority.version)) {
    throw "Retained reconstruction authority format/version mismatch."
}
$targetFamily = ([string]$reconstructionAuthority.body_model_gender).Trim().ToLowerInvariant()
if ($targetFamily -notin @("female", "male", "neutral")) {
    throw "Retained reconstruction target model family is invalid: $targetFamily"
}

$packageShaBefore = Sha256 $PackagePath
$reconstructionShaBefore = Sha256 $reconstructionPath
$reconstructionAuthorityShaBefore = Sha256 $reconstructionAuthorityPath
$sourceMeshShaBefore = Sha256 $sourceMeshPath
$donorShaBefore = Sha256 $donorObj
$fitShaBefore = Sha256 $fitParams
if ([string]$reconstructionAuthority.reconstruction_sha256 -ne $reconstructionShaBefore) {
    throw "Retained reconstruction authority no longer binds reconstruction.json."
}

$hairScript = Need-File -Path (Join-Path $repoRoot "extract-retained-hair.ps1") -Label "Source hair extraction operator"
$eyeScript = Need-File -Path (Join-Path $repoRoot "extract-eye-components.ps1") -Label "Eye geometry extraction operator"
$eyeAppearanceScript = Need-File -Path (Join-Path $repoRoot "extract-eye-appearance.ps1") -Label "Eye appearance extraction operator"
$runtimeScript = Need-File -Path (Join-Path $repoRoot "build-source-hair-eye-review-runtime.ps1") -Label "Hair+eye review runtime operator"
$previewScript = Need-File -Path (Join-Path $repoRoot "run-source-hair-eye-windows-preview.ps1") -Label "Hair+eye Windows preview operator"

$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) { throw "Retained hair+eye preview output already exists: $OutputRoot" }
$outputParent = Split-Path -Parent $OutputRoot
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Retained hair+eye preview output must have a parent directory." }
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
$attempt = Join-Path $outputParent ("." + [IO.Path]::GetFileName($OutputRoot) + ".partial-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attempt | Out-Null
$committed = $false

try {
    $hairDir = Join-Path $attempt "hair"
    $eyeDir = Join-Path $attempt "eyes"
    $eyeAppearanceDir = Join-Path $attempt "eye-appearance"
    $runtimeDir = Join-Path $attempt "runtime"
    $previewDir = Join-Path $attempt "windows-preview"

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "BODYRIG RETAINED HAIR + EYE PREVIEW"
    Write-Host "Revision:          $head"
    Write-Host "Package SHA:       $packageShaBefore"
    Write-Host "Reconstruction:    $reconstructionShaBefore"
    Write-Host "Target family:     $targetFamily"
    Write-Host "SiTH reconstruction rerun: FALSE"
    Write-Host "Production activation:     FALSE"
    Write-Host "============================================================"

    $common = @{
        Distribution = $Distribution
        InstallRoot = $InstallRoot
        WslExe = $WslExe
    }

    Write-Host ""
    Write-Host "=== 1/5 SOURCE HAIR FROM RETAINED RECONSTRUCTION ==="
    $hairArgs = $common.Clone()
    $hairArgs.IdentityWorkspace = $IdentityWorkspace
    $hairArgs.DonorObj = $donorObj
    $hairArgs.OutputDir = $hairDir
    Invoke-CheckedScript -Script $hairScript -Arguments $hairArgs -Label "Retained source hair extraction"

    Write-Host ""
    Write-Host "=== 2/5 EXPLICIT EYE GEOMETRY ==="
    $eyeArgs = $common.Clone()
    $eyeArgs.DonorObj = $donorObj
    $eyeArgs.TargetFamily = $targetFamily
    $eyeArgs.OutputDir = $eyeDir
    Invoke-CheckedScript -Script $eyeScript -Arguments $eyeArgs -Label "Retained eye geometry extraction"

    Write-Host ""
    Write-Host "=== 3/5 SOURCE-BAKED EYE APPEARANCE ==="
    $appearanceArgs = $common.Clone()
    $appearanceArgs.IdentityWorkspace = $IdentityWorkspace
    $appearanceArgs.DonorObj = $donorObj
    $appearanceArgs.TargetFamily = $targetFamily
    $appearanceArgs.OutputDir = $eyeAppearanceDir
    Invoke-CheckedScript -Script $eyeAppearanceScript -Arguments $appearanceArgs -Label "Retained eye appearance extraction"

    Write-Host ""
    Write-Host "=== 4/5 COMPOSE HAIR + EYE REVIEW RUNTIME ==="
    $runtimeArgs = $common.Clone()
    $runtimeArgs.PackagePath = $PackagePath
    $runtimeArgs.HairCandidateDir = $hairDir
    $runtimeArgs.EyeGeometryDir = $eyeDir
    $runtimeArgs.EyeAppearanceDir = $eyeAppearanceDir
    $runtimeArgs.CandidateWorkspace = $IdentityWorkspace
    $runtimeArgs.OutputDir = $runtimeDir
    Invoke-CheckedScript -Script $runtimeScript -Arguments $runtimeArgs -Label "Retained hair+eye runtime composition"

    $runtimeReceiptPath = Need-File -Path (Join-Path $runtimeDir "source-hair-eye-review-runtime.json") -Label "Hair+eye runtime receipt"
    $runtimeVrmPath = Need-File -Path (Join-Path $runtimeDir "source-hair-eye-review.vrm") -Label "Hair+eye review VRM"
    $runtimeReceipt = Read-Json -Path $runtimeReceiptPath -Label "Hair+eye runtime receipt"
    if ([string]$runtimeReceipt.format -ne "bodyrig-source-hair-eye-review-runtime" -or -not (Test-V1Version $runtimeReceipt.version) -or
        [string]$runtimeReceipt.bodyrigRevision -ne $head -or
        [string]$runtimeReceipt.reviewVrmSha256 -ne (Sha256 $runtimeVrmPath) -or
        $runtimeReceipt.sourceHairRuntimeApplied -ne $true -or $runtimeReceipt.sourceEyeSurfaceApplied -ne $true -or
        [string]$runtimeReceipt.irisAppearanceStatus -ne "review-pending" -or
        [string]$runtimeReceipt.cornealMaterialStatus -ne "runtime-applied" -or
        [string]$runtimeReceipt.eyelashStatus -ne "missing" -or
        $runtimeReceipt.comparisonOnly -ne $true -or $runtimeReceipt.humanReviewRequired -ne $true -or
        $runtimeReceipt.productionActivation -ne $false) {
        throw "Retained hair+eye runtime receipt crossed its comparison-only authority boundary."
    }

    Write-Host ""
    Write-Host "=== 5/5 WINDOWS PHYSICAL PREVIEW ==="
    $previewArgs = @{
        PackagePath = $PackagePath
        ReviewRuntimeDir = $runtimeDir
        OutputDir = $previewDir
        BodyRigPython = $BodyRigPython
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $previewArgs.UnityExe = $UnityExe }
    if ($SkipBuild) { $previewArgs.SkipBuild = $true }
    Invoke-CheckedScript -Script $previewScript -Arguments $previewArgs -Label "Retained hair+eye Windows preview"

    $comparisonPath = Need-File -Path (Join-Path $previewDir "comparison-authority.json") -Label "Preview comparison authority"
    $hairProbePath = Need-File -Path (Join-Path $previewDir "hair-deformation-probe.json") -Label "Hair deformation probe"
    $comparison = Read-Json -Path $comparisonPath -Label "Preview comparison authority"
    if ([string]$comparison.authority -ne "source-hair-eye-review-runtime" -or
        $comparison.source_hair_runtime_applied -ne $true -or
        $comparison.source_eye_surface_applied -ne $true -or
        [string]$comparison.corneal_material_status -ne "runtime-applied" -or
        $comparison.hair_deformation_machine_pass -ne $true -or
        $comparison.hair_deformation_human_review_required -ne $true -or
        $comparison.physical_acceptance_authority -ne $false -or
        $comparison.production_activation -ne $false) {
        throw "Retained hair+eye Windows preview lacks exact comparison authority."
    }

    $snapshotNames = @("front-full.png", "three-quarter-full.png", "side-full.png", "face-front.png", "face-zoom.png", "eyes-closeup.png")
    foreach ($name in $snapshotNames) {
        [void](Need-File -Path (Join-Path $previewDir "snapshots\$name") -Label "Preview snapshot $name")
    }

    if ((Sha256 $PackagePath) -ne $packageShaBefore -or
        (Sha256 $reconstructionPath) -ne $reconstructionShaBefore -or
        (Sha256 $reconstructionAuthorityPath) -ne $reconstructionAuthorityShaBefore -or
        (Sha256 $sourceMeshPath) -ne $sourceMeshShaBefore -or
        (Sha256 $donorObj) -ne $donorShaBefore -or
        (Sha256 $fitParams) -ne $fitShaBefore) {
        throw "Retained reconstruction/package authority changed during hair+eye preview continuation."
    }

    $summary = [ordered]@{
        format = "bodyrig-retained-hair-eye-preview"
        version = 1
        bodyrig_revision = $head
        package_sha256 = $packageShaBefore
        reconstruction_sha256 = $reconstructionShaBefore
        reconstruction_authority_sha256 = $reconstructionAuthorityShaBefore
        donor_obj_sha256 = $donorShaBefore
        fit_params_sha256 = $fitShaBefore
        target_model_family = $targetFamily
        review_vrm_sha256 = Sha256 $runtimeVrmPath
        comparison_authority_sha256 = Sha256 $comparisonPath
        hair_deformation_probe_sha256 = Sha256 $hairProbePath
        source_hair_runtime_applied = $true
        source_eye_surface_applied = $true
        iris_appearance_status = "review-pending"
        corneal_material_status = "runtime-applied"
        eyelash_status = "missing"
        reconstruction_rerun = $false
        comparison_only = $true
        full_fidelity_component_complete = $false
        human_review_required = $true
        production_activation = $false
        semantics = "retained-reconstruction-hair-eye-physical-preview-not-full-fidelity-acceptance"
        snapshots = $snapshotNames
    }
    $summaryPath = Join-Path $attempt "retained-hair-eye-preview.json"
    $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

    if (Test-Path -LiteralPath $OutputRoot) { throw "Retained hair+eye preview output appeared during build: $OutputRoot" }
    Move-Item -LiteralPath $attempt -Destination $OutputRoot
    $committed = $true

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "RETAINED HAIR + EYE WINDOWS PREVIEW: READY"
    Write-Host "Output:          $OutputRoot"
    Write-Host "Hair:            SOURCE-DERIVED RUNTIME APPLIED"
    Write-Host "Eyes:            SOURCE-BAKED RUNTIME APPLIED"
    Write-Host "Cornea:          RUNTIME APPLIED"
    Write-Host "Iris:            REVIEW-PENDING"
    Write-Host "Eyelashes:       MISSING"
    Write-Host "SiTH rerun:      FALSE"
    Write-Host "Full fidelity:   FALSE - inspect this preview before further composition"
    Write-Host "Production:      FALSE"
    Write-Host "============================================================"
    exit 0
}
finally {
    if (-not $committed -and (Test-Path -LiteralPath $attempt -PathType Container)) {
        Remove-Item -LiteralPath $attempt -Recurse -Force -ErrorAction SilentlyContinue
    }
}
