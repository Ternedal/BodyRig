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
function Test-V1Version {
    param($Value)
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
    if ((Get-Head -RepoRoot $RepoRoot) -ne $Expected) { throw "BodyRig checkout changed during current-floor evening review." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "BodyRig checkout became dirty during current-floor evening review." }
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
function Resolve-WorkspaceFromMarker {
    param([Parameter(Mandatory = $true)][string]$RebuildDir)
    $marker = Join-Path $RebuildDir "identity-workspace.txt"
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { return "" }
    $lines = @(Get-Content -LiteralPath $marker -Encoding UTF8 | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    if ($lines.Count -ne 1) { throw "Identity-workspace marker must contain exactly one non-empty path: $marker" }
    return Need-Directory -Path $lines[0] -Label "Retained identity workspace marker target"
}
function Resolve-WorkspaceByReconstructionHash {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$ExpectedSha256)
    $wanted = Need-Sha256 -Value $ExpectedSha256 -Label "Expected reconstruction SHA-256"
    $matches = @(
        Get-ChildItem -LiteralPath $Root -Directory -ErrorAction Stop | ForEach-Object {
            $candidate = Join-Path $_.FullName "sith-input-v1\reconstruction.json"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -eq $wanted) { $_.FullName }
            }
        }
    )
    if ($matches.Count -ne 1) { throw "Expected exactly one retained identity workspace for reconstruction $wanted; found $($matches.Count)." }
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
        $workspace = Need-Directory -Path $Explicit -Label "Explicit retained identity workspace"
    } else {
        $workspace = Resolve-WorkspaceFromMarker -RebuildDir (Join-Path $WorkRootPath ("rebuild-{0:D2}" -f $RebuildNumber))
        if ([string]::IsNullOrWhiteSpace($workspace) -and -not [string]::IsNullOrWhiteSpace($ExpectedReconstructionSha256)) {
            $workspace = Resolve-WorkspaceByReconstructionHash -Root $IdentityRootPath -ExpectedSha256 $ExpectedReconstructionSha256
        }
        if ([string]::IsNullOrWhiteSpace($workspace)) {
            throw "Could not resolve rebuild-$('{0:D2}' -f $RebuildNumber) retained identity workspace; pass it explicitly."
        }
    }
    $reconstruction = Need-File -Path (Join-Path $workspace "sith-input-v1\reconstruction.json") -Label "Retained reconstruction"
    $sha = Sha256 $reconstruction
    if (-not [string]::IsNullOrWhiteSpace($ExpectedReconstructionSha256) -and $sha -ne (Need-Sha256 -Value $ExpectedReconstructionSha256 -Label "Expected reconstruction SHA-256")) {
        throw "Resolved retained workspace reconstruction differs from candidate authority."
    }
    return [pscustomobject]@{ Path = $workspace; ReconstructionSha256 = $sha }
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
function Get-ExactIteration {
    param([Parameter(Mandatory = $true)]$Value)
    if ($Value -is [bool] -or $Value -isnot [ValueType]) { throw "V5 best_iteration must be an exact numeric iteration." }
    try { $number = [decimal]$Value } catch { throw "V5 best_iteration must be numeric." }
    if ($number -notin @([decimal]1,[decimal]2,[decimal]3)) { throw "V5 convergence selected unsupported best iteration: $Value" }
    return [int]$number
}
function Test-RefreshComplete {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [Parameter(Mandatory = $true)][string]$ExpectedReconstructionSha,
        [Parameter(Mandatory = $true)][string]$ExpectedSourcePackageSha,
        [Parameter(Mandatory = $true)][string]$ExpectedBodyAlias,
        [string]$ExpectedAdjustmentEvidenceSha = ""
    )
    $receiptPath = Join-Path $Path "retained-fidelity-package-refresh.json"
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { return $false }
    try { $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40 } catch { return $false }
    if ([string]$receipt.bodyrig_revision -ne $ExpectedHead -or [string]$receipt.refreshed_builder_revision -ne $ExpectedHead -or
        [string]$receipt.reconstruction_sha256 -ne $ExpectedReconstructionSha -or [string]$receipt.source_package_sha256 -ne $ExpectedSourcePackageSha -or
        [string]$receipt.body_alias -ne $ExpectedBodyAlias -or [string]$receipt.adjustment_evidence_sha256 -ne $ExpectedAdjustmentEvidenceSha -or
        $receipt.expensive_reconstruction_rerun -ne $false -or $receipt.fitter_rerun -ne $true -or
        $receipt.comparison_only -ne $true -or $receipt.human_visual_authority_required -ne $true -or $receipt.production_activation -ne $false) { return $false }
    $packages = @(Get-ChildItem -LiteralPath $Path -Filter "*.mrbody" -File -ErrorAction SilentlyContinue)
    if ($packages.Count -ne 1) { return $false }
    return (Sha256 $packages[0].FullName) -eq [string]$receipt.refreshed_package_sha256
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
function Test-FaceSecondaryPreviewComplete {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [Parameter(Mandatory = $true)][string]$ExpectedSourcePackageSha,
        [Parameter(Mandatory = $true)][string]$ExpectedHairEyeReceiptSha,
        [Parameter(Mandatory = $true)][string]$ExpectedHairEyeVrmSha
    )
    $summaryPath = Join-Path $Path "face-secondary-hair-eye-preview.json"
    $comparisonPackage = Join-Path $Path "comparison\face-secondary-hair-eye-comparison.mrbody"
    $comparisonReceipt = Join-Path $Path "comparison\face-secondary-hair-eye-comparison.json"
    $visibilityPath = Join-Path $Path "windows-preview\component-visibility-probe.json"
    $renderSetPath = Join-Path $Path "windows-preview\snapshots\fidelity-render-set.json"
    $gapPath = Join-Path $Path "component-gap-plan.json"
    foreach ($required in @($summaryPath,$comparisonPackage,$comparisonReceipt,$visibilityPath,$renderSetPath,$gapPath)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { return $false }
    }
    try { $summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40 } catch { return $false }
    if ([string]$summary.format -ne "bodyrig-face-secondary-hair-eye-windows-preview" -or -not (Test-V1Version $summary.version) -or
        [string]$summary.bodyrig_revision -ne $ExpectedHead -or [string]$summary.source_package_sha256 -ne $ExpectedSourcePackageSha -or
        [string]$summary.source_hair_eye_runtime_receipt_sha256 -ne $ExpectedHairEyeReceiptSha -or
        [string]$summary.source_hair_eye_review_vrm_sha256 -ne $ExpectedHairEyeVrmSha -or
        $summary.source_hair_preserved -ne $true -or $summary.source_eye_surface_preserved -ne $true -or
        $summary.face_secondary_drawable -ne $true -or $summary.comparison_only -ne $true -or
        $summary.physical_acceptance_authority -ne $false -or $summary.human_visual_authority_required -ne $true -or
        $summary.package_promotion_authority -ne $false -or $summary.production_activation -ne $false) { return $false }
    if ([string]$summary.comparison_package_sha256 -ne (Sha256 $comparisonPackage) -or
        [string]$summary.comparison_receipt_sha256 -ne (Sha256 $comparisonReceipt) -or
        [string]$summary.component_visibility_probe_sha256 -ne (Sha256 $visibilityPath) -or
        [string]$summary.render_set_sha256 -ne (Sha256 $renderSetPath) -or [string]$summary.gap_plan_sha256 -ne (Sha256 $gapPath)) { return $false }
    $drawable = @($summary.drawable_components | ForEach-Object { [string]$_ })
    foreach ($required in @("hair","eyes","face-secondary")) { if (-not ($drawable -contains $required)) { return $false } }
    return $true
}
function Assert-SemanticallyEqualJson {
    param([Parameter(Mandatory = $true)]$Expected,[Parameter(Mandatory = $true)]$Actual,[Parameter(Mandatory = $true)][string]$Label)
    $expectedText = $Expected | ConvertTo-Json -Depth 50 -Compress
    $actualText = $Actual | ConvertTo-Json -Depth 50 -Compress
    if ($expectedText -ne $actualText) { throw "$Label differs from freshly recomputed authority; refusing stale/tampered reuse." }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig current-floor evening review is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Current-floor evening review must be launched from the canonical main checkout."
}
$head = Get-Head -RepoRoot $repoRoot
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Current-floor evening review requires an exact clean BodyRig checkout." }

$WorkRoot = Need-Directory -Path $WorkRoot -Label "Fidelity convergence work root"
if ([string]::IsNullOrWhiteSpace($IdentityRoot)) {
    if ([string]::IsNullOrWhiteSpace([string]$env:LOCALAPPDATA)) { throw "LOCALAPPDATA is unavailable; pass -IdentityRoot explicitly." }
    $IdentityRoot = Join-Path $env:LOCALAPPDATA "BodyRig\identity-workspaces"
}
$IdentityRoot = Need-Directory -Path $IdentityRoot -Label "BodyRig identity-workspaces root"
$BodyRigPython = Resolve-BodyRigPython -RepoRoot $repoRoot -Requested $BodyRigPython
Assert-CheckoutBoundPython -RepoRoot $repoRoot -Python $BodyRigPython

$v5Review = Need-File -Path (Join-Path $repoRoot "run-fidelity-v5-review.ps1") -Label "V5 historical review runner"
$refreshRunner = Need-File -Path (Join-Path $repoRoot "refresh-retained-fidelity-candidate.ps1") -Label "Current-floor retained package refresh runner"
$retainedPreview = Need-File -Path (Join-Path $repoRoot "run-retained-hair-eye-preview.ps1") -Label "Retained hair+eye preview runner"
$faceSecondaryPreview = Need-File -Path (Join-Path $repoRoot "run-face-secondary-hair-eye-windows-preview.ps1") -Label "Face-secondary on retained hair+eye preview runner"
$tag = $head.Substring(0, 8)
$reanalysisRoot = Join-Path $WorkRoot "reanalysis-v5-$tag"
$decisionPath = Join-Path $reanalysisRoot "convergence-decision.json"
$baselineEvaluation = Get-ChildItem -Path (Join-Path $WorkRoot "rebuild-01\full\fidelity-evaluation-resumed-*.json") -File -ErrorAction Stop | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $baselineEvaluation) { throw "Historical baseline fidelity evaluation was not found." }

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG CURRENT-FLOOR EVENING FIDELITY REVIEW"
Write-Host "Revision:            $head"
Write-Host "Work root:           $WorkRoot"
Write-Host "SiTH reconstruction: NEVER STARTED BY THIS RUNNER"
Write-Host "Current-floor fitter/repackage: ALLOWED"
Write-Host "Production:          FALSE"
Write-Host "============================================================"

Write-Host ""
Write-Host "=== 1/4 HISTORICAL V5 SELECTION ==="
& $v5Review -WorkRoot $WorkRoot -BodyRigPython $BodyRigPython
if ($LASTEXITCODE -ne 0) { throw "V5 historical review failed with exit code $LASTEXITCODE" }
Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
$decision = Read-Json -Path $decisionPath -Label "V5 convergence decision"
$best = Get-ExactIteration -Value $decision.best_iteration

$session1 = Read-Json -Path (Join-Path $WorkRoot "rebuild-01\physical-session.json") -Label "Rebuild 1 physical session"
if ([string]$session1.status -ne "pass" -or [string]$session1.stage -ne "complete") { throw "Rebuild 1 physical session is not a completed PASS." }
$bodyAlias = ([string]$session1.body_id).Trim()
if ($bodyAlias -notmatch '^[a-z0-9æøå_-]{1,160}$') { throw "Rebuild 1 body alias is invalid." }
$baselineClone = Need-Directory -Path ([string]$session1.clone_output) -Label "Rebuild 1 clone output"
$baselinePackage = Need-File -Path (Join-Path $baselineClone "clone\$bodyAlias.mrbody") -Label "Historical baseline package"
$baselinePackageSha = Sha256 $baselinePackage
$refitRoot = Join-Path $WorkRoot "rebuild-01\night-refinement-01\refit"
$refitPackage = Need-File -Path (Join-Path $refitRoot "$bodyAlias.mrbody") -Label "Historical refit 1 package"
$refitResult = Read-Json -Path (Join-Path $refitRoot "refit-result.json") -Label "Historical refit 1 result"
$rebuild1ReconstructionSha = Need-Sha256 -Value ([string]$refitResult.reconstruction_authority_sha256) -Label "Rebuild 1 reconstruction SHA-256"
$historicalAdjustmentEvidence = Need-File -Path (Join-Path $refitRoot "bodyrig-bodyprint-adjustment.json") -Label "Historical proof-bound refit adjustment evidence"
$historicalAdjustmentEvidenceSha = Need-Sha256 -Value ([string]$refitResult.adjustment_evidence_sha256) -Label "Historical refit adjustment evidence SHA-256"
if ((Sha256 $historicalAdjustmentEvidence) -ne $historicalAdjustmentEvidenceSha) { throw "Historical refit adjustment evidence bytes differ from refit-result authority." }

$selectedLabel = ""
$historicalPackage = ""
$selectedEvaluation = ""
$refreshClone = ""
$refreshSourcePackageSha = ""
$selectedAdjustmentEvidence = ""
$workspaceInfo = $null
switch ($best) {
    1 {
        $selectedLabel = "baseline"
        $historicalPackage = $baselinePackage
        $selectedEvaluation = Need-File -Path (Join-Path $reanalysisRoot "iteration-01-baseline.json") -Label "V5 baseline evaluation"
        $refreshClone = $baselineClone
        $refreshSourcePackageSha = $baselinePackageSha
        $workspaceInfo = Resolve-Workspace -RebuildNumber 1 -Explicit $Rebuild1IdentityWorkspace -ExpectedReconstructionSha256 $rebuild1ReconstructionSha -WorkRootPath $WorkRoot -IdentityRootPath $IdentityRoot
    }
    2 {
        $selectedLabel = "refit1"
        $historicalPackage = $refitPackage
        $selectedEvaluation = Need-File -Path (Join-Path $reanalysisRoot "iteration-02-refit1.json") -Label "V5 refit 1 evaluation"
        $refreshClone = $baselineClone
        $refreshSourcePackageSha = $baselinePackageSha
        $selectedAdjustmentEvidence = $historicalAdjustmentEvidence
        $workspaceInfo = Resolve-Workspace -RebuildNumber 1 -Explicit $Rebuild1IdentityWorkspace -ExpectedReconstructionSha256 $rebuild1ReconstructionSha -WorkRootPath $WorkRoot -IdentityRootPath $IdentityRoot
    }
    3 {
        $session2 = Read-Json -Path (Join-Path $WorkRoot "rebuild-02\physical-session.json") -Label "Rebuild 2 physical session"
        if ([string]$session2.status -ne "pass" -or [string]$session2.stage -ne "complete" -or [string]$session2.body_id -ne $bodyAlias) {
            throw "Rebuild 2 physical session is not a completed PASS for the same body alias."
        }
        $refreshClone = Need-Directory -Path ([string]$session2.clone_output) -Label "Rebuild 2 clone output"
        $selectedLabel = "reconstruction2"
        $historicalPackage = Need-File -Path (Join-Path $refreshClone "clone\$bodyAlias.mrbody") -Label "Historical reconstruction 2 package"
        $refreshSourcePackageSha = Sha256 $historicalPackage
        $selectedEvaluation = Need-File -Path (Join-Path $reanalysisRoot "iteration-03-reconstruction2.json") -Label "V5 reconstruction 2 evaluation"
        $workspaceInfo = Resolve-Workspace -RebuildNumber 2 -Explicit $Rebuild2IdentityWorkspace -ExpectedReconstructionSha256 "" -WorkRootPath $WorkRoot -IdentityRootPath $IdentityRoot
    }
}

$selectedEval = Read-Json -Path $selectedEvaluation -Label "Selected historical V5 evaluation"
$expectedCandidateSha = Need-Sha256 -Value ([string]$selectedEval.measurement.candidate_sha256) -Label "Selected evaluator candidate SHA-256"
$historicalPackageSha = Sha256 $historicalPackage
if ($historicalPackageSha -ne $expectedCandidateSha) { throw "Historical selected package bytes differ from the candidate bytes scored by V5." }

$eveningRoot = Join-Path $WorkRoot "evening-current-floor-$tag"
if (-not (Test-Path -LiteralPath $eveningRoot -PathType Container)) { New-Item -ItemType Directory -Path $eveningRoot | Out-Null }
$refreshRoot = Join-Path $eveningRoot "current-floor-$selectedLabel"
$expectedAdjustmentEvidenceSha = $(if ($best -eq 2) { $historicalAdjustmentEvidenceSha } else { "" })

Write-Host ""
Write-Host "=== 2/4 CURRENT-FLOOR REFIT/REPACKAGE (NO SITH RECONSTRUCTION) ==="
Write-Host "Historical selection: $selectedLabel | iteration=$best | SHA=$historicalPackageSha"
Write-Host "Workspace:            $($workspaceInfo.Path)"
Write-Host "Reconstruction SHA:   $($workspaceInfo.ReconstructionSha256)"
$refreshComplete = Test-RefreshComplete -Path $refreshRoot -ExpectedHead $head -ExpectedReconstructionSha ([string]$workspaceInfo.ReconstructionSha256) -ExpectedSourcePackageSha $refreshSourcePackageSha -ExpectedBodyAlias $bodyAlias -ExpectedAdjustmentEvidenceSha $expectedAdjustmentEvidenceSha
if (-not $refreshComplete) {
    if (Test-Path -LiteralPath $refreshRoot) { throw "Current-floor refresh output exists but is incomplete or stale: $refreshRoot" }
    $refreshArgs = @{
        BaselineCloneOutput = $refreshClone
        IdentityWorkspace = [string]$workspaceInfo.Path
        OutputDir = $refreshRoot
        BodyRigPython = $BodyRigPython
    }
    if ($best -eq 2) { $refreshArgs.AdjustmentEvidence = $selectedAdjustmentEvidence }
    & $refreshRunner @refreshArgs
    if ($LASTEXITCODE -ne 0) { throw "Current-floor retained package refresh failed with exit code $LASTEXITCODE" }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
    if (-not (Test-RefreshComplete -Path $refreshRoot -ExpectedHead $head -ExpectedReconstructionSha ([string]$workspaceInfo.ReconstructionSha256) -ExpectedSourcePackageSha $refreshSourcePackageSha -ExpectedBodyAlias $bodyAlias -ExpectedAdjustmentEvidenceSha $expectedAdjustmentEvidenceSha)) {
        throw "Current-floor package refresh returned without complete authority evidence."
    }
} else {
    Write-Host "Reusing complete current-floor package refresh: $refreshRoot"
}
$refreshReceiptPath = Need-File -Path (Join-Path $refreshRoot "retained-fidelity-package-refresh.json") -Label "Current-floor refresh receipt"
$refreshReceipt = Read-Json -Path $refreshReceiptPath -Label "Current-floor refresh receipt"
$currentPackages = @(Get-ChildItem -LiteralPath $refreshRoot -Filter "*.mrbody" -File)
if ($currentPackages.Count -ne 1) { throw "Current-floor refresh must contain exactly one .mrbody package." }
$currentPackage = $currentPackages[0].FullName
$currentPackageSha = Sha256 $currentPackage
if ($currentPackageSha -ne [string]$refreshReceipt.refreshed_package_sha256 -or [string]$refreshReceipt.refreshed_builder_revision -ne $head) {
    throw "Current-floor package bytes/revision differ from refresh authority."
}
if ([string]$refreshReceipt.source_package_sha256 -ne $refreshSourcePackageSha) { throw "Current-floor refresh does not bind the exact selected source package lineage." }
if ([string]$refreshReceipt.adjustment_evidence_sha256 -ne $expectedAdjustmentEvidenceSha) { throw "Current-floor refresh does not preserve the selected adjustment evidence authority." }

$retainedOutput = Join-Path $eveningRoot "retained-hair-eye-$selectedLabel"
Write-Host ""
Write-Host "=== 3/4 CURRENT-FLOOR RETAINED HAIR + EYE PHYSICAL PREVIEW ==="
Write-Host "Current package SHA: $currentPackageSha"
if (Test-RetainedPreviewComplete -Path $retainedOutput) {
    Write-Host "Reusing complete retained preview: $retainedOutput"
} else {
    if (Test-Path -LiteralPath $retainedOutput) { throw "Retained preview output exists but is incomplete; refusing overwrite: $retainedOutput" }
    $previewArgs = @{
        PackagePath = $currentPackage
        IdentityWorkspace = [string]$workspaceInfo.Path
        OutputRoot = $retainedOutput
        BodyRigPython = $BodyRigPython
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $previewArgs.UnityExe = $UnityExe }
    if ($SkipBuild) { $previewArgs.SkipBuild = $true }
    & $retainedPreview @previewArgs
    if ($LASTEXITCODE -ne 0) { throw "Current-floor retained hair+eye preview failed with exit code $LASTEXITCODE" }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
    if (-not (Test-RetainedPreviewComplete -Path $retainedOutput)) { throw "Retained preview returned without complete physical evidence." }
}

$visibilityPath = Need-File -Path (Join-Path $retainedOutput "windows-preview\component-visibility-probe.json") -Label "Physical component visibility probe"
$renderSet = Need-File -Path (Join-Path $retainedOutput "windows-preview\snapshots\fidelity-render-set.json") -Label "Current-floor retained preview render set"
$diagnosticRenderSet = $renderSet
$gapProbeCode = @'
import json,pathlib,sys
from bodyrig.fidelity_component_gap import build_gap_plan
visibility=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
render=json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
print(json.dumps(build_gap_plan(visibility,render_set=render),separators=(",",":"),allow_nan=False))
'@
$gapRaw = @(& $BodyRigPython -c $gapProbeCode $visibilityPath $renderSet 2>&1)
if ($LASTEXITCODE -ne 0 -or $gapRaw.Count -ne 1) { throw "Current-floor physical component evidence failed canonical gap validation: $($gapRaw -join ' ')" }
try { $gap = ([string]$gapRaw[0]) | ConvertFrom-Json -Depth 30 } catch { throw "Canonical component-gap validation returned unreadable JSON." }
if ([string]$gap.package_sha256 -ne $currentPackageSha -or [string]$gap.bodyrig_revision -ne $head) { throw "Component gap authority targets different current-floor bytes/revision." }
$drawable = @($gap.drawable_components | ForEach-Object { [string]$_ })
if (-not ($drawable -contains "hair") -or -not ($drawable -contains "eyes")) { throw "Current-floor retained preview lacks physically drawable hair/eyes authority." }

$physicalOutput = $retainedOutput
$physicalAuthorityKind = "retained-hair-eye"
$physicalAuthorityPackageSha = $currentPackageSha
$physicalComparisonPackageSha = ""
$faceSecondarySummaryPath = ""
if (-not ($drawable -contains "face-secondary")) {
    Write-Host ""
    Write-Host "=== 3B/4 CURRENT-FLOOR FACE-SECONDARY PHYSICAL COMPARISON ==="
    $hairEyeRuntimeDir = Need-Directory -Path (Join-Path $retainedOutput "runtime") -Label "Retained hair+eye runtime"
    $hairEyeReceiptPath = Need-File -Path (Join-Path $hairEyeRuntimeDir "source-hair-eye-review-runtime.json") -Label "Retained hair+eye runtime receipt"
    $hairEyeVrmPath = Need-File -Path (Join-Path $hairEyeRuntimeDir "source-hair-eye-review.vrm") -Label "Retained hair+eye review VRM"
    $hairEyeReceiptSha = Sha256 $hairEyeReceiptPath
    $hairEyeVrmSha = Sha256 $hairEyeVrmPath
    $faceSecondaryOutput = Join-Path $eveningRoot "face-secondary-hair-eye-$selectedLabel"
    $faceComplete = Test-FaceSecondaryPreviewComplete -Path $faceSecondaryOutput -ExpectedHead $head -ExpectedSourcePackageSha $currentPackageSha -ExpectedHairEyeReceiptSha $hairEyeReceiptSha -ExpectedHairEyeVrmSha $hairEyeVrmSha
    if (-not $faceComplete) {
        if (Test-Path -LiteralPath $faceSecondaryOutput) { throw "Face-secondary current-floor output exists but is incomplete/stale; refusing overwrite: $faceSecondaryOutput" }
        $faceArgs = @{
            PackagePath = $currentPackage
            HairEyeRuntimeDir = $hairEyeRuntimeDir
            OutputDir = $faceSecondaryOutput
            BodyRigPython = $BodyRigPython
        }
        if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $faceArgs.UnityExe = $UnityExe }
        if ($SkipBuild) { $faceArgs.SkipBuild = $true }
        & $faceSecondaryPreview @faceArgs
        if ($LASTEXITCODE -ne 0) { throw "Current-floor face-secondary comparison failed with exit code $LASTEXITCODE" }
        Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
        if (-not (Test-FaceSecondaryPreviewComplete -Path $faceSecondaryOutput -ExpectedHead $head -ExpectedSourcePackageSha $currentPackageSha -ExpectedHairEyeReceiptSha $hairEyeReceiptSha -ExpectedHairEyeVrmSha $hairEyeVrmSha)) {
            throw "Face-secondary comparison returned without complete hash-bound physical evidence."
        }
    } else {
        Write-Host "Reusing complete face-secondary physical comparison: $faceSecondaryOutput"
    }
    $faceSecondarySummaryPath = Need-File -Path (Join-Path $faceSecondaryOutput "face-secondary-hair-eye-preview.json") -Label "Face-secondary physical comparison summary"
    $faceSummary = Read-Json -Path $faceSecondarySummaryPath -Label "Face-secondary physical comparison summary"
    $physicalAuthorityKind = "face-secondary-hair-eye-comparison"
    $physicalAuthorityPackageSha = Need-Sha256 -Value ([string]$faceSummary.comparison_package_sha256) -Label "Face-secondary comparison package SHA-256"
    $physicalComparisonPackageSha = $physicalAuthorityPackageSha
    $physicalOutput = $faceSecondaryOutput
    $visibilityPath = Need-File -Path (Join-Path $faceSecondaryOutput "windows-preview\component-visibility-probe.json") -Label "Face-secondary component visibility probe"
    $renderSet = Need-File -Path (Join-Path $faceSecondaryOutput "windows-preview\snapshots\fidelity-render-set.json") -Label "Face-secondary physical render set"
    $finalGapPath = Need-File -Path (Join-Path $faceSecondaryOutput "component-gap-plan.json") -Label "Face-secondary component gap plan"
    $gap = Read-Json -Path $finalGapPath -Label "Face-secondary component gap plan"
    if ([string]$gap.package_sha256 -ne $physicalAuthorityPackageSha -or [string]$gap.bodyrig_revision -ne $head -or
        $gap.human_visual_authority_required -ne $true -or $gap.production_activation -ne $false) {
        throw "Face-secondary component gap authority targets different comparison bytes/revision or crossed authority."
    }
    $drawable = @($gap.drawable_components | ForEach-Object { [string]$_ })
    foreach ($required in @("hair","eyes","face-secondary")) {
        if (-not ($drawable -contains $required)) { throw "Face-secondary current-floor comparison lacks physically drawable $required evidence." }
    }
}

$visibility = Read-Json -Path $visibilityPath -Label "Final physical component visibility probe"
$componentMap = @{}
foreach ($item in @($visibility.components)) { $componentMap[[string]$item.label] = $item }

Write-Host ""
Write-Host "=== 4/4 DIAGNOSTIC-ONLY V5 SCORE OF CURRENT-FLOOR HAIR + EYE PREVIEW ==="
$diagnosticEvaluation = Join-Path $eveningRoot "hair-eye-diagnostic-v5-$selectedLabel.json"
$diagnosticAttempt = Join-Path $eveningRoot (".hair-eye-diagnostic-v5-$selectedLabel.verify-" + [Guid]::NewGuid().ToString("N") + ".json")
$referenceSet = Need-File -Path (Join-Path $WorkRoot "references\reference-set.json") -Label "Frozen fidelity reference set"
$bodyReference = Resolve-BodyReference -BaselineEvaluation $baselineEvaluation.FullName -IdentityRootPath $IdentityRoot
$rigSetup = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json") -Label "BodyRig rig setup"
try {
    & $BodyRigPython -m bodyrig.fidelity_evaluator_cli `
        --rig-setup $rigSetup `
        --reference-set $referenceSet `
        --render-set $diagnosticRenderSet `
        --body-reference-rgba $bodyReference `
        --iteration 9001 `
        --allow-incomplete-component-comparison `
        --out $diagnosticAttempt
    if ($LASTEXITCODE -ne 0) { throw "Diagnostic-only current-floor hair+eye evaluation failed with exit code $LASTEXITCODE" }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
    $freshDiagnostic = Read-Json -Path $diagnosticAttempt -Label "Freshly recomputed diagnostic evaluation"
    if (Test-Path -LiteralPath $diagnosticEvaluation -PathType Leaf) {
        $existingDiagnostic = Read-Json -Path $diagnosticEvaluation -Label "Existing diagnostic-only current-floor evaluation"
        Assert-SemanticallyEqualJson -Expected $freshDiagnostic -Actual $existingDiagnostic -Label "Existing diagnostic evaluation"
        Write-Host "Revalidated existing diagnostic-only evaluation: $diagnosticEvaluation"
    } else {
        Move-Item -LiteralPath $diagnosticAttempt -Destination $diagnosticEvaluation
        $diagnosticAttempt = ""
    }
} finally {
    if (-not [string]::IsNullOrWhiteSpace($diagnosticAttempt) -and (Test-Path -LiteralPath $diagnosticAttempt -PathType Leaf)) { Remove-Item -LiteralPath $diagnosticAttempt -Force -ErrorAction SilentlyContinue }
}

$diagnostic = Read-Json -Path $diagnosticEvaluation -Label "Diagnostic-only current-floor hair+eye evaluation"
if ((Need-Sha256 -Value ([string]$diagnostic.measurement.candidate_sha256) -Label "Diagnostic candidate SHA-256") -ne $currentPackageSha) {
    throw "Diagnostic evaluation targets different current-floor package bytes."
}
$summaryPath = Join-Path $eveningRoot "evening-review-summary.json"
$summary = [ordered]@{
    format = "bodyrig-fidelity-current-floor-evening-review"
    version = 1
    bodyrig_revision = $head
    selected_iteration = $best
    selected_candidate = $selectedLabel
    historical_selected_package_sha256 = $historicalPackageSha
    source_current_floor_package_sha256 = $currentPackageSha
    current_floor_package_sha256 = $currentPackageSha
    selected_package_sha256 = $currentPackageSha
    package_refresh_receipt_sha256 = Sha256 $refreshReceiptPath
    selected_identity_workspace = [string]$workspaceInfo.Path
    selected_reconstruction_sha256 = [string]$workspaceInfo.ReconstructionSha256
    v5_historical_selection_decision_sha256 = Sha256 $decisionPath
    retained_preview_summary_sha256 = Sha256 (Need-File -Path (Join-Path $retainedOutput "retained-hair-eye-preview.json") -Label "Retained preview summary")
    face_secondary_preview_summary_sha256 = $(if ([string]::IsNullOrWhiteSpace($faceSecondarySummaryPath)) { "" } else { Sha256 $faceSecondarySummaryPath })
    physical_authority_kind = $physicalAuthorityKind
    physical_component_authority_package_sha256 = $physicalAuthorityPackageSha
    physical_component_package_sha256 = $physicalAuthorityPackageSha
    physical_comparison_package_sha256 = $physicalComparisonPackageSha
    component_visibility_probe_sha256 = Sha256 $visibilityPath
    physical_component_visibility_probe_sha256 = Sha256 $visibilityPath
    component_gap_render_set_sha256 = Sha256 $renderSet
    physical_render_set_sha256 = Sha256 $renderSet
    diagnostic_render_set_sha256 = Sha256 $diagnosticRenderSet
    diagnostic_evaluation_sha256 = Sha256 $diagnosticEvaluation
    current_floor_refit_repackage = $true
    expensive_reconstruction_rerun = $false
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
        hair = $drawable -contains "hair"
        eyes = $drawable -contains "eyes"
        face_secondary = $drawable -contains "face-secondary"
        fingernails = $drawable -contains "fingernails"
        toenails = $drawable -contains "toenails"
    }
    full_fidelity_component_complete = [bool]$visibility.all_required_present_and_visible
    physical_acceptance_authority = $false
    human_visual_authority_required = $true
    production_activation = $false
    semantics = "current-floor-component-continuation-physical-preview-plus-source-package-diagnostic-score-not-full-fidelity-acceptance"
}
if (Test-Path -LiteralPath $summaryPath -PathType Leaf) {
    $existing = Read-Json -Path $summaryPath -Label "Existing current-floor evening review summary"
    Assert-SemanticallyEqualJson -Expected $summary -Actual $existing -Label "Existing current-floor evening review summary"
} else {
    $summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
}

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG CURRENT-FLOOR EVENING REVIEW READY FOR HUMAN QA"
Write-Host "Selected history: $selectedLabel (iteration $best)"
Write-Host "Historical SHA:   $historicalPackageSha"
Write-Host "Current-floor SHA:$currentPackageSha"
Write-Host "Overall diag:     $($diagnostic.measurement.scores.overall)"
Write-Host "Hair diag:        $($diagnostic.measurement.scores.hair_appearance)"
Write-Host "Face diag:        $($diagnostic.measurement.scores.face_appearance)"
Write-Host "Body diag:        $($diagnostic.measurement.scores.body_silhouette)"
Write-Host "Hair drawable:    $($drawable -contains 'hair')"
Write-Host "Eyes drawable:    $($drawable -contains 'eyes')"
Write-Host "Face drawable:    $($drawable -contains 'face-secondary')"
Write-Host "All 5 drawable:   $([bool]$visibility.all_required_present_and_visible)"
Write-Host "SiTH rerun:       FALSE"
Write-Host "Human QA:         REQUIRED"
Write-Host "Production:       FALSE"
Write-Host "Summary:          $summaryPath"
Write-Host "Snapshots:        $(Join-Path $physicalOutput 'windows-preview\snapshots')"
Write-Host "============================================================"

if ($OpenSnapshots) { Start-Process explorer.exe -ArgumentList @((Join-Path $physicalOutput "windows-preview\snapshots")) }
exit 0
