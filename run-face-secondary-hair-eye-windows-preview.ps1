param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$HairEyeRuntimeDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
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
    $resolved = Need-File -Path $Path -Label $Label
    try { return Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
    catch { throw "$Label is unreadable JSON: $resolved" }
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath (Need-File -Path $Path -Label "Hash input") -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Invoke-CheckedPython {
    param([Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Label)
    $raw = @(& $BodyRigPython @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "$Label failed: $($raw -join [Environment]::NewLine)" }
    return $raw
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "Face-secondary hair+eye Windows preview is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Face-secondary hair+eye preview must run from canonical main."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Face-secondary hair+eye preview requires a clean checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$PackagePath = Need-File -Path $PackagePath -Label "Current-floor package"
$HairEyeRuntimeDir = Need-Directory -Path $HairEyeRuntimeDir -Label "Source hair+eye review runtime"
$packageShaBefore = Sha256 $PackagePath
$hairEyeReceipt = Need-File -Path (Join-Path $HairEyeRuntimeDir "source-hair-eye-review-runtime.json") -Label "Hair+eye runtime receipt"
$hairEyeVrm = Need-File -Path (Join-Path $HairEyeRuntimeDir "source-hair-eye-review.vrm") -Label "Hair+eye review VRM"
$hairEyeReceiptShaBefore = Sha256 $hairEyeReceipt
$hairEyeVrmShaBefore = Sha256 $hairEyeVrm

$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Face-secondary hair+eye preview output already exists: $OutputDir" }
$parent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($parent)) { throw "Preview output must have a parent directory." }
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$attempt = Join-Path $parent ("." + [IO.Path]::GetFileName($OutputDir) + ".partial-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attempt | Out-Null
$committed = $false

try {
    $runtimeDir = Join-Path $attempt "runtime"
    $comparisonDir = Join-Path $attempt "comparison"
    $renderDir = Join-Path $attempt "windows-preview"

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "BODYRIG FACE-SECONDARY ON HAIR+EYE REVIEW"
    Write-Host "Revision:          $head"
    Write-Host "Package SHA:       $packageShaBefore"
    Write-Host "Hair+eye VRM SHA:  $hairEyeVrmShaBefore"
    Write-Host "Package mutation:  FALSE"
    Write-Host "Promotion:         FALSE"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"

    Write-Host ""
    Write-Host "=== 1/3 COMPOSE REVIEW-ONLY FACE-SECONDARY ==="
    [void](Invoke-CheckedPython -Label "Face-secondary hair+eye runtime composition" -Arguments @(
        "-m", "bodyrig.face_secondary_hair_eye_review", "build",
        "--package", $PackagePath,
        "--hair-eye-runtime", $HairEyeRuntimeDir,
        "--output-dir", $runtimeDir,
        "--bodyrig-revision", $head
    ))
    $runtimeReceipt = Read-Json -Path (Join-Path $runtimeDir "face-secondary-hair-eye-review-runtime.json") -Label "Face-secondary hair+eye runtime receipt"
    if ($runtimeReceipt.comparisonOnly -ne $true -or $runtimeReceipt.humanReviewRequired -ne $true -or
        $runtimeReceipt.faceSecondaryComponentAuthority -ne $false -or $runtimeReceipt.packageMutationPerformed -ne $false -or
        $runtimeReceipt.productionActivation -ne $false) {
        throw "Face-secondary hair+eye runtime crossed review-only authority."
    }

    Write-Host ""
    Write-Host "=== 2/3 MATERIALIZE COMPARISON PACKAGE ==="
    [void](Invoke-CheckedPython -Label "Face-secondary hair+eye comparison package" -Arguments @(
        "-m", "bodyrig.face_secondary_hair_eye_comparison", "build",
        "--package", $PackagePath,
        "--runtime-dir", $runtimeDir,
        "--output-dir", $comparisonDir,
        "--bodyrig-revision", $head
    ))
    $comparisonReceipt = Read-Json -Path (Join-Path $comparisonDir "face-secondary-hair-eye-comparison.json") -Label "Face-secondary hair+eye comparison receipt"
    $comparisonPackage = Need-File -Path (Join-Path $comparisonDir "face-secondary-hair-eye-comparison.mrbody") -Label "Face-secondary hair+eye comparison package"
    if ([string]$comparisonReceipt.comparisonPackageSha256 -ne (Sha256 $comparisonPackage) -or
        $comparisonReceipt.comparisonOnly -ne $true -or $comparisonReceipt.physicalAcceptanceAuthority -ne $false -or
        $comparisonReceipt.humanReviewRequired -ne $true -or $comparisonReceipt.packagePromotionAuthority -ne $false -or
        $comparisonReceipt.productionActivation -ne $false) {
        throw "Face-secondary hair+eye comparison receipt crossed its authority boundary."
    }

    Write-Host ""
    Write-Host "=== 3/3 WINDOWS PHYSICAL PREVIEW ==="
    $renderArgs = @{
        PackagePath = $comparisonPackage
        OutputDir = $renderDir
        BodyRigPython = $BodyRigPython
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $renderArgs.UnityExe = $UnityExe }
    if ($SkipBuild) { $renderArgs.SkipBuild = $true }
    & (Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1") @renderArgs
    if ($LASTEXITCODE -ne 0) { throw "Face-secondary hair+eye Windows renderer failed with exit code $LASTEXITCODE" }

    $visibilityPath = Need-File -Path (Join-Path $renderDir "component-visibility-probe.json") -Label "Component visibility probe"
    $renderSetPath = Need-File -Path (Join-Path $renderDir "snapshots\fidelity-render-set.json") -Label "Fidelity render set"
    $gapPath = Join-Path $attempt "component-gap-plan.json"
    [void](Invoke-CheckedPython -Label "Face-secondary component gap validation" -Arguments @(
        "-m", "bodyrig.fidelity_component_gap",
        "--visibility-probe", $visibilityPath,
        "--render-set", $renderSetPath,
        "--out", $gapPath
    ))
    $gap = Read-Json -Path $gapPath -Label "Face-secondary component gap plan"
    $drawable = @($gap.drawable_components | ForEach-Object { [string]$_ })
    foreach ($required in @("hair", "eyes", "face-secondary")) {
        if (-not ($drawable -contains $required)) { throw "Face-secondary preview lacks physically drawable $required evidence." }
    }

    if ((Sha256 $PackagePath) -ne $packageShaBefore -or (Sha256 $hairEyeReceipt) -ne $hairEyeReceiptShaBefore -or (Sha256 $hairEyeVrm) -ne $hairEyeVrmShaBefore) {
        throw "Source package or hair+eye runtime bytes changed during face-secondary preview."
    }
    $summary = [ordered]@{
        format = "bodyrig-face-secondary-hair-eye-windows-preview"
        version = 1
        bodyrig_revision = $head
        source_package_sha256 = $packageShaBefore
        source_hair_eye_runtime_receipt_sha256 = $hairEyeReceiptShaBefore
        source_hair_eye_review_vrm_sha256 = $hairEyeVrmShaBefore
        face_secondary_runtime_receipt_sha256 = Sha256 (Join-Path $runtimeDir "face-secondary-hair-eye-review-runtime.json")
        comparison_receipt_sha256 = Sha256 (Join-Path $comparisonDir "face-secondary-hair-eye-comparison.json")
        comparison_package_sha256 = Sha256 $comparisonPackage
        component_visibility_probe_sha256 = Sha256 $visibilityPath
        render_set_sha256 = Sha256 $renderSetPath
        gap_plan_sha256 = Sha256 $gapPath
        drawable_components = @($gap.drawable_components)
        missing_components = @($gap.missing_components)
        strict_machine_scoring_ready = [bool]$gap.strict_machine_scoring_ready
        next_actions = @($gap.next_actions)
        source_hair_preserved = $true
        source_eye_surface_preserved = $true
        face_secondary_drawable = $true
        comparison_only = $true
        physical_acceptance_authority = $false
        human_visual_authority_required = $true
        package_promotion_authority = $false
        production_activation = $false
        semantics = "hair-eye-face-secondary-physical-comparison-not-visual-or-release-acceptance"
    }
    $summary | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $attempt "face-secondary-hair-eye-preview.json") -Encoding UTF8

    Move-Item -LiteralPath $attempt -Destination $OutputDir
    $committed = $true

    Write-Host ""
    Write-Host "Face-secondary hair+eye Windows preview: PASS"
    Write-Host "Drawable: $($drawable -join ', ')"
    Write-Host "Missing:  $(@($gap.missing_components) -join ', ')"
    Write-Host "Snapshots: $(Join-Path $OutputDir 'windows-preview\snapshots')"
    Write-Host "Authority: comparison-only; human visual review required; no package/production activation"
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $attempt -PathType Container)) {
        Remove-Item -LiteralPath $attempt -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit 0
