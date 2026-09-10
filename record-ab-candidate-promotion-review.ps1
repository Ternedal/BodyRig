param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [string]$PbrRunDir,

    [Parameter(Mandatory = $true)]
    [string]$ThroughputRunDir,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$PromotionNote,

    [Parameter(Mandatory = $true)]
    [switch]$PromotePbr,

    [Parameter(Mandatory = $true)]
    [switch]$PromoteThroughput,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmPromotion,

    [string]$RepoRoot = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBaselineRevision = '6e10351e4eba929062960ac46ec1582a467db259'
$ExpectedPbrRef = 'candidate/skin-pbr-v3-linear-light-20260909'
$ExpectedPbrRevision = 'fe2db94b8ae3be51938a7b302361bcf5fdec5f48'
$ExpectedFailedThroughputRef = 'candidate/recovery-throughput-v3-current-main-20260908'
$ExpectedFailedThroughputRevision = 'ec743446d98809d693d01e51830f435fc3c09535'
$ExpectedFixedThroughputRef = 'fix/throughput-v3-resume-signature-20260910'
$ExpectedFixedThroughputRevision = '5fa01deb08399fda64e83db1329d4d2e83ad1bc2'
$ExpectedFailedCandidateJobId = 'job-164250c1d8e04f66a8f8f6cf646c1a31'
$ExpectedCandidateJobId = 'job-56248d1b57164ce9b68ea8e5478b7f9d'
$ExpectedFailureSignature = "_load_canonical_checkpoint() got an unexpected keyword argument 'source_fps'"

$ExpectedPbrFiles = @(
    'bodyrig/bridges/sith_pbr_material.py',
    'tests/test_sith_basecolor_detail.py',
    'tests/test_sith_pbr_material.py'
)
$ExpectedThroughputFiles = @(
    'bodyrig/bridges/hmr2_checkpoint_bridge.py',
    'bodyrig/bridges/hmr2_config.py',
    'bodyrig/bridges/hmr2_resume_bridge.py',
    'bodyrig/recovery_throughput_human_review.py',
    'bodyrig/recovery_throughput_review_bundle.py',
    'bodyrig/recovery_throughput_sampling_audit.py',
    'build-recovery-throughput-review-bundle.ps1',
    'compare-recovery-throughput.ps1',
    'docs/RECOVERY_THROUGHPUT_AB.md',
    'record-recovery-throughput-human-review.ps1',
    'tests/test_compare_recovery_throughput_script.py',
    'tests/test_hmr2_cross_job_resume.py',
    'tests/test_hmr2_recovery_checkpoints.py',
    'tests/test_hmr2_resume_signature_regression.py',
    'tests/test_observation_throughput.py',
    'tests/test_recovery_throughput_ab_docs.py',
    'tests/test_recovery_throughput_review_chain.py',
    'tests/test_recovery_throughput_review_wrappers.py',
    'tests/test_recovery_throughput_sampling_audit.py'
)

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
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 70 }
    catch { throw "$Label is unreadable JSON: $Path" }
    if ($null -eq $value) { throw "$Label is empty: $Path" }
    return $value
}

function File-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $v = $Value.Trim().ToLowerInvariant()
    if ($v -notmatch '^[0-9a-f]{40}$') { throw "$Label is not an exact Git revision." }
    return $v
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $v = $Value.Trim().ToLowerInvariant()
    if ($v -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $v
}

function Assert-ComparisonBoundary {
    param([Parameter(Mandatory = $true)]$Value,[Parameter(Mandatory = $true)][string]$Label,[switch]$PromotionFieldOptional)
    if ($Value.PSObject.Properties.Name -contains 'comparison_only' -and $Value.comparison_only -ne $true) { throw "$Label is not comparison-only evidence." }
    if ($Value.PSObject.Properties.Name -contains 'physical_acceptance_authority' -and $Value.physical_acceptance_authority -ne $false) { throw "$Label unexpectedly carries physical acceptance authority." }
    if (-not $PromotionFieldOptional -and $Value.PSObject.Properties.Name -contains 'promotion_authority' -and $Value.promotion_authority -ne $false) { throw "$Label unexpectedly carries promotion authority." }
    if ($Value.PSObject.Properties.Name -contains 'production_activation' -and $Value.production_activation -ne $false) { throw "$Label unexpectedly carries production activation." }
}

function Assert-ExactFileSet {
    param(
        [Parameter(Mandatory = $true)][string]$Base,
        [Parameter(Mandatory = $true)][string]$Head,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $raw = @(& git -C $RepoRoot diff --name-only "$Base..$Head" 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not enumerate $Label files: $($raw -join ' ')" }
    $actual = @($raw | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ } | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    if ($actual.Count -ne $wanted.Count) { throw "$Label changed-file count mismatch: $($actual.Count) != $($wanted.Count)." }
    for ($i = 0; $i -lt $wanted.Count; $i++) {
        if ($actual[$i] -cne $wanted[$i]) { throw "$Label changed-file set mismatch at index $i: $($actual[$i]) != $($wanted[$i])." }
    }
}

function Assert-RemoteRef {
    param([Parameter(Mandatory = $true)][string]$Ref,[Parameter(Mandatory = $true)][string]$Expected,[Parameter(Mandatory = $true)][string]$Label)
    $raw = @(& git -C $RepoRoot rev-parse "refs/remotes/origin/$Ref" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "Could not resolve $Label." }
    $actual = Need-Revision -Value ([string]$raw[0]) -Label $Label
    if ($actual -ne $Expected) { throw "$Label moved: $actual != $Expected" }
}

function Assert-Ancestor {
    param([Parameter(Mandatory = $true)][string]$Ancestor,[Parameter(Mandatory = $true)][string]$Descendant,[Parameter(Mandatory = $true)][string]$Label)
    & git -C $RepoRoot merge-base --is-ancestor $Ancestor $Descendant
    if ($LASTEXITCODE -ne 0) { throw "$Label ancestry check failed." }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite candidate promotion review: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ('.' + [IO.Path]::GetFileName($Path) + '.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $Value | ConvertTo-Json -Depth 70 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    }
    finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
    }
}

if (-not $PromotePbr -or -not $PromoteThroughput -or -not $ConfirmPromotion) {
    throw 'Explicit -PromotePbr, -PromoteThroughput and -ConfirmPromotion are all required. This command is the candidate-integration promotion decision.'
}
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw 'BodyRig candidate promotion review is Windows-only.' }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ is required.' }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required.' }
if ([string]::IsNullOrWhiteSpace($PromotionNote.Trim())) { throw 'PromotionNote must contain the operator promotion rationale.' }
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
Need-Directory -Path (Join-Path $RepoRoot '.git') -Label 'BodyRig Git checkout' | Out-Null

# Promotion is reviewed from the exact fixed throughput checkout that produced the successful physical candidate.
$branchRaw = @(& git -C $RepoRoot branch --show-current 2>&1)
$headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
$dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or $headRaw.Count -ne 1 -or $dirty.Count -gt 0) { throw 'Candidate promotion review requires a clean, attached Git checkout.' }
if (([string]$branchRaw[0]).Trim() -ne $ExpectedFixedThroughputRef) { throw "Promotion review must run from $ExpectedFixedThroughputRef." }
if ((Need-Revision -Value ([string]$headRaw[0]) -Label 'checkout HEAD') -ne $ExpectedFixedThroughputRevision) { throw 'Promotion review checkout is not the physically reviewed fixed throughput revision.' }

$fetchSpecs = @(
    '+refs/heads/main:refs/remotes/origin/main',
    "+refs/heads/${ExpectedPbrRef}:refs/remotes/origin/${ExpectedPbrRef}",
    "+refs/heads/${ExpectedFailedThroughputRef}:refs/remotes/origin/${ExpectedFailedThroughputRef}",
    "+refs/heads/${ExpectedFixedThroughputRef}:refs/remotes/origin/${ExpectedFixedThroughputRef}"
)
$fetchRaw = @(& git -C $RepoRoot fetch --no-tags origin @fetchSpecs 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not refresh promotion-bound refs: $($fetchRaw -join ' ')" }
Assert-RemoteRef -Ref 'main' -Expected $ExpectedBaselineRevision -Label 'origin/main'
Assert-RemoteRef -Ref $ExpectedPbrRef -Expected $ExpectedPbrRevision -Label 'origin PBR candidate'
Assert-RemoteRef -Ref $ExpectedFailedThroughputRef -Expected $ExpectedFailedThroughputRevision -Label 'origin planned throughput candidate'
Assert-RemoteRef -Ref $ExpectedFixedThroughputRef -Expected $ExpectedFixedThroughputRevision -Label 'origin fixed throughput candidate'
Assert-Ancestor -Ancestor $ExpectedBaselineRevision -Descendant $ExpectedPbrRevision -Label 'PBR candidate'
Assert-Ancestor -Ancestor $ExpectedBaselineRevision -Descendant $ExpectedFixedThroughputRevision -Label 'fixed throughput candidate'
Assert-Ancestor -Ancestor $ExpectedFailedThroughputRevision -Descendant $ExpectedFixedThroughputRevision -Label 'throughput defect fix'
Assert-ExactFileSet -Base $ExpectedBaselineRevision -Head $ExpectedPbrRevision -Expected $ExpectedPbrFiles -Label 'PBR candidate'
Assert-ExactFileSet -Base $ExpectedBaselineRevision -Head $ExpectedFixedThroughputRevision -Expected $ExpectedThroughputFiles -Label 'fixed throughput candidate'

$PbrRunDir = Need-Directory -Path $PbrRunDir -Label 'PBR A/B run directory'
$ThroughputRunDir = Need-Directory -Path $ThroughputRunDir -Label 'throughput retry review directory'
$planRoot = Join-Path $env:LOCALAPPDATA 'BodyRig\ab-baseline-plans'
$sharedPlanPath = Need-File -Path (Join-Path $planRoot "$BaselineJobId.json") -Label 'shared A/B baseline plan'
$retryPath = Need-File -Path (Join-Path $planRoot "$BaselineJobId-throughput-retry-$ExpectedCandidateJobId.json") -Label 'throughput retry migration authority'
$retry = Read-Json -Path $retryPath -Label 'throughput retry migration authority'
$sharedPlan = Read-Json -Path $sharedPlanPath -Label 'shared A/B baseline plan'
Assert-ComparisonBoundary -Value $sharedPlan -Label 'shared A/B baseline plan'
Assert-ComparisonBoundary -Value $retry -Label 'throughput retry migration authority'
if ([string]$sharedPlan.format -ne 'bodyrig-dual-candidate-ab-baseline-plan' -or [int]$sharedPlan.version -ne 1) { throw 'Shared A/B baseline plan format/version mismatch.' }
if ([string]$retry.format -ne 'bodyrig-throughput-retry-after-resume-signature-fix' -or [int]$retry.version -ne 1) { throw 'Throughput retry migration authority format/version mismatch.' }
if ([string]$retry.baseline_job_id -ne $BaselineJobId -or [string]$retry.failed_candidate_job_id -ne $ExpectedFailedCandidateJobId -or [string]$retry.candidate_job_id -ne $ExpectedCandidateJobId) { throw 'Retry migration authority does not match the reviewed jobs.' }
if ((Need-Revision -Value ([string]$sharedPlan.baseline_bodyrig_revision) -Label 'shared-plan baseline revision') -ne $ExpectedBaselineRevision) { throw 'Shared baseline revision changed.' }
if ((Need-Revision -Value ([string]$retry.fixed_candidate_revision) -Label 'retry fixed revision') -ne $ExpectedFixedThroughputRevision -or [string]$retry.fixed_candidate_ref -ne $ExpectedFixedThroughputRef) { throw 'Retry migration does not bind the exact physically reviewed fixed throughput candidate.' }
if ((Need-Revision -Value ([string]$retry.failed_candidate_revision) -Label 'retry failed revision') -ne $ExpectedFailedThroughputRevision -or [string]$retry.failure_signature -ne $ExpectedFailureSignature) { throw 'Retry migration does not bind the reviewed throughput failure lineage.' }
if ((File-Sha256 -Path $sharedPlanPath) -ne (Need-Sha256 -Value ([string]$retry.baseline_plan_sha256) -Label 'retry baseline-plan SHA')) { throw 'Shared A/B baseline plan bytes changed after retry migration.' }

$pbrReviewPath = Need-File -Path (Join-Path $PbrRunDir 'human-review.json') -Label 'PBR human review'
$pbrAuthorityPath = Need-File -Path (Join-Path $PbrRunDir 'plan-bound-human-review-authority.json') -Label 'PBR plan-bound human-review authority'
$pbrReview = Read-Json -Path $pbrReviewPath -Label 'PBR human review'
$pbrAuthority = Read-Json -Path $pbrAuthorityPath -Label 'PBR plan-bound human-review authority'
Assert-ComparisonBoundary -Value $pbrReview -Label 'PBR human review' -PromotionFieldOptional
Assert-ComparisonBoundary -Value $pbrAuthority -Label 'PBR plan-bound human-review authority'
if ([string]$pbrReview.format -ne 'bodyrig-fidelity-ab-human-review' -or [int]$pbrReview.version -ne 1 -or $pbrReview.human_visual_review_confirmed -ne $true -or [string]$pbrReview.decision -ne 'right' -or [string]$pbrReview.preferred_side -ne 'right') { throw 'PBR human review is not an explicit reviewed preference for the candidate.' }
if ((Need-Revision -Value ([string]$pbrReview.left.builder_revision) -Label 'PBR left revision') -ne $ExpectedBaselineRevision -or (Need-Revision -Value ([string]$pbrReview.right.builder_revision) -Label 'PBR right revision') -ne $ExpectedPbrRevision) { throw 'PBR human review revisions do not match the promoted candidate pair.' }
if ((File-Sha256 -Path $pbrAuthorityPath) -ne (Need-Sha256 -Value ([string]$retry.pbr_human_review_authority_sha256) -Label 'retry PBR authority SHA')) { throw 'PBR plan-bound human-review authority bytes changed after retry migration.' }
if ((File-Sha256 -Path $pbrReviewPath) -ne (Need-Sha256 -Value ([string]$retry.pbr_human_review_sha256) -Label 'retry PBR human-review SHA')) { throw 'PBR human-review bytes changed after retry migration.' }
if ([string]$retry.pbr_decision -ne 'right') { throw 'Retry migration does not preserve the PBR right-side preference.' }

$continuationPath = Need-File -Path (Join-Path $ThroughputRunDir 'continuation-authority.json') -Label 'throughput retry continuation authority'
$throughputReviewPath = Need-File -Path "$ThroughputRunDir.human-review.json" -Label 'throughput human review'
$throughputAuthorityPath = Need-File -Path "$ThroughputRunDir.retry-human-review-authority.json" -Label 'throughput retry human-review authority'
$continuation = Read-Json -Path $continuationPath -Label 'throughput retry continuation authority'
$throughputReview = Read-Json -Path $throughputReviewPath -Label 'throughput human review'
$throughputAuthority = Read-Json -Path $throughputAuthorityPath -Label 'throughput retry human-review authority'
Assert-ComparisonBoundary -Value $continuation -Label 'throughput retry continuation authority'
Assert-ComparisonBoundary -Value $throughputReview -Label 'throughput human review'
Assert-ComparisonBoundary -Value $throughputAuthority -Label 'throughput retry human-review authority'
if ([string]$continuation.format -ne 'bodyrig-throughput-retry-review-continuation' -or [int]$continuation.version -ne 1) { throw 'Throughput retry continuation format/version mismatch.' }
if ([string]$throughputReview.format -ne 'bodyrig-recovery-throughput-human-review' -or [int]$throughputReview.version -ne 1) { throw 'Throughput human review format/version mismatch.' }
if ([string]$throughputAuthority.format -ne 'bodyrig-throughput-retry-human-review-authority' -or [int]$throughputAuthority.version -ne 1) { throw 'Throughput retry human-review authority format/version mismatch.' }
if ([string]$continuation.baseline_job_id -ne $BaselineJobId -or [string]$continuation.candidate_job_id -ne $ExpectedCandidateJobId -or [string]$continuation.failed_candidate_job_id -ne $ExpectedFailedCandidateJobId) { throw 'Throughput continuation jobs do not match promotion authority.' }
if ((Need-Revision -Value ([string]$continuation.fixed_candidate_revision) -Label 'continuation candidate revision') -ne $ExpectedFixedThroughputRevision -or [string]$continuation.fixed_candidate_ref -ne $ExpectedFixedThroughputRef) { throw 'Throughput continuation does not bind the exact fixed candidate.' }
if ([string]$throughputReview.candidate_job_id -ne $ExpectedCandidateJobId -or (Need-Revision -Value ([string]$throughputReview.candidate_bodyrig_revision) -Label 'throughput human candidate revision') -ne $ExpectedFixedThroughputRevision) { throw 'Throughput human review does not bind the exact fixed candidate job/revision.' }
if ($throughputReview.human_visual_review_completed -ne $true -or $throughputReview.human_visual_review_passed -ne $true -or [string]$throughputReview.decision -ne 'no-material-regression' -or [string]$throughputReview.next_gate -ne 'eligible-for-explicit-promotion-review') { throw 'Throughput human review is not eligible for explicit promotion review.' }
foreach ($criterion in @('identity_shape','face_identity','skin_texture_alignment','gross_anatomy')) {
    if ([string]$throughputReview.criteria.$criterion -ne 'pass') { throw "Throughput promotion blocked by human criterion: $criterion" }
}
if ([string]$throughputAuthority.candidate_job_id -ne $ExpectedCandidateJobId -or $throughputAuthority.human_visual_review_passed -ne $true -or [string]$throughputAuthority.decision -ne 'no-material-regression' -or [string]$throughputAuthority.next_gate -ne 'eligible-for-explicit-promotion-review') { throw 'Retry human-review authority is not promotion-eligible.' }
if ((File-Sha256 -Path $continuationPath) -ne (Need-Sha256 -Value ([string]$throughputAuthority.continuation_authority_sha256) -Label 'throughput human continuation SHA')) { throw 'Throughput continuation bytes changed after human review.' }
if ((File-Sha256 -Path $throughputReviewPath) -ne (Need-Sha256 -Value ([string]$throughputAuthority.human_review_sha256) -Label 'throughput human-review SHA')) { throw 'Throughput human-review bytes changed after terminal authority.' }
if ((File-Sha256 -Path $retryPath) -ne (Need-Sha256 -Value ([string]$throughputAuthority.retry_authority_sha256) -Label 'throughput human retry-authority SHA')) { throw 'Throughput retry migration bytes changed after terminal human review.' }

# Re-read exact job bytes bound by continuation authority.
$dataRoot = if (-not [string]::IsNullOrWhiteSpace($env:BODYRIG_DATA_DIR)) { [IO.Path]::GetFullPath($env:BODYRIG_DATA_DIR) } else { Join-Path $env:LOCALAPPDATA 'BodyRig' }
$baselineJobPath = Need-File -Path (Join-Path $dataRoot "ui-jobs\$BaselineJobId\job.json") -Label 'baseline job JSON'
$candidateJobPath = Need-File -Path (Join-Path $dataRoot "ui-jobs\$ExpectedCandidateJobId\job.json") -Label 'candidate job JSON'
if ((File-Sha256 -Path $baselineJobPath) -ne (Need-Sha256 -Value ([string]$continuation.baseline_job_json_sha256) -Label 'continuation baseline job SHA')) { throw 'Baseline job JSON changed after throughput continuation.' }
if ((File-Sha256 -Path $candidateJobPath) -ne (Need-Sha256 -Value ([string]$continuation.candidate_job_json_sha256) -Label 'continuation candidate job SHA')) { throw 'Candidate job JSON changed after throughput continuation.' }

$promotionRoot = Join-Path $env:LOCALAPPDATA 'BodyRig\ab-promotions'
$outPath = Join-Path $promotionRoot "$BaselineJobId--pbr-$($ExpectedPbrRevision.Substring(0,12))--throughput-$($ExpectedFixedThroughputRevision.Substring(0,12)).json"
$receipt = [ordered]@{
    format = 'bodyrig-dual-candidate-explicit-promotion-review'
    version = 1
    baseline_job_id = $BaselineJobId
    person_id = [string]$retry.person_id
    stash_performer_id = [string]$retry.stash_performer_id
    baseline_revision = $ExpectedBaselineRevision
    pbr = [ordered]@{
        decision = 'promote'
        ref = $ExpectedPbrRef
        revision = $ExpectedPbrRevision
        human_decision = 'right'
        human_review_sha256 = (File-Sha256 -Path $pbrReviewPath)
        plan_bound_human_review_authority_sha256 = (File-Sha256 -Path $pbrAuthorityPath)
        exact_changed_files = $ExpectedPbrFiles
    }
    throughput = [ordered]@{
        decision = 'promote'
        original_planned_ref = $ExpectedFailedThroughputRef
        original_planned_revision = $ExpectedFailedThroughputRevision
        failed_candidate_job_id = $ExpectedFailedCandidateJobId
        reviewed_failure_signature = $ExpectedFailureSignature
        fixed_ref = $ExpectedFixedThroughputRef
        fixed_revision = $ExpectedFixedThroughputRevision
        candidate_job_id = $ExpectedCandidateJobId
        human_decision = 'no-material-regression'
        retry_migration_authority_sha256 = (File-Sha256 -Path $retryPath)
        continuation_authority_sha256 = (File-Sha256 -Path $continuationPath)
        human_review_sha256 = (File-Sha256 -Path $throughputReviewPath)
        retry_human_review_authority_sha256 = (File-Sha256 -Path $throughputAuthorityPath)
        exact_changed_files = $ExpectedThroughputFiles
    }
    integration_decision = 'promote-both-reviewed-candidates'
    promotion_note = $PromotionNote.Trim()
    candidate_promotion_authority = $true
    promotion_authority = $true
    physical_acceptance_authority = $false
    production_activation = $false
    release_authority = $false
    created_at = [DateTime]::UtcNow.ToString('o')
}
Write-CreateOnlyJson -Path $outPath -Value $receipt
$receiptSha = File-Sha256 -Path $outPath

Write-Host ''
Write-Host 'BodyRig explicit candidate promotion review: RECORDED'
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "PBR promotion:      APPROVED @ $ExpectedPbrRevision"
Write-Host "Throughput promote: APPROVED @ $ExpectedFixedThroughputRevision"
Write-Host "Receipt:            $outPath"
Write-Host "Receipt SHA-256:    $receiptSha"
Write-Host 'Authority: candidate integration promotion only; physical acceptance=false; production activation=false; release authority=false.'
Write-Host 'Next: GitHub integration may proceed only with these exact candidate bytes/revisions or a byte-preserving re-anchor.'
