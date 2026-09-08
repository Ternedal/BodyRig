param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [string]$RunDir,

    [Parameter(Mandatory = $true)]
    [ValidateSet("left", "right", "tie", "reject-both")]
    [string]$Decision,

    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 4000)]
    [string]$QualityNote,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmVisualReview,

    [string]$BodyRigPython = ""
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
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40 }
    catch { throw "$Label is unreadable JSON: $Path" }
    if ($null -eq $value) { throw "$Label is empty: $Path" }
    return $value
}

function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not an exact Git revision." }
    return $normalized
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
}

function File-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Require-PlanBoundary {
    param([Parameter(Mandatory = $true)]$Value,[Parameter(Mandatory = $true)][string]$Label)
    if (
        $Value.comparison_only -ne $true -or
        $Value.human_visual_authority_required -ne $true -or
        $Value.physical_acceptance_authority -ne $false -or
        $Value.promotion_authority -ne $false -or
        $Value.production_activation -ne $false
    ) { throw "$Label crossed the comparison-only authority boundary." }
}

function Assert-CleanMain {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[Parameter(Mandatory = $true)][string]$ExpectedRevision)
    $branchRaw = @(& git -C $RepoRoot branch --show-current 2>&1)
    if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
        throw "Plan-bound PBR human review must be recorded from branch main."
    }
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = Need-Revision -Value ([string]$headRaw[0]) -Label "BodyRig HEAD"
    if ($head -ne $ExpectedRevision) { throw "BodyRig HEAD does not match the shared A/B baseline plan revision." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Plan-bound PBR human review requires an exact clean main checkout." }
}

function Refresh-ExactRefs {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$PbrRef,
        [Parameter(Mandatory = $true)][string]$MainRevision,
        [Parameter(Mandatory = $true)][string]$PbrRevision
    )
    $fetchMain = "+refs/heads/main:refs/remotes/origin/main"
    $fetchPbr = "+refs/heads/${PbrRef}:refs/remotes/origin/${PbrRef}"
    $raw = @(& git -C $RepoRoot fetch --no-tags origin $fetchMain $fetchPbr 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not refresh plan-bound PBR refs: $($raw -join ' ')" }
    $originMainRaw = @(& git -C $RepoRoot rev-parse refs/remotes/origin/main 2>&1)
    $originPbrRaw = @(& git -C $RepoRoot rev-parse "refs/remotes/origin/$PbrRef" 2>&1)
    if ($originMainRaw.Count -ne 1 -or $originPbrRaw.Count -ne 1) { throw "Could not resolve plan-bound PBR remote refs." }
    $originMain = Need-Revision -Value ([string]$originMainRaw[0]) -Label "origin/main"
    $originPbr = Need-Revision -Value ([string]$originPbrRaw[0]) -Label "origin PBR candidate"
    if ($originMain -ne $MainRevision) { throw "origin/main moved after the shared A/B baseline plan was created." }
    if ($originPbr -ne $PbrRevision) { throw "PBR candidate ref moved after the shared A/B baseline plan was created." }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite plan-bound PBR human-review authority: $Path" }
    $parent = Split-Path -Parent $Path
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig plan-bound PBR human review is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required for shared A/B plan authority." }
if (-not $ConfirmVisualReview) { throw "Pass -ConfirmVisualReview only after visually comparing all four canonical left/right snapshots." }
if ([string]::IsNullOrWhiteSpace($QualityNote) -or $QualityNote.Trim() -match '^<[^>]+>$') { throw "QualityNote must contain the operator's actual visual A/B assessment." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$RunDir = Need-Directory -Path $RunDir -Label "plan-bound PBR A/B run directory"
$planPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId.json") -Label "shared A/B baseline plan"
$contractPath = Need-File -Path (Join-Path $repoRoot "contracts\ab-baseline-candidates-v1.json") -Label "candidate byte contract"
$runAuthorityPath = Need-File -Path (Join-Path $RunDir "run-authority.json") -Label "PBR A/B run authority"
$sourceAuthorityPath = Need-File -Path (Join-Path $RunDir "body-job-source-authority.json") -Label "PBR body-job source authority"
$planAuthorityPath = Need-File -Path (Join-Path $RunDir "body-job-plan-authority.json") -Label "PBR body-job plan authority"
$machineAbPath = Need-File -Path (Join-Path $RunDir "machine-ab.json") -Label "PBR machine A/B evidence"
$leftRenderDir = Need-Directory -Path (Join-Path $RunDir "baseline-render") -Label "baseline render directory"
$rightRenderDir = Need-Directory -Path (Join-Path $RunDir "candidate-render") -Label "candidate render directory"
$humanReviewPath = Join-Path $RunDir "human-review.json"
$humanAuthorityPath = Join-Path $RunDir "plan-bound-human-review-authority.json"
if (Test-Path -LiteralPath $humanReviewPath) { throw "Human A/B review already exists: $humanReviewPath" }
if (Test-Path -LiteralPath $humanAuthorityPath) { throw "Plan-bound PBR human-review authority already exists: $humanAuthorityPath" }

$plan = Read-Json -Path $planPath -Label "shared A/B baseline plan"
if ([string]$plan.format -ne "bodyrig-dual-candidate-ab-baseline-plan" -or [int]$plan.version -ne 1) { throw "Shared A/B baseline plan format/version mismatch." }
Require-PlanBoundary -Value $plan -Label "shared A/B baseline plan"
if ([string]$plan.baseline_job_id -ne $BaselineJobId -or [string]$plan.person_id -notmatch '^person-[0-9a-f]{32}$') { throw "Shared A/B baseline plan identity mismatch." }
$mainRevision = Need-Revision -Value ([string]$plan.baseline_bodyrig_revision) -Label "baseline plan main revision"
$pbrRef = [string]$plan.pbr_candidate.ref
$pbrRevision = Need-Revision -Value ([string]$plan.pbr_candidate.revision) -Label "baseline plan PBR revision"
$throughputRef = [string]$plan.throughput_candidate.ref
$throughputRevision = Need-Revision -Value ([string]$plan.throughput_candidate.revision) -Label "baseline plan throughput revision"
$contractSha = Need-Sha256 -Value ([string]$plan.candidate_contract_sha256) -Label "baseline plan candidate contract SHA"
$planSha = File-Sha256 -Path $planPath
if ((File-Sha256 -Path $contractPath) -ne $contractSha) { throw "Candidate byte contract bytes differ from the shared A/B baseline plan." }
if ([string]::IsNullOrWhiteSpace($pbrRef) -or [string]::IsNullOrWhiteSpace($throughputRef) -or $plan.pbr_candidate.retained_reconstruction_reuse -ne $true) { throw "Shared A/B baseline plan does not authorize retained PBR comparison reuse." }

Assert-CleanMain -RepoRoot $repoRoot -ExpectedRevision $mainRevision
Refresh-ExactRefs -RepoRoot $repoRoot -PbrRef $pbrRef -MainRevision $mainRevision -PbrRevision $pbrRevision

$runAuthority = Read-Json -Path $runAuthorityPath -Label "PBR A/B run authority"
if (
    [string]$runAuthority.format -ne "bodyrig-pbr-ab-run" -or [int]$runAuthority.version -ne 1 -or
    (Need-Revision -Value ([string]$runAuthority.baseline_revision) -Label "PBR run baseline revision") -ne $mainRevision -or
    (Need-Revision -Value ([string]$runAuthority.candidate_revision) -Label "PBR run candidate revision") -ne $pbrRevision -or
    $runAuthority.comparison_only -ne $true -or $runAuthority.physical_acceptance_authority -ne $false -or $runAuthority.production_activation -ne $false
) { throw "PBR run authority does not match the shared baseline plan." }

$sourceAuthority = Read-Json -Path $sourceAuthorityPath -Label "PBR body-job source authority"
if (
    [string]$sourceAuthority.format -ne "bodyrig-pbr-ab-body-job-source-authority" -or [int]$sourceAuthority.version -ne 1 -or
    [string]$sourceAuthority.body_job_id -ne $BaselineJobId -or [string]$sourceAuthority.person_id -ne [string]$plan.person_id -or
    (Need-Revision -Value ([string]$sourceAuthority.bodyrig_revision) -Label "PBR source authority revision") -ne $mainRevision -or
    (Need-Sha256 -Value ([string]$sourceAuthority.pbr_run_authority_sha256) -Label "PBR source run-authority SHA") -ne (File-Sha256 -Path $runAuthorityPath) -or
    $sourceAuthority.comparison_only -ne $true -or $sourceAuthority.human_visual_authority_required -ne $true -or
    $sourceAuthority.physical_acceptance_authority -ne $false -or $sourceAuthority.production_activation -ne $false
) { throw "PBR body-job source authority does not match this exact plan-bound run." }

$planAuthority = Read-Json -Path $planAuthorityPath -Label "PBR body-job plan authority"
if ([string]$planAuthority.format -ne "bodyrig-pbr-ab-body-job-plan-authority" -or [int]$planAuthority.version -ne 1) { throw "PBR body-job plan authority format/version mismatch." }
Require-PlanBoundary -Value $planAuthority -Label "PBR body-job plan authority"
if (
    (Need-Sha256 -Value ([string]$planAuthority.baseline_plan_sha256) -Label "PBR plan authority baseline-plan SHA") -ne $planSha -or
    (Need-Sha256 -Value ([string]$planAuthority.candidate_contract_sha256) -Label "PBR plan authority contract SHA") -ne $contractSha -or
    [string]$planAuthority.baseline_job_id -ne $BaselineJobId -or [string]$planAuthority.person_id -ne [string]$plan.person_id -or
    (Need-Revision -Value ([string]$planAuthority.baseline_revision) -Label "PBR plan authority baseline revision") -ne $mainRevision -or
    [string]$planAuthority.pbr_candidate_ref -ne $pbrRef -or
    (Need-Revision -Value ([string]$planAuthority.pbr_candidate_revision) -Label "PBR plan authority candidate revision") -ne $pbrRevision -or
    [string]$planAuthority.throughput_candidate_ref -ne $throughputRef -or
    (Need-Revision -Value ([string]$planAuthority.throughput_candidate_revision) -Label "PBR plan authority throughput revision") -ne $throughputRevision -or
    (Need-Sha256 -Value ([string]$planAuthority.run_authority_sha256) -Label "PBR plan run-authority SHA") -ne (File-Sha256 -Path $runAuthorityPath) -or
    (Need-Sha256 -Value ([string]$planAuthority.source_authority_sha256) -Label "PBR plan source-authority SHA") -ne (File-Sha256 -Path $sourceAuthorityPath)
) { throw "PBR body-job plan authority does not bind this exact shared plan and run." }

$stablePaths = @($planPath,$contractPath,$runAuthorityPath,$sourceAuthorityPath,$planAuthorityPath,$machineAbPath)
$stableHashes = @{}
foreach ($path in $stablePaths) { $stableHashes[$path] = File-Sha256 -Path $path }

$recorder = Need-File -Path (Join-Path $repoRoot "record-fidelity-ab-review.ps1") -Label "canonical fidelity A/B human review recorder"
$recordParams = @{
    AbEvidence = $machineAbPath
    LeftRenderDir = $leftRenderDir
    RightRenderDir = $rightRenderDir
    Decision = $Decision
    QualityNote = $QualityNote.Trim()
    ConfirmVisualReview = $true
    Output = $humanReviewPath
}
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $recordParams.BodyRigPython = $BodyRigPython }
& $recorder @recordParams
if ($LASTEXITCODE -ne 0) { throw "Canonical fidelity A/B human review recorder failed with exit code $LASTEXITCODE" }

$humanReviewPath = Need-File -Path $humanReviewPath -Label "PBR human review receipt"
Assert-CleanMain -RepoRoot $repoRoot -ExpectedRevision $mainRevision
Refresh-ExactRefs -RepoRoot $repoRoot -PbrRef $pbrRef -MainRevision $mainRevision -PbrRevision $pbrRevision
foreach ($path in $stablePaths) {
    if ((File-Sha256 -Path $path) -ne $stableHashes[$path]) {
        if (Test-Path -LiteralPath $humanReviewPath -PathType Leaf) { Remove-Item -LiteralPath $humanReviewPath -Force }
        throw "Plan-bound PBR evidence changed during human review; removed non-authoritative receipt: $path"
    }
}

$review = Read-Json -Path $humanReviewPath -Label "PBR human review receipt"
if (
    [string]$review.format -ne "bodyrig-fidelity-ab-human-review" -or [int]$review.version -ne 1 -or
    [string]$review.decision -ne $Decision -or [string]$review.quality_note -ne $QualityNote.Trim() -or
    (Need-Sha256 -Value ([string]$review.ab_evidence_sha256) -Label "human review A/B evidence SHA") -ne (File-Sha256 -Path $machineAbPath) -or
    (Need-Revision -Value ([string]$review.renderer_revision) -Label "human review renderer revision") -ne $mainRevision -or
    (Need-Revision -Value ([string]$review.review_bodyrig_revision) -Label "human review checkout revision") -ne $mainRevision -or
    (Need-Revision -Value ([string]$review.left.builder_revision) -Label "human review baseline builder revision") -ne $mainRevision -or
    (Need-Revision -Value ([string]$review.right.builder_revision) -Label "human review candidate builder revision") -ne $pbrRevision -or
    $review.clean_appearance_ab_verified -ne $true -or $review.human_visual_review_confirmed -ne $true -or
    $review.comparison_only -ne $true -or $review.physical_acceptance_authority -ne $false -or $review.production_activation -ne $false
) {
    Remove-Item -LiteralPath $humanReviewPath -Force
    throw "Human review receipt did not preserve exact shared-plan PBR authority; removed non-authoritative receipt."
}

$authority = [ordered]@{
    format = "bodyrig-pbr-plan-bound-human-review-authority"
    version = 1
    baseline_job_id = $BaselineJobId
    person_id = [string]$plan.person_id
    baseline_plan_sha256 = $planSha
    candidate_contract_sha256 = $contractSha
    baseline_revision = $mainRevision
    pbr_candidate_ref = $pbrRef
    pbr_candidate_revision = $pbrRevision
    throughput_candidate_ref = $throughputRef
    throughput_candidate_revision = $throughputRevision
    run_authority_sha256 = File-Sha256 -Path $runAuthorityPath
    source_authority_sha256 = File-Sha256 -Path $sourceAuthorityPath
    plan_authority_sha256 = File-Sha256 -Path $planAuthorityPath
    machine_ab_sha256 = File-Sha256 -Path $machineAbPath
    human_review_sha256 = File-Sha256 -Path $humanReviewPath
    decision = $Decision
    comparison_only = $true
    human_visual_authority_recorded = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}
try {
    Write-CreateOnlyJson -Path $humanAuthorityPath -Value $authority
    Assert-CleanMain -RepoRoot $repoRoot -ExpectedRevision $mainRevision
    Refresh-ExactRefs -RepoRoot $repoRoot -PbrRef $pbrRef -MainRevision $mainRevision -PbrRevision $pbrRevision
    foreach ($path in $stablePaths) {
        if ((File-Sha256 -Path $path) -ne $stableHashes[$path]) { throw "Plan-bound PBR evidence changed before terminal human-review authority publication: $path" }
    }
    if ((File-Sha256 -Path $humanReviewPath) -ne [string]$authority.human_review_sha256) { throw "Human review receipt changed before terminal authority publication." }
} catch {
    if (Test-Path -LiteralPath $humanAuthorityPath -PathType Leaf) { Remove-Item -LiteralPath $humanAuthorityPath -Force }
    if (Test-Path -LiteralPath $humanReviewPath -PathType Leaf) { Remove-Item -LiteralPath $humanReviewPath -Force }
    throw
}

Write-Host "BodyRig plan-bound PBR human review: RECORDED"
Write-Host "Baseline job:  $BaselineJobId"
Write-Host "Decision:      $Decision"
Write-Host "Human receipt: $humanReviewPath"
Write-Host "Plan authority:$humanAuthorityPath"
Write-Host "Authority: comparison-only human preference; no physical acceptance, promotion or production activation."
exit 0
