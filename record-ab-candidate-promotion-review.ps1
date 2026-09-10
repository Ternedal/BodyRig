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
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw ("{0} not found: {1}" -f $Label,$Path) }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw ("{0} not found: {1}" -f $Label,$Path) }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 70 }
    catch { throw ("{0} is unreadable JSON: {1}" -f $Label,$Path) }
    if ($null -eq $value) { throw ("{0} is empty: {1}" -f $Label,$Path) }
    return $value
}

function File-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $v = $Value.Trim().ToLowerInvariant()
    if ($v -notmatch '^[0-9a-f]{40}$') { throw ("{0} is not an exact Git revision." -f $Label) }
    return $v
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $v = $Value.Trim().ToLowerInvariant()
    if ($v -notmatch '^[0-9a-f]{64}$') { throw ("{0} is not a canonical SHA-256." -f $Label) }
    return $v
}

function Assert-ComparisonBoundary {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$PromotionFieldOptional
    )
    if ($Value.PSObject.Properties.Name -contains 'comparison_only') {
        if ($Value.comparison_only -ne $true) { throw ("{0} is not comparison-only evidence." -f $Label) }
    }
    if ($Value.PSObject.Properties.Name -contains 'physical_acceptance_authority') {
        if ($Value.physical_acceptance_authority -ne $false) { throw ("{0} unexpectedly carries physical acceptance authority." -f $Label) }
    }
    if ($Value.PSObject.Properties.Name -contains 'promotion_authority') {
        if ($Value.promotion_authority -ne $false) { throw ("{0} unexpectedly carries promotion authority." -f $Label) }
    } elseif (-not $PromotionFieldOptional) {
        throw ("{0} lacks an explicit promotion-authority boundary." -f $Label)
    }
    if ($Value.PSObject.Properties.Name -contains 'production_activation') {
        if ($Value.production_activation -ne $false) { throw ("{0} unexpectedly carries production activation." -f $Label) }
    }
}

function Assert-ExactFileSet {
    param(
        [Parameter(Mandatory = $true)][string]$Base,
        [Parameter(Mandatory = $true)][string]$Head,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $raw = @(& git -C $RepoRoot diff --name-only "$Base..$Head" 2>&1)
    if ($LASTEXITCODE -ne 0) { throw ("Could not enumerate {0} files: {1}" -f $Label,($raw -join ' ')) }
    $actual = @($raw | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ } | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    if ($actual.Count -ne $wanted.Count) {
        throw ("{0} changed-file count mismatch: {1} != {2}." -f $Label,$actual.Count,$wanted.Count)
    }
    for ($i = 0; $i -lt $wanted.Count; $i++) {
        if ($actual[$i] -cne $wanted[$i]) {
            throw ("{0} changed-file set mismatch at index {1}: {2} != {3}." -f $Label,$i,$actual[$i],$wanted[$i])
        }
    }
}

function Assert-RemoteRef {
    param([Parameter(Mandatory = $true)][string]$Ref,[Parameter(Mandatory = $true)][string]$Expected,[Parameter(Mandatory = $true)][string]$Label)
    $raw = @(& git -C $RepoRoot rev-parse "refs/remotes/origin/$Ref" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw ("Could not resolve {0}." -f $Label) }
    $actual = Need-Revision -Value ([string]$raw[0]) -Label $Label
    if ($actual -ne $Expected) { throw ("{0} moved: {1} != {2}" -f $Label,$actual,$Expected) }
}

function Assert-Ancestor {
    param([Parameter(Mandatory = $true)][string]$Ancestor,[Parameter(Mandatory = $true)][string]$Descendant,[Parameter(Mandatory = $true)][string]$Label)
    & git -C $RepoRoot merge-base --is-ancestor $Ancestor $Descendant
    if ($LASTEXITCODE -ne 0) { throw ("{0} ancestry check failed." -f $Label) }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw ("Refusing to overwrite candidate promotion review: {0}" -f $Path) }
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
    throw 'Explicit -PromotePbr, -PromoteThroughput and -ConfirmPromotion are all required. This is the candidate-integration promotion decision.'
}
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw 'BodyRig candidate promotion review is Windows-only.' }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ is required.' }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required.' }
if ([string]::IsNullOrWhiteSpace($PromotionNote.Trim())) { throw 'PromotionNote must contain the operator promotion rationale.' }
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
Need-Directory -Path (Join-Path $RepoRoot '.git') -Label 'BodyRig Git checkout' | Out-Null

# The explicit promotion decision is made from the exact successful physical throughput checkout.
$branchRaw = @(& git -C $RepoRoot branch --show-current 2>&1)
$headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
$dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or $headRaw.Count -ne 1 -or $dirty.Count -gt 0) {
    throw 'Candidate promotion review requires a clean, attached Git checkout.'
}
if (([string]$branchRaw[0]).Trim() -ne $ExpectedFixedThroughputRef) { throw ("Promotion review must run from {0}." -f $ExpectedFixedThroughputRef) }
if ((Need-Revision -Value ([string]$headRaw[0]) -Label 'checkout HEAD') -ne $ExpectedFixedThroughputRevision) {
    throw 'Promotion review checkout is not the physically reviewed fixed throughput revision.'
}

$fetchSpecs = @(
    '+refs/heads/main:refs/remotes/origin/main',
    "+refs/heads/${ExpectedPbrRef}:refs/remotes/origin/${ExpectedPbrRef}",
    "+refs/heads/${ExpectedFailedThroughputRef}:refs/remotes/origin/${ExpectedFailedThroughputRef}",
    "+refs/heads/${ExpectedFixedThroughputRef}:refs/remotes/origin/${ExpectedFixedThroughputRef}"
)
$fetchRaw = @(& git -C $RepoRoot fetch --no-tags origin @fetchSpecs 2>&1)
if ($LASTEXITCODE -ne 0) { throw ("Could not refresh promotion-bound refs: {0}" -f ($fetchRaw -join ' ')) }
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
$oldGatePath = Need-File -Path (Join-Path $planRoot "$BaselineJobId-throughput-$ExpectedFailedCandidateJobId-pbr-gate.json") -Label 'original PBR-to-throughput gate'

$sharedPlan = Read-Json -Path $sharedPlanPath -Label 'shared A/B baseline plan'
$retry = Read-Json -Path $retryPath -Label 'throughput retry migration authority'
$oldGate = Read-Json -Path $oldGatePath -Label 'original PBR-to-throughput gate'
Assert-ComparisonBoundary -Value $sharedPlan -Label 'shared A/B baseline plan'
Assert-ComparisonBoundary -Value $retry -Label 'throughput retry migration authority'
Assert-ComparisonBoundary -Value $oldGate -Label 'original PBR-to-throughput gate'
if ([string]$sharedPlan.format -ne 'bodyrig-dual-candidate-ab-baseline-plan' -or [int]$sharedPlan.version -ne 1) { throw 'Shared A/B baseline plan format/version mismatch.' }
if ([string]$retry.format -ne 'bodyrig-throughput-retry-after-resume-signature-fix' -or [int]$retry.version -ne 1) { throw 'Throughput retry migration authority format/version mismatch.' }
if ([string]$oldGate.format -ne 'bodyrig-throughput-pbr-human-review-gate' -or [int]$oldGate.version -ne 1) { throw 'Original PBR-to-throughput gate format/version mismatch.' }
if ([string]$retry.baseline_job_id -ne $BaselineJobId -or [string]$retry.failed_candidate_job_id -ne $ExpectedFailedCandidateJobId -or [string]$retry.candidate_job_id -ne $ExpectedCandidateJobId) { throw 'Retry migration authority does not match the reviewed jobs.' }
if ((Need-Revision -Value ([string]$sharedPlan.baseline_bodyrig_revision) -Label 'shared-plan baseline revision') -ne $ExpectedBaselineRevision) { throw 'Shared baseline revision changed.' }
if ((Need-Revision -Value ([string]$retry.fixed_candidate_revision) -Label 'retry fixed revision') -ne $ExpectedFixedThroughputRevision -or [string]$retry.fixed_candidate_ref -ne $ExpectedFixedThroughputRef) { throw 'Retry migration does not bind the exact physically reviewed fixed throughput candidate.' }
if ((Need-Revision -Value ([string]$retry.failed_candidate_revision) -Label 'retry failed revision') -ne $ExpectedFailedThroughputRevision -or [string]$retry.failure_signature -ne $ExpectedFailureSignature) { throw 'Retry migration does not bind the reviewed throughput failure lineage.' }
if ((File-Sha256 -Path $sharedPlanPath) -ne (Need-Sha256 -Value ([string]$retry.baseline_plan_sha256) -Label 'retry baseline-plan SHA')) { throw 'Shared A/B baseline plan bytes changed after retry migration.' }
if ((File-Sha256 -Path $oldGatePath) -ne (Need-Sha256 -Value ([string]$retry.original_pbr_to_throughput_gate_sha256) -Label 'retry original PBR gate SHA')) { throw 'Original PBR-to-throughput gate bytes changed after retry migration.' }
if ([string]$oldGate.baseline_job_id -ne $BaselineJobId -or [string]$oldGate.candidate_job_id -ne $ExpectedFailedCandidateJobId -or [string]$oldGate.person_id -ne [string]$retry.person_id -or [string]$oldGate.stash_performer_id -ne [string]$retry.stash_performer_id -or [string]$oldGate.pbr_decision -ne 'right') { throw 'Original PBR-to-throughput gate identity/decision no longer matches retry lineage.' }

$pbrReviewPath = Need-File -Path (Join-Path $PbrRunDir 'human-review.json') -Label 'PBR human review'
$pbrAuthorityPath = Need-File -Path (Join-Path $PbrRunDir 'plan-bound-human-review-authority.json') -Label 'PBR plan-bound human-review authority'
$pbrReview = Read-Json -Path $pbrReviewPath -Label 'PBR human review'
$pbrAuthority = Read-Json -Path $pbrAuthorityPath -Label 'PBR plan-bound human-review authority'
Assert-ComparisonBoundary -Value $pbrReview -Label 'PBR human review' -PromotionFieldOptional
Assert-ComparisonBoundary -Value $pbrAuthority -Label 'PBR plan-bound human-review authority'
if ([string]$pbrReview.format -ne 'bodyrig-fidelity-ab-human-review' -or [int]$pbrReview.version -ne 1 -or $pbrReview.human_visual_review_confirmed -ne $true -or [string]$pbrReview.decision -ne 'right' -or [string]$pbrReview.preferred_side -ne 'right') { throw 'PBR human review is not an explicit reviewed preference for the candidate.' }
if ((Need-Revision -Value ([string]$pbrReview.left.builder_revision) -Label 'PBR left revision') -ne $ExpectedBaselineRevision -or (Need-Revision -Value ([string]$pbrReview.right.builder_revision) -Label 'PBR right revision') -ne $ExpectedPbrRevision) { throw 'PBR human-review revisions do not match the promoted candidate pair.' }
if ((File-Sha256 -Path $pbrAuthorityPath) -ne (Need-Sha256 -Value ([string]$retry.pbr_human_review_authority_sha256) -Label 'retry PBR authority SHA')) { throw 'PBR plan-bound human-review authority bytes changed after retry migration.' }
if ((File-Sha256 -Path $pbrReviewPath) -ne (Need-Sha256 -Value ([string]$retry.pbr_human_review_sha256) -Label 'retry PBR human-review SHA')) { throw 'PBR human-review bytes changed after retry migration.' }
if ([string]$retry.pbr_decision -ne 'right') { throw 'Retry migration does not preserve the PBR right-side preference.' }

$continuationPath = Need-File -Path (Join-Path $ThroughputRunDir 'continuation-authority.json') -Label 'throughput retry continuation authority'
$machinePath = Need-File -Path (Join-Path $ThroughputRunDir 'machine-audit.json') -Label 'throughput machine A/B audit'
$bundleReceiptPath = Need-File -Path (Join-Path $ThroughputRunDir 'review-bundle\review-bundle.json') -Label 'throughput review-bundle receipt'
$throughputReviewPath = Need-File -Path "$ThroughputRunDir.human-review.json" -Label 'throughput human review'
$throughputAuthorityPath = Need-File -Path "$ThroughputRunDir.retry-human-review-authority.json" -Label 'throughput retry human-review authority'

$continuation = Read-Json -Path $continuationPath -Label 'throughput retry continuation authority'
$machine = Read-Json -Path $machinePath -Label 'throughput machine A/B audit'
$bundleReceipt = Read-Json -Path $bundleReceiptPath -Label 'throughput review-bundle receipt'
$throughputReview = Read-Json -Path $throughputReviewPath -Label 'throughput human review'
$throughputAuthority = Read-Json -Path $throughputAuthorityPath -Label 'throughput retry human-review authority'
Assert-ComparisonBoundary -Value $continuation -Label 'throughput retry continuation authority'
Assert-ComparisonBoundary -Value $machine -Label 'throughput machine A/B audit'
Assert-ComparisonBoundary -Value $bundleReceipt -Label 'throughput review-bundle receipt'
Assert-ComparisonBoundary -Value $throughputReview -Label 'throughput human review'
Assert-ComparisonBoundary -Value $throughputAuthority -Label 'throughput retry human-review authority'

if ([string]$continuation.format -ne 'bodyrig-throughput-retry-review-continuation' -or [int]$continuation.version -ne 1) { throw 'Throughput retry continuation format/version mismatch.' }
if ([string]$machine.format -ne 'bodyrig-recovery-throughput-sampling-audit' -or [int]$machine.version -ne 1 -or $machine.machine_evidence_pass -ne $true -or [string]$machine.decision -ne 'eligible-for-human-ab-review') { throw 'Throughput machine evidence is not promotion-review eligible.' }
if ([string]$bundleReceipt.format -ne 'bodyrig-recovery-throughput-review-bundle' -or [int]$bundleReceipt.version -ne 1 -or $bundleReceipt.human_visual_review_required -ne $true) { throw 'Throughput review bundle is not the canonical human-review bundle.' }
if ([string]$throughputReview.format -ne 'bodyrig-recovery-throughput-human-review' -or [int]$throughputReview.version -ne 1) { throw 'Throughput human review format/version mismatch.' }
if ([string]$throughputAuthority.format -ne 'bodyrig-throughput-retry-human-review-authority' -or [int]$throughputAuthority.version -ne 1) { throw 'Throughput retry human-review authority format/version mismatch.' }

if ([string]$continuation.baseline_job_id -ne $BaselineJobId -or [string]$continuation.candidate_job_id -ne $ExpectedCandidateJobId -or [string]$continuation.failed_candidate_job_id -ne $ExpectedFailedCandidateJobId) { throw 'Throughput continuation jobs do not match promotion authority.' }
if ((Need-Revision -Value ([string]$continuation.fixed_candidate_revision) -Label 'continuation candidate revision') -ne $ExpectedFixedThroughputRevision -or [string]$continuation.fixed_candidate_ref -ne $ExpectedFixedThroughputRef) { throw 'Throughput continuation does not bind the exact fixed candidate.' }
if ([string]$machine.baseline_job_id -ne $BaselineJobId -or [string]$machine.candidate_job_id -ne $ExpectedCandidateJobId -or (Need-Revision -Value ([string]$machine.baseline_bodyrig_revision) -Label 'machine baseline revision') -ne $ExpectedBaselineRevision -or (Need-Revision -Value ([string]$machine.candidate_bodyrig_revision) -Label 'machine candidate revision') -ne $ExpectedFixedThroughputRevision) { throw 'Throughput machine A/B does not match the reviewed job/revision pair.' }
if ($machine.blockers.Count -ne 0 -or $machine.source_authority_equal -ne $true -or $machine.observation_selection_equal -ne $true -or $machine.native_observation_segment_bytes_equal -ne $true -or $machine.recovery_track_equal -ne $true -or $machine.frames.reduction_observed -ne $true) { throw 'Throughput machine A/B no longer proves clean comparable throughput improvement.' }
if ([string]$bundleReceipt.baseline_job_id -ne $BaselineJobId -or [string]$bundleReceipt.candidate_job_id -ne $ExpectedCandidateJobId -or (Need-Revision -Value ([string]$bundleReceipt.candidate_bodyrig_revision) -Label 'bundle candidate revision') -ne $ExpectedFixedThroughputRevision) { throw 'Throughput review bundle does not match the reviewed candidate.' }
if ([string]$throughputReview.candidate_job_id -ne $ExpectedCandidateJobId -or (Need-Revision -Value ([string]$throughputReview.candidate_bodyrig_revision) -Label 'throughput human candidate revision') -ne $ExpectedFixedThroughputRevision) { throw 'Throughput human review does not bind the exact fixed candidate job/revision.' }
if ($throughputReview.human_visual_review_completed -ne $true -or $throughputReview.human_visual_review_passed -ne $true -or [string]$throughputReview.decision -ne 'no-material-regression' -or [string]$throughputReview.next_gate -ne 'eligible-for-explicit-promotion-review') { throw 'Throughput human review is not eligible for explicit promotion review.' }
foreach ($criterion in @('identity_shape','face_identity','skin_texture_alignment','gross_anatomy')) {
    if ([string]$throughputReview.criteria.$criterion -ne 'pass') { throw ("Throughput promotion blocked by human criterion: {0}" -f $criterion) }
}
if ([string]$throughputAuthority.candidate_job_id -ne $ExpectedCandidateJobId -or $throughputAuthority.human_visual_review_passed -ne $true -or [string]$throughputAuthority.decision -ne 'no-material-regression' -or [string]$throughputAuthority.next_gate -ne 'eligible-for-explicit-promotion-review') { throw 'Retry human-review authority is not promotion-eligible.' }

$machineSha = File-Sha256 -Path $machinePath
$bundleSha = File-Sha256 -Path $bundleReceiptPath
if ($machineSha -ne (Need-Sha256 -Value ([string]$continuation.machine_audit_sha256) -Label 'continuation machine SHA') -or $machineSha -ne (Need-Sha256 -Value ([string]$throughputReview.machine_audit_sha256) -Label 'human-review machine SHA')) { throw 'Throughput machine-audit bytes changed after continuation/human review.' }
if ($bundleSha -ne (Need-Sha256 -Value ([string]$continuation.review_bundle_receipt_sha256) -Label 'continuation bundle SHA') -or $bundleSha -ne (Need-Sha256 -Value ([string]$throughputReview.review_bundle_receipt_sha256) -Label 'human-review bundle SHA')) { throw 'Throughput review-bundle bytes changed after continuation/human review.' }
if ((File-Sha256 -Path $continuationPath) -ne (Need-Sha256 -Value ([string]$throughputAuthority.continuation_authority_sha256) -Label 'throughput human continuation SHA')) { throw 'Throughput continuation bytes changed after human review.' }
if ((File-Sha256 -Path $throughputReviewPath) -ne (Need-Sha256 -Value ([string]$throughputAuthority.human_review_sha256) -Label 'throughput human-review SHA')) { throw 'Throughput human-review bytes changed after terminal authority.' }
if ((File-Sha256 -Path $retryPath) -ne (Need-Sha256 -Value ([string]$throughputAuthority.retry_authority_sha256) -Label 'throughput human retry-authority SHA')) { throw 'Throughput retry migration bytes changed after terminal human review.' }

$dataRoot = if (-not [string]::IsNullOrWhiteSpace($env:BODYRIG_DATA_DIR)) { [IO.Path]::GetFullPath($env:BODYRIG_DATA_DIR) } else { Join-Path $env:LOCALAPPDATA 'BodyRig' }
$baselineJobPath = Need-File -Path (Join-Path $dataRoot "ui-jobs\$BaselineJobId\job.json") -Label 'baseline job JSON'
$candidateJobPath = Need-File -Path (Join-Path $dataRoot "ui-jobs\$ExpectedCandidateJobId\job.json") -Label 'candidate job JSON'
if ((File-Sha256 -Path $baselineJobPath) -ne (Need-Sha256 -Value ([string]$continuation.baseline_job_json_sha256) -Label 'continuation baseline job SHA')) { throw 'Baseline job JSON changed after throughput continuation.' }
if ((File-Sha256 -Path $candidateJobPath) -ne (Need-Sha256 -Value ([string]$continuation.candidate_job_json_sha256) -Label 'continuation candidate job SHA')) { throw 'Candidate job JSON changed after throughput continuation.' }

# Recheck refs and checkout immediately before publishing create-only promotion authority.
$refetchRaw = @(& git -C $RepoRoot fetch --no-tags origin @fetchSpecs 2>&1)
if ($LASTEXITCODE -ne 0) { throw ("Could not recheck promotion-bound refs: {0}" -f ($refetchRaw -join ' ')) }
Assert-RemoteRef -Ref 'main' -Expected $ExpectedBaselineRevision -Label 'post-review origin/main'
Assert-RemoteRef -Ref $ExpectedPbrRef -Expected $ExpectedPbrRevision -Label 'post-review origin PBR candidate'
Assert-RemoteRef -Ref $ExpectedFailedThroughputRef -Expected $ExpectedFailedThroughputRevision -Label 'post-review origin planned throughput candidate'
Assert-RemoteRef -Ref $ExpectedFixedThroughputRef -Expected $ExpectedFixedThroughputRevision -Label 'post-review origin fixed throughput candidate'
$dirtyAfter = @(& git -C $RepoRoot status --porcelain 2>&1)
$headAfter = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirtyAfter.Count -gt 0 -or $headAfter.Count -ne 1 -or (Need-Revision -Value ([string]$headAfter[0]) -Label 'post-review checkout HEAD') -ne $ExpectedFixedThroughputRevision) { throw 'Checkout changed during promotion review.' }

$promotionRoot = Join-Path $env:LOCALAPPDATA 'BodyRig\ab-promotions'
$outPath = Join-Path $promotionRoot "$BaselineJobId--pbr-$($ExpectedPbrRevision.Substring(0,12))--throughput-$($ExpectedFixedThroughputRevision.Substring(0,12)).json"
$receipt = [ordered]@{
    format = 'bodyrig-dual-candidate-explicit-promotion-review'
    version = 1
    baseline_job_id = $BaselineJobId
    person_id = [string]$retry.person_id
    stash_performer_id = [string]$retry.stash_performer_id
    baseline_revision = $ExpectedBaselineRevision
    shared_baseline_plan_sha256 = (File-Sha256 -Path $sharedPlanPath)
    original_pbr_to_throughput_gate_sha256 = (File-Sha256 -Path $oldGatePath)
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
        machine_audit_sha256 = $machineSha
        review_bundle_receipt_sha256 = $bundleSha
        human_review_sha256 = (File-Sha256 -Path $throughputReviewPath)
        retry_human_review_authority_sha256 = (File-Sha256 -Path $throughputAuthorityPath)
        baseline_frames = [int]$machine.frames.baseline
        candidate_frames = [int]$machine.frames.candidate
        clone_pipeline_ratio = [double]$machine.timing.clone_pipeline_ratio
        total_ratio = [double]$machine.timing.total_ratio
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
Write-Host ("Baseline job:       {0}" -f $BaselineJobId)
Write-Host ("PBR promotion:      APPROVED @ {0}" -f $ExpectedPbrRevision)
Write-Host ("Throughput promote: APPROVED @ {0}" -f $ExpectedFixedThroughputRevision)
Write-Host ("Receipt:            {0}" -f $outPath)
Write-Host ("Receipt SHA-256:    {0}" -f $receiptSha)
Write-Host 'Authority: candidate integration promotion only; physical acceptance=false; production activation=false; release authority=false.'
Write-Host 'Next: GitHub integration may proceed only with these exact candidate bytes/revisions or a byte-preserving re-anchor.'
