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
    try { return Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
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
    $actual = Get-Head -RepoRoot $RepoRoot
    if ($actual -ne $Expected) { throw "BodyRig checkout changed during evening review: expected $Expected, found $actual" }
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
function Resolve-WorkspaceFromMarker {
    param([Parameter(Mandatory = $true)][string]$RebuildDir)
    $marker = Join-Path $RebuildDir "identity-workspace.txt"
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { return "" }
    $lines = @(Get-Content -LiteralPath $marker -Encoding UTF8 | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    if ($lines.Count -ne 1) { throw "Identity-workspace marker must contain exactly one non-empty path: $marker" }
    return Need-Directory -Path $lines[0] -Label "Retained identity workspace marker target"
}
function Resolve-WorkspaceByReconstructionHash {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    $wanted = Need-Sha256 -Value $ExpectedSha256 -Label "Expected reconstruction SHA-256"
    $matches = @(
        Get-ChildItem -LiteralPath $Root -Directory -ErrorAction Stop | ForEach-Object {
            $reconstruction = Join-Path $_.FullName "sith-input-v1\reconstruction.json"
            if (Test-Path -LiteralPath $reconstruction -PathType Leaf) {
                $actual = (Get-FileHash -LiteralPath $reconstruction -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($actual -eq $wanted) { $_.FullName }
            }
        }
    )
    if ($matches.Count -ne 1) {
        throw "Expected exactly one retained identity workspace for reconstruction $wanted; found $($matches.Count)."
    }
    return Need-Directory -Path $matches[0] -Label "Hash-bound retained identity workspace"
}
function Resolve-Workspace {
    param(
        [Parameter(Mandatory = $true)][int]$RebuildNumber,
        [string]$Explicit,
        [string]$ExpectedReconstructionSha256,
        [Parameter(Mandatory = $true)][string]$WorkRootPath,
        [Parameter(Mandatory = $true)][string]$IdentityRootPath
    )
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        $workspace = Need-Directory -Path $Explicit -Label "Explicit rebuild-$('{0:D2}' -f $RebuildNumber) identity workspace"
    } else {
        $rebuild = Join-Path $WorkRootPath ("rebuild-{0:D2}" -f $RebuildNumber)
        $workspace = Resolve-WorkspaceFromMarker -RebuildDir $rebuild
        if ([string]::IsNullOrWhiteSpace($workspace) -and -not [string]::IsNullOrWhiteSpace($ExpectedReconstructionSha256)) {
            $workspace = Resolve-WorkspaceByReconstructionHash -Root $IdentityRootPath -ExpectedSha256 $ExpectedReconstructionSha256
        }
        if ([string]::IsNullOrWhiteSpace($workspace)) {
            throw "Could not resolve rebuild-$('{0:D2}' -f $RebuildNumber) identity workspace from marker or reconstruction hash. Pass the matching -Rebuild$($RebuildNumber)IdentityWorkspace explicitly."
        }
    }
    $reconstruction = Need-File -Path (Join-Path $workspace "sith-input-v1\reconstruction.json") -Label "Retained reconstruction"
    $sha = Sha256 $reconstruction
    if (-not [string]::IsNullOrWhiteSpace($ExpectedReconstructionSha256) -and $sha -ne (Need-Sha256 -Value $ExpectedReconstructionSha256 -Label "Expected reconstruction SHA-256")) {
        throw "Resolved retained workspace reconstruction differs from candidate authority."
    }
    return [pscustomobject]@{ Path = $workspace; Reconstruction = $reconstruction; ReconstructionSha256 = $sha }
}
function Resolve-BodyReference {
    param(
        [Parameter(Mandatory = $true)][string]$BaselineEvaluation,
        [Parameter(Mandatory = $true)][string]$IdentityRootPath
    )
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
function Test-RetainedPreviewComplete {
    param([Parameter(Mandatory = $true)][string]$Path)
    foreach ($relative in @(
        "retained-hair-eye-preview.json",
        "windows-preview\component-visibility-probe.json",
        "windows-preview\snapshots\fidelity-render-set.json",
        "windows-preview\snapshots\front-full.png",
        "windows-preview\snapshots\face-front.png",
        "windows-preview\snapshots\eyes-closeup.png"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $relative) -PathType Leaf)) { return $false }
    }
    return $true
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig evening fidelity review is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Evening fidelity review must be launched from the canonical main checkout."
}
$head = Get-Head -RepoRoot $repoRoot
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Evening fidelity review requires an exact clean BodyRig checkout." }

$WorkRoot = Need-Directory -Path $WorkRoot -Label "Fidelity convergence work root"
if ([string]::IsNullOrWhiteSpace($IdentityRoot)) {
    if ([string]::IsNullOrWhiteSpace([string]$env:LOCALAPPDATA)) { throw "LOCALAPPDATA is unavailable; pass -IdentityRoot explicitly." }
    $IdentityRoot = Join-Path $env:LOCALAPPDATA "BodyRig\identity-workspaces"
}
$IdentityRoot = Need-Directory -Path $IdentityRoot -Label "BodyRig identity-workspaces root"
$BodyRigPython = Resolve-BodyRigPython -RepoRoot $repoRoot -Requested $BodyRigPython

$v5Review = Need-File -Path (Join-Path $repoRoot "run-fidelity-v5-review.ps1") -Label "V5 review runner"
$retainedPreview = Need-File -Path (Join-Path $repoRoot "run-retained-hair-eye-preview.ps1") -Label "Retained hair+eye preview runner"
$tag = $head.Substring(0, 8)
$reanalysisRoot = Join-Path $WorkRoot "reanalysis-v5-$tag"
$decisionPath = Join-Path $reanalysisRoot "convergence-decision.json"
$baselineEvaluation = Get-ChildItem -Path (Join-Path $WorkRoot "rebuild-01\full\fidelity-evaluation-resumed-*.json") -File -ErrorAction Stop | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $baselineEvaluation) { throw "Historical baseline fidelity evaluation was not found." }

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG EVENING FIDELITY REVIEW"
Write-Host "Revision:            $head"
Write-Host "Work root:           $WorkRoot"
Write-Host "SiTH reconstruction: NEVER STARTED BY THIS RUNNER"
Write-Host "Production:          FALSE"
Write-Host "============================================================"

Write-Host ""
Write-Host "=== 1/3 EXISTING-RENDER V5 REVIEW ==="
& $v5Review -WorkRoot $WorkRoot -BodyRigPython $BodyRigPython
if ($LASTEXITCODE -ne 0) { throw "V5 review failed with exit code $LASTEXITCODE" }
Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
$decision = Read-Json -Path $decisionPath -Label "V5 convergence decision"
$best = [int]$decision.best_iteration
if ($best -notin @(1,2,3)) { throw "V5 convergence selected unsupported best iteration: $best" }

$session1 = Read-Json -Path (Join-Path $WorkRoot "rebuild-01\physical-session.json") -Label "Rebuild 1 physical session"
if ([string]$session1.status -ne "pass" -or [string]$session1.stage -ne "complete") { throw "Rebuild 1 physical session is not a completed PASS." }
$bodyId = ([string]$session1.body_id).Trim()
if ($bodyId -notmatch '^[a-z0-9æøå_-]{1,160}$') { throw "Rebuild 1 body_id is invalid." }
$baselineClone = Need-Directory -Path ([string]$session1.clone_output) -Label "Rebuild 1 clone output"
$baselinePackage = Need-File -Path (Join-Path $baselineClone "clone\$bodyId.mrbody") -Label "Baseline package"
$refitRoot = Join-Path $WorkRoot "rebuild-01\night-refinement-01\refit"
$refitPackage = Need-File -Path (Join-Path $refitRoot "$bodyId.mrbody") -Label "Refit 1 package"
$refitResult = Read-Json -Path (Join-Path $refitRoot "refit-result.json") -Label "Refit 1 result"
$rebuild1ReconstructionSha = Need-Sha256 -Value ([string]$refitResult.reconstruction_authority_sha256) -Label "Rebuild 1 reconstruction SHA-256"

$selectedLabel = ""
$selectedPackage = ""
$selectedEvaluation = ""
$workspaceInfo = $null
switch ($best) {
    1 {
        $selectedLabel = "baseline"
        $selectedPackage = $baselinePackage
        $selectedEvaluation = Need-File -Path (Join-Path $reanalysisRoot "iteration-01-baseline.json") -Label "V5 baseline evaluation"
        $workspaceInfo = Resolve-Workspace -RebuildNumber 1 -Explicit $Rebuild1IdentityWorkspace -ExpectedReconstructionSha256 $rebuild1ReconstructionSha -WorkRootPath $WorkRoot -IdentityRootPath $IdentityRoot
    }
    2 {
        $selectedLabel = "refit1"
        $selectedPackage = $refitPackage
        $selectedEvaluation = Need-File -Path (Join-Path $reanalysisRoot "iteration-02-refit1.json") -Label "V5 refit 1 evaluation"
        $workspaceInfo = Resolve-Workspace -RebuildNumber 1 -Explicit $Rebuild1IdentityWorkspace -ExpectedReconstructionSha256 $rebuild1ReconstructionSha -WorkRootPath $WorkRoot -IdentityRootPath $IdentityRoot
    }
    3 {
        $session2 = Read-Json -Path (Join-Path $WorkRoot "rebuild-02\physical-session.json") -Label "Rebuild 2 physical session"
        if ([string]$session2.status -ne "pass" -or [string]$session2.stage -ne "complete" -or [string]$session2.body_id -ne $bodyId) {
            throw "Rebuild 2 physical session is not a completed PASS for the same body alias."
        }
        $clone2 = Need-Directory -Path ([string]$session2.clone_output) -Label "Rebuild 2 clone output"
        $selectedLabel = "reconstruction2"
        $selectedPackage = Need-File -Path (Join-Path $clone2 "clone\$bodyId.mrbody") -Label "Reconstruction 2 package"
        $selectedEvaluation = Need-File -Path (Join-Path $reanalysisRoot "iteration-03-reconstruction2.json") -Label "V5 reconstruction 2 evaluation"
        $workspaceInfo = Resolve-Workspace -RebuildNumber 2 -Explicit $Rebuild2IdentityWorkspace -ExpectedReconstructionSha256 "" -WorkRootPath $WorkRoot -IdentityRootPath $IdentityRoot
    }
}

$selectedEval = Read-Json -Path $selectedEvaluation -Label "Selected V5 evaluation"
$expectedCandidateSha = Need-Sha256 -Value ([string]$selectedEval.measurement.candidate_sha256) -Label "Selected evaluator candidate SHA-256"
$selectedPackageSha = Sha256 $selectedPackage
if ($selectedPackageSha -ne $expectedCandidateSha) {
    throw "Selected package bytes differ from the candidate bytes scored by V5."
}

$eveningRoot = Join-Path $WorkRoot "evening-review-$tag"
if (-not (Test-Path -LiteralPath $eveningRoot -PathType Container)) { New-Item -ItemType Directory -Path $eveningRoot | Out-Null }
$retainedOutput = Join-Path $eveningRoot "retained-hair-eye-$selectedLabel"

Write-Host ""
Write-Host "=== 2/3 RETAINED HAIR + EYE PHYSICAL PREVIEW ==="
Write-Host "Selected candidate: $selectedLabel | iteration=$best"
Write-Host "Package SHA:        $selectedPackageSha"
Write-Host "Workspace:          $($workspaceInfo.Path)"
Write-Host "Reconstruction SHA: $($workspaceInfo.ReconstructionSha256)"
if (Test-RetainedPreviewComplete -Path $retainedOutput) {
    Write-Host "Reusing complete retained preview: $retainedOutput"
} else {
    if (Test-Path -LiteralPath $retainedOutput) {
        throw "Retained preview output exists but is incomplete; refusing to overwrite evidence: $retainedOutput"
    }
    $previewArgs = @{
        PackagePath = $selectedPackage
        IdentityWorkspace = [string]$workspaceInfo.Path
        OutputRoot = $retainedOutput
        BodyRigPython = $BodyRigPython
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $previewArgs.UnityExe = $UnityExe }
    if ($SkipBuild) { $previewArgs.SkipBuild = $true }
    & $retainedPreview @previewArgs
    if ($LASTEXITCODE -ne 0) { throw "Retained hair+eye preview failed with exit code $LASTEXITCODE" }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
    if (-not (Test-RetainedPreviewComplete -Path $retainedOutput)) { throw "Retained preview returned without complete physical evidence." }
}

$visibilityPath = Need-File -Path (Join-Path $retainedOutput "windows-preview\component-visibility-probe.json") -Label "Physical component visibility probe"
$visibility = Read-Json -Path $visibilityPath -Label "Physical component visibility probe"
$componentMap = @{}
foreach ($item in @($visibility.components)) { $componentMap[[string]$item.label] = $item }
foreach ($label in @("hair","eyes")) {
    if (-not $componentMap.ContainsKey($label) -or
        $componentMap[$label].present_in_avatar_bytes -ne $true -or
        $componentMap[$label].instantiated -ne $true -or
        $componentMap[$label].active_in_hierarchy -ne $true -or
        $componentMap[$label].visible_skinned_renderer -ne $true -or
        [int]$componentMap[$label].visible_renderer_count -lt 1) {
        throw "Retained preview completed without physically drawable $label evidence."
    }
}

$renderSet = Need-File -Path (Join-Path $retainedOutput "windows-preview\snapshots\fidelity-render-set.json") -Label "Retained preview fidelity render set"
$visibilitySha = Sha256 $visibilityPath
$renderSetSha = Sha256 $renderSet
$gapPlanPath = Join-Path $eveningRoot ("component-gap-plan-" + $visibilitySha.Substring(0,16) + "-" + $renderSetSha.Substring(0,16) + ".json")
if (Test-Path -LiteralPath $gapPlanPath -PathType Leaf) {
    Write-Host "Reusing component gap plan: $gapPlanPath"
} else {
    & $BodyRigPython -m bodyrig.fidelity_component_gap `
        --visibility-probe $visibilityPath `
        --render-set $renderSet `
        --out $gapPlanPath
    if ($LASTEXITCODE -ne 0) { throw "Physical component gap planning failed with exit code $LASTEXITCODE" }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
}
$gapPlan = Read-Json -Path $gapPlanPath -Label "Physical component gap plan"
if ([string]$gapPlan.bodyrig_revision -ne $head -or
    [string]$gapPlan.body_id -ne $bodyId -or
    [string]$gapPlan.package_sha256 -ne $selectedPackageSha -or
    [string]$gapPlan.state -notin @("composition-required", "machine-component-complete-human-review-required") -or
    $gapPlan.human_visual_authority_required -ne $true -or
    $gapPlan.production_activation -ne $false) {
    throw "Physical component gap plan is stale or crossed its machine-only authority boundary."
}
$gapPlanSha = Sha256 $gapPlanPath

Write-Host ""
Write-Host "=== 3/3 DIAGNOSTIC-ONLY V5 SCORE OF HAIR + EYE PREVIEW ==="
$diagnosticEvaluation = Join-Path $eveningRoot "hair-eye-diagnostic-v5-$selectedLabel.json"
if (Test-Path -LiteralPath $diagnosticEvaluation -PathType Leaf) {
    Write-Host "Reusing diagnostic-only evaluation: $diagnosticEvaluation"
} else {
    $referenceSet = Need-File -Path (Join-Path $WorkRoot "references\reference-set.json") -Label "Frozen fidelity reference set"
    $bodyReference = Resolve-BodyReference -BaselineEvaluation $baselineEvaluation.FullName -IdentityRootPath $IdentityRoot
    $rigSetup = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json") -Label "BodyRig rig setup"
    & $BodyRigPython -m bodyrig.fidelity_evaluator_cli `
        --rig-setup $rigSetup `
        --reference-set $referenceSet `
        --render-set $renderSet `
        --body-reference-rgba $bodyReference `
        --iteration 9001 `
        --allow-incomplete-component-comparison `
        --out $diagnosticEvaluation
    if ($LASTEXITCODE -ne 0) { throw "Diagnostic-only hair+eye evaluation failed with exit code $LASTEXITCODE" }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
}

$diagnostic = Read-Json -Path $diagnosticEvaluation -Label "Diagnostic-only hair+eye evaluation"
$summaryPath = Join-Path $eveningRoot "evening-review-summary.json"
$decisionSha = Sha256 $decisionPath
$retainedSummaryPath = Need-File -Path (Join-Path $retainedOutput "retained-hair-eye-preview.json") -Label "Retained preview summary"
$summary = [ordered]@{
    format = "bodyrig-fidelity-evening-review"
    version = 1
    bodyrig_revision = $head
    selected_iteration = $best
    selected_candidate = $selectedLabel
    selected_package_sha256 = $selectedPackageSha
    selected_identity_workspace = [string]$workspaceInfo.Path
    selected_reconstruction_sha256 = [string]$workspaceInfo.ReconstructionSha256
    v5_convergence_decision_sha256 = $decisionSha
    retained_preview_summary_sha256 = Sha256 $retainedSummaryPath
    component_visibility_probe_sha256 = $visibilitySha
    component_gap_render_set_sha256 = $renderSetSha
    component_gap_plan_sha256 = $gapPlanSha
    component_gap_state = [string]$gapPlan.state
    missing_components = @($gapPlan.missing_components)
    next_actions = @($gapPlan.next_actions)
    diagnostic_evaluation_sha256 = Sha256 $diagnosticEvaluation
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
    component_visibility = [ordered]@{
        hair = [bool]$componentMap["hair"].visible_skinned_renderer
        eyes = [bool]$componentMap["eyes"].visible_skinned_renderer
        face_secondary = $(if ($componentMap.ContainsKey("face-secondary")) { [bool]$componentMap["face-secondary"].visible_skinned_renderer } else { $false })
        fingernails = $(if ($componentMap.ContainsKey("fingernails")) { [bool]$componentMap["fingernails"].visible_skinned_renderer } else { $false })
        toenails = $(if ($componentMap.ContainsKey("toenails")) { [bool]$componentMap["toenails"].visible_skinned_renderer } else { $false })
    }
    full_fidelity_component_complete = [bool]$gapPlan.strict_machine_scoring_ready
    human_visual_authority_required = $true
    production_activation = $false
    semantics = "retained-physical-preview-plus-component-gap-plan-and-diagnostic-score-not-visual-or-release-acceptance"
}
if (Test-Path -LiteralPath $summaryPath -PathType Leaf) {
    $existing = Read-Json -Path $summaryPath -Label "Existing evening review summary"
    if ([string]$existing.bodyrig_revision -ne $head -or [string]$existing.selected_package_sha256 -ne $selectedPackageSha -or
        [string]$existing.component_visibility_probe_sha256 -ne $visibilitySha -or [string]$existing.component_gap_plan_sha256 -ne $gapPlanSha) {
        throw "Existing evening review summary targets different authority bytes; refusing overwrite."
    }
} else {
    $summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
}

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG EVENING REVIEW READY FOR HUMAN VISUAL QA"
Write-Host "Selected:       $selectedLabel (iteration $best)"
Write-Host "Overall diag:   $($diagnostic.measurement.scores.overall)"
Write-Host "Hair diag:      $($diagnostic.measurement.scores.hair_appearance)"
Write-Host "Face diag:      $($diagnostic.measurement.scores.face_appearance)"
Write-Host "Body diag:      $($diagnostic.measurement.scores.body_silhouette)"
Write-Host "Hair drawable:  $([bool]$componentMap['hair'].visible_skinned_renderer)"
Write-Host "Eyes drawable:  $([bool]$componentMap['eyes'].visible_skinned_renderer)"
Write-Host "Component state: $([string]$gapPlan.state)"
Write-Host "Missing:         $(@($gapPlan.missing_components) -join ', ')"
Write-Host "Machine ready:   $([bool]$gapPlan.strict_machine_scoring_ready)"
Write-Host "Human visual QA: REQUIRED"
Write-Host "Summary:        $summaryPath"
Write-Host "Snapshots:      $(Join-Path $retainedOutput 'windows-preview\snapshots')"
Write-Host "============================================================"

if ($OpenSnapshots) { Start-Process explorer.exe -ArgumentList @((Join-Path $retainedOutput "windows-preview\snapshots")) }
exit 0
