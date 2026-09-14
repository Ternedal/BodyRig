param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [string]$Rebuild1IdentityWorkspace = "",
    [string]$Rebuild2IdentityWorkspace = "",
    [string]$IdentityRoot = "",
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
    [switch]$SkipBuild,
    [switch]$OpenSnapshots
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
    try { return Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60 }
    catch { throw "$Label is unreadable JSON: $resolved" }
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath (Need-File -Path $Path -Label "Hash input") -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
}
function Test-V1Version($Value) {
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }
}
function Get-Head {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $raw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$raw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
    return $head
}
function Assert-HeadPinned {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[Parameter(Mandatory = $true)][string]$Expected)
    if ((Get-Head -RepoRoot $RepoRoot) -ne $Expected) { throw "BodyRig checkout changed during full-component evening review." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "BodyRig checkout became dirty during full-component evening review." }
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
function Assert-CheckoutBoundPython {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[Parameter(Mandatory = $true)][string]$Python)
    $expected = Need-File -Path (Join-Path $RepoRoot "bodyrig\__init__.py") -Label "Checkout-bound BodyRig module"
    $raw = @(& $Python -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "Could not prove checkout-bound BodyRig Python authority." }
    $actual = [IO.Path]::GetFullPath(([string]$raw[0]).Trim())
    if (-not [string]::Equals($actual, $expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from a different checkout/package: $actual"
    }
}
function Resolve-BodyReference {
    param([Parameter(Mandatory = $true)][string]$BaselineEvaluation,[Parameter(Mandatory = $true)][string]$IdentityRootPath)
    $baseline = Read-Json -Path $BaselineEvaluation -Label "Baseline fidelity evaluation"
    $wanted = Need-Sha256 -Value ([string]$baseline.body_reference.sha256) -Label "Baseline body-reference SHA-256"
    $matches = @(
        Get-ChildItem -LiteralPath $IdentityRootPath -Directory -ErrorAction Stop | ForEach-Object {
            $candidate = Join-Path $_.FullName "identity-capture\primary-rgba.png"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -eq $wanted) { $candidate }
            }
        }
    )
    if ($matches.Count -ne 1) { throw "Expected exactly one private body reference matching $wanted; found $($matches.Count)." }
    return Need-File -Path $matches[0] -Label "Private body reference"
}
function Assert-SemanticallyEqualJson {
    param([Parameter(Mandatory = $true)]$Expected,[Parameter(Mandatory = $true)]$Actual,[Parameter(Mandatory = $true)][string]$Label)
    $expectedText = $Expected | ConvertTo-Json -Depth 60 -Compress
    $actualText = $Actual | ConvertTo-Json -Depth 60 -Compress
    if ($expectedText -ne $actualText) { throw "$Label differs from freshly recomputed authority; refusing stale/tampered reuse." }
}
function Test-FaceSecondaryComplete {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [Parameter(Mandatory = $true)][string]$ExpectedSourcePackageSha
    )
    foreach ($relative in @(
        "face-secondary-hair-eye-preview.json",
        "runtime\face-secondary-hair-eye-review-runtime.json",
        "comparison\face-secondary-hair-eye-comparison.json",
        "comparison\face-secondary-hair-eye-comparison.mrbody",
        "component-gap-plan.json",
        "windows-preview\component-visibility-probe.json",
        "windows-preview\snapshots\fidelity-render-set.json",
        "windows-preview\snapshots\front-full.png",
        "windows-preview\snapshots\face-front.png",
        "windows-preview\snapshots\eyes-closeup.png"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $relative) -PathType Leaf)) { return $false }
    }
    try { $summary = Get-Content -LiteralPath (Join-Path $Path "face-secondary-hair-eye-preview.json") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
    catch { return $false }
    if ([string]$summary.format -ne "bodyrig-face-secondary-hair-eye-windows-preview" -or
        -not (Test-V1Version $summary.version) -or
        [string]$summary.bodyrig_revision -ne $ExpectedHead -or
        [string]$summary.source_package_sha256 -ne $ExpectedSourcePackageSha -or
        $summary.source_hair_preserved -ne $true -or $summary.source_eye_surface_preserved -ne $true -or
        $summary.face_secondary_drawable -ne $true -or $summary.comparison_only -ne $true -or
        $summary.physical_acceptance_authority -ne $false -or $summary.human_visual_authority_required -ne $true -or
        $summary.package_promotion_authority -ne $false -or $summary.production_activation -ne $false) { return $false }
    $comparisonPackage = Join-Path $Path "comparison\face-secondary-hair-eye-comparison.mrbody"
    return (Sha256 $comparisonPackage) -eq [string]$summary.comparison_package_sha256
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig full-component evening review is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Full-component evening review must be launched from canonical main."
}
$head = Get-Head -RepoRoot $repoRoot
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Full-component evening review requires an exact clean BodyRig checkout." }

$WorkRoot = Need-Directory -Path $WorkRoot -Label "Fidelity convergence work root"
if ([string]::IsNullOrWhiteSpace($IdentityRoot)) {
    if ([string]::IsNullOrWhiteSpace([string]$env:LOCALAPPDATA)) { throw "LOCALAPPDATA is unavailable; pass -IdentityRoot explicitly." }
    $IdentityRoot = Join-Path $env:LOCALAPPDATA "BodyRig\identity-workspaces"
}
$IdentityRoot = Need-Directory -Path $IdentityRoot -Label "BodyRig identity-workspaces root"
$BodyRigPython = Resolve-BodyRigPython -RepoRoot $repoRoot -Requested $BodyRigPython
Assert-CheckoutBoundPython -RepoRoot $repoRoot -Python $BodyRigPython

$currentFloorRunner = Need-File -Path (Join-Path $repoRoot "run-fidelity-evening-current-floor-review.ps1") -Label "Current-floor evening review runner"
$faceSecondaryRunner = Need-File -Path (Join-Path $repoRoot "run-face-secondary-hair-eye-windows-preview.ps1") -Label "Face-secondary hair+eye preview runner"

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG FULL-COMPONENT CURRENT-FLOOR EVENING REVIEW"
Write-Host "Revision:            $head"
Write-Host "Work root:           $WorkRoot"
Write-Host "SiTH reconstruction: NEVER STARTED BY THIS RUNNER"
Write-Host "Face-secondary:      REVIEW-ONLY COMPOSITION"
Write-Host "Production:          FALSE"
Write-Host "============================================================"

Write-Host ""
Write-Host "=== 1/3 CURRENT-FLOOR HAIR + EYE REVIEW ==="
$baseArgs = @{
    WorkRoot = $WorkRoot
    IdentityRoot = $IdentityRoot
    BodyRigPython = $BodyRigPython
}
if (-not [string]::IsNullOrWhiteSpace($Rebuild1IdentityWorkspace)) { $baseArgs.Rebuild1IdentityWorkspace = $Rebuild1IdentityWorkspace }
if (-not [string]::IsNullOrWhiteSpace($Rebuild2IdentityWorkspace)) { $baseArgs.Rebuild2IdentityWorkspace = $Rebuild2IdentityWorkspace }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $baseArgs.UnityExe = $UnityExe }
if ($SkipBuild) { $baseArgs.SkipBuild = $true }
& $currentFloorRunner @baseArgs
if ($LASTEXITCODE -ne 0) { throw "Current-floor hair+eye evening review failed with exit code $LASTEXITCODE" }
Assert-HeadPinned -RepoRoot $repoRoot -Expected $head

$tag = $head.Substring(0, 8)
$eveningRoot = Need-Directory -Path (Join-Path $WorkRoot "evening-current-floor-$tag") -Label "Current-floor evening output"
$baseSummaryPath = Need-File -Path (Join-Path $eveningRoot "evening-review-summary.json") -Label "Current-floor evening summary"
$baseSummary = Read-Json -Path $baseSummaryPath -Label "Current-floor evening summary"
if ([string]$baseSummary.format -ne "bodyrig-fidelity-current-floor-evening-review" -or
    -not (Test-V1Version $baseSummary.version) -or
    [string]$baseSummary.bodyrig_revision -ne $head -or
    $baseSummary.expensive_reconstruction_rerun -ne $false -or
    $baseSummary.physical_acceptance_authority -ne $false -or
    $baseSummary.human_visual_authority_required -ne $true -or
    $baseSummary.production_activation -ne $false) {
    throw "Current-floor evening summary crossed its authority boundary."
}
$selectedLabel = ([string]$baseSummary.selected_candidate).Trim()
if ($selectedLabel -notin @("baseline", "refit1", "reconstruction2")) { throw "Current-floor evening summary selected_candidate is invalid." }
$currentPackageSha = Need-Sha256 -Value ([string]$baseSummary.current_floor_package_sha256) -Label "Current-floor package SHA-256"
$currentFloorDir = Need-Directory -Path (Join-Path $eveningRoot "current-floor-$selectedLabel") -Label "Current-floor package directory"
$currentPackages = @(Get-ChildItem -LiteralPath $currentFloorDir -Filter "*.mrbody" -File)
if ($currentPackages.Count -ne 1) { throw "Current-floor package directory must contain exactly one .mrbody package." }
$currentPackage = $currentPackages[0].FullName
if ((Sha256 $currentPackage) -ne $currentPackageSha) { throw "Current-floor package bytes differ from the base evening summary." }
$hairEyeOutput = Need-Directory -Path (Join-Path $eveningRoot "retained-hair-eye-$selectedLabel") -Label "Retained hair+eye output"
$hairEyeRuntime = Need-Directory -Path (Join-Path $hairEyeOutput "runtime") -Label "Retained hair+eye runtime"

Write-Host ""
Write-Host "=== 2/3 FACE-SECONDARY ON RETAINED HAIR + EYE RUNTIME ==="
$faceSecondaryOutput = Join-Path $eveningRoot "face-secondary-hair-eye-$selectedLabel"
if (Test-FaceSecondaryComplete -Path $faceSecondaryOutput -ExpectedHead $head -ExpectedSourcePackageSha $currentPackageSha) {
    Write-Host "Reusing complete face-secondary comparison: $faceSecondaryOutput"
} else {
    if (Test-Path -LiteralPath $faceSecondaryOutput) { throw "Face-secondary output exists but is incomplete or stale: $faceSecondaryOutput" }
    $faceArgs = @{
        PackagePath = $currentPackage
        HairEyeRuntimeDir = $hairEyeRuntime
        OutputDir = $faceSecondaryOutput
        BodyRigPython = $BodyRigPython
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $faceArgs.UnityExe = $UnityExe }
    if ($SkipBuild) { $faceArgs.SkipBuild = $true }
    & $faceSecondaryRunner @faceArgs
    if ($LASTEXITCODE -ne 0) { throw "Face-secondary hair+eye review failed with exit code $LASTEXITCODE" }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
    if (-not (Test-FaceSecondaryComplete -Path $faceSecondaryOutput -ExpectedHead $head -ExpectedSourcePackageSha $currentPackageSha)) {
        throw "Face-secondary review returned without complete current-floor authority evidence."
    }
}

$faceSummaryPath = Need-File -Path (Join-Path $faceSecondaryOutput "face-secondary-hair-eye-preview.json") -Label "Face-secondary preview summary"
$faceSummary = Read-Json -Path $faceSummaryPath -Label "Face-secondary preview summary"
$comparisonPackage = Need-File -Path (Join-Path $faceSecondaryOutput "comparison\face-secondary-hair-eye-comparison.mrbody") -Label "Face-secondary comparison package"
$comparisonPackageSha = Sha256 $comparisonPackage
if ($comparisonPackageSha -ne [string]$faceSummary.comparison_package_sha256) { throw "Face-secondary comparison package bytes differ from preview authority." }
$gapPath = Need-File -Path (Join-Path $faceSecondaryOutput "component-gap-plan.json") -Label "Face-secondary component gap plan"
$gap = Read-Json -Path $gapPath -Label "Face-secondary component gap plan"
if ([string]$gap.bodyrig_revision -ne $head -or [string]$gap.package_sha256 -ne $comparisonPackageSha -or
    $gap.human_visual_authority_required -ne $true -or $gap.production_activation -ne $false) {
    throw "Face-secondary component gap plan crossed its authority boundary."
}
$drawable = @($gap.drawable_components | ForEach-Object { [string]$_ })
foreach ($required in @("hair", "eyes", "face-secondary")) {
    if (-not ($drawable -contains $required)) { throw "Full-component evening review lacks physically drawable $required evidence." }
}
$missing = @($gap.missing_components | ForEach-Object { [string]$_ })
$nextActions = @($gap.next_actions)
$renderSet = Need-File -Path (Join-Path $faceSecondaryOutput "windows-preview\snapshots\fidelity-render-set.json") -Label "Face-secondary fidelity render set"

Write-Host ""
Write-Host "=== 3/3 DIAGNOSTIC V5 SCORE OF HAIR + EYES + FACE-SECONDARY ==="
$referenceSet = Need-File -Path (Join-Path $WorkRoot "references\reference-set.json") -Label "Frozen fidelity reference set"
$baselineEvaluation = Get-ChildItem -Path (Join-Path $WorkRoot "rebuild-01\full\fidelity-evaluation-resumed-*.json") -File -ErrorAction Stop | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $baselineEvaluation) { throw "Historical baseline fidelity evaluation was not found." }
$bodyReference = Resolve-BodyReference -BaselineEvaluation $baselineEvaluation.FullName -IdentityRootPath $IdentityRoot
$rigSetup = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json") -Label "BodyRig rig setup"
$diagnosticEvaluation = Join-Path $eveningRoot "full-component-diagnostic-v5-$selectedLabel.json"
$diagnosticAttempt = Join-Path $eveningRoot (".full-component-diagnostic-v5-$selectedLabel.verify-" + [Guid]::NewGuid().ToString("N") + ".json")
try {
    & $BodyRigPython -m bodyrig.fidelity_evaluator_cli `
        --rig-setup $rigSetup `
        --reference-set $referenceSet `
        --render-set $renderSet `
        --body-reference-rgba $bodyReference `
        --iteration 9002 `
        --allow-incomplete-component-comparison `
        --out $diagnosticAttempt
    if ($LASTEXITCODE -ne 0) { throw "Diagnostic full-component evaluation failed with exit code $LASTEXITCODE" }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
    $freshDiagnostic = Read-Json -Path $diagnosticAttempt -Label "Fresh full-component diagnostic evaluation"
    if (Test-Path -LiteralPath $diagnosticEvaluation -PathType Leaf) {
        $existingDiagnostic = Read-Json -Path $diagnosticEvaluation -Label "Existing full-component diagnostic evaluation"
        Assert-SemanticallyEqualJson -Expected $freshDiagnostic -Actual $existingDiagnostic -Label "Existing full-component diagnostic evaluation"
        Write-Host "Revalidated existing full-component diagnostic evaluation: $diagnosticEvaluation"
    } else {
        Move-Item -LiteralPath $diagnosticAttempt -Destination $diagnosticEvaluation
        $diagnosticAttempt = ""
    }
} finally {
    if (-not [string]::IsNullOrWhiteSpace($diagnosticAttempt) -and (Test-Path -LiteralPath $diagnosticAttempt -PathType Leaf)) {
        Remove-Item -LiteralPath $diagnosticAttempt -Force -ErrorAction SilentlyContinue
    }
}
$diagnostic = Read-Json -Path $diagnosticEvaluation -Label "Full-component diagnostic evaluation"
if ((Need-Sha256 -Value ([string]$diagnostic.measurement.candidate_sha256) -Label "Full-component diagnostic candidate SHA-256") -ne $comparisonPackageSha) {
    throw "Full-component diagnostic targets different comparison package bytes."
}

$summaryPath = Join-Path $eveningRoot "evening-full-component-summary.json"
$summary = [ordered]@{
    format = "bodyrig-fidelity-current-floor-full-component-evening-review"
    version = 1
    bodyrig_revision = $head
    selected_iteration = $baseSummary.selected_iteration
    selected_candidate = $selectedLabel
    historical_selected_package_sha256 = [string]$baseSummary.historical_selected_package_sha256
    current_floor_source_package_sha256 = $currentPackageSha
    comparison_package_sha256 = $comparisonPackageSha
    base_evening_summary_sha256 = Sha256 $baseSummaryPath
    face_secondary_preview_summary_sha256 = Sha256 $faceSummaryPath
    component_gap_plan_sha256 = Sha256 $gapPath
    diagnostic_evaluation_sha256 = Sha256 $diagnosticEvaluation
    selected_identity_workspace = [string]$baseSummary.selected_identity_workspace
    selected_reconstruction_sha256 = [string]$baseSummary.selected_reconstruction_sha256
    current_floor_refit_repackage = $true
    expensive_reconstruction_rerun = $false
    face_secondary_review_composition = $true
    comparison_only = $true
    diagnostic_only = $true
    diagnostic_scores = [ordered]@{
        overall = $diagnostic.measurement.scores.overall
        face_appearance = $diagnostic.measurement.scores.face_appearance
        body_silhouette = $diagnostic.measurement.scores.body_silhouette
        hair_appearance = $diagnostic.measurement.scores.hair_appearance
        skin_material = $diagnostic.measurement.scores.skin_material
        photorealism = $diagnostic.measurement.scores.photorealism
        human_plausibility = $diagnostic.measurement.scores.human_plausibility
    }
    drawable_components = @($drawable)
    missing_components = @($missing)
    next_actions = @($nextActions)
    strict_machine_scoring_ready = [bool]$gap.strict_machine_scoring_ready
    full_fidelity_component_complete = [bool]$gap.strict_machine_scoring_ready
    physical_acceptance_authority = $false
    human_visual_authority_required = $true
    package_promotion_authority = $false
    production_activation = $false
    semantics = "current-floor-hair-eye-face-secondary-physical-comparison-plus-diagnostic-score-not-visual-or-release-acceptance"
}
if (Test-Path -LiteralPath $summaryPath -PathType Leaf) {
    $existing = Read-Json -Path $summaryPath -Label "Existing full-component evening summary"
    Assert-SemanticallyEqualJson -Expected $summary -Actual $existing -Label "Existing full-component evening summary"
} else {
    $summary | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
}

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG FULL-COMPONENT EVENING REVIEW READY FOR HUMAN QA"
Write-Host "Selected history: $selectedLabel (iteration $($baseSummary.selected_iteration))"
Write-Host "Current-floor SHA:$currentPackageSha"
Write-Host "Comparison SHA:   $comparisonPackageSha"
Write-Host "Overall diag:     $($diagnostic.measurement.scores.overall)"
Write-Host "Hair diag:        $($diagnostic.measurement.scores.hair_appearance)"
Write-Host "Face diag:        $($diagnostic.measurement.scores.face_appearance)"
Write-Host "Body diag:        $($diagnostic.measurement.scores.body_silhouette)"
Write-Host "Drawable:         $($drawable -join ', ')"
Write-Host "Missing:          $(if ($missing.Count -eq 0) { '<none>' } else { $missing -join ', ' })"
Write-Host "Machine complete: $([bool]$gap.strict_machine_scoring_ready)"
foreach ($action in $nextActions) {
    Write-Host "Next:             $([string]$action.id) | $([string]$action.reason)"
}
Write-Host "SiTH rerun:       FALSE"
Write-Host "Human QA:         REQUIRED"
Write-Host "Production:       FALSE"
Write-Host "Summary:          $summaryPath"
Write-Host "Snapshots:        $(Join-Path $faceSecondaryOutput 'windows-preview\snapshots')"
Write-Host "============================================================"

if ($OpenSnapshots) { Start-Process explorer.exe -ArgumentList @((Join-Path $faceSecondaryOutput "windows-preview\snapshots")) }
exit 0
