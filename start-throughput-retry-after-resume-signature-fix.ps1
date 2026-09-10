param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$FailedCandidateJobId,

    [Parameter(Mandatory = $true)]
    [string]$PbrRunDir,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')]
    [string]$BaseUri = 'http://127.0.0.1:8775'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$PlannedThroughputRef = 'candidate/recovery-throughput-v3-current-main-20260908'
$PlannedThroughputRevision = 'ec743446d98809d693d01e51830f435fc3c09535'
$FixedThroughputRef = 'fix/throughput-v3-resume-signature-20260910'
$FixedThroughputRevision = '5fa01deb08399fda64e83db1329d4d2e83ad1bc2'
$ExpectedFailureNeedle = "_load_canonical_checkpoint() got an unexpected keyword argument 'source_fps'"
$ExpectedFixFiles = @(
    'bodyrig/bridges/hmr2_resume_bridge.py',
    'tests/test_hmr2_cross_job_resume.py',
    'tests/test_hmr2_resume_signature_regression.py'
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
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
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

function Require-ComparisonBoundary {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$PromotionOptional
    )
    $hasPromotion = @($Value.PSObject.Properties.Name) -contains 'promotion_authority'
    $promotionInvalid = if ($hasPromotion) { $Value.promotion_authority -ne $false } else { -not $PromotionOptional }
    if (
        $Value.comparison_only -ne $true -or
        $Value.physical_acceptance_authority -ne $false -or
        $promotionInvalid -or
        $Value.production_activation -ne $false
    ) { throw "$Label crossed the comparison-only authority boundary." }
}

function Assert-Checkout {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedBranch,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision
    )
    $branchRaw = @(& git -C $Root branch --show-current 2>&1)
    if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne $ExpectedBranch) {
        throw "Checkout must be attached to $ExpectedBranch."
    }
    $headRaw = @(& git -C $Root rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or (Need-Revision -Value ([string]$headRaw[0]) -Label 'checkout HEAD') -ne $ExpectedRevision) {
        throw "Checkout HEAD is not the expected revision $ExpectedRevision."
    }
    $dirty = @(& git -C $Root status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw 'Throughput retry migration requires an exact clean checkout.' }
}

function Assert-ServiceRevision {
    param([Parameter(Mandatory = $true)][string]$ExpectedRevision)
    try { $authority = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/operator-authority" -TimeoutSec 3 }
    catch { throw 'BodyRig operator authority endpoint is unavailable.' }
    if ($authority.ok -ne $true -or (Need-Revision -Value ([string]$authority.bodyrig_revision) -Label 'service revision') -ne $ExpectedRevision) {
        throw "BodyRig service is not bound to expected revision $ExpectedRevision."
    }
}

function Try-CancelJob {
    param([Parameter(Mandatory = $true)][string]$JobId)
    try {
        $result = Invoke-RestMethod -Method Post -Uri "$BaseUri/api/v1/jobs/$JobId/cancel" -TimeoutSec 10
        return "cancel requested ($([string]$result.status))"
    } catch {
        return "cancel request failed: $($_.Exception.Message)"
    }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite throughput retry authority: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ('.' + [IO.Path]::GetFileName($Path) + '.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $Value | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $temp -Encoding UTF8
        [IO.File]::Move($temp,$Path)
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw 'BodyRig throughput retry migration is Windows-only.' }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ (pwsh) is required.' }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required.' }

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$PbrRunDir = Need-Directory -Path $PbrRunDir -Label 'PBR run directory'
Assert-Checkout -Root $RepoRoot -ExpectedBranch $PlannedThroughputRef -ExpectedRevision $PlannedThroughputRevision
Assert-ServiceRevision -ExpectedRevision $PlannedThroughputRevision

$planRoot = Join-Path $env:LOCALAPPDATA 'BodyRig\ab-baseline-plans'
$sharedPlanPath = Need-File -Path (Join-Path $planRoot "$BaselineJobId.json") -Label 'shared A/B baseline plan'
$sharedPlan = Read-Json -Path $sharedPlanPath -Label 'shared A/B baseline plan'
$sharedPlanSha = File-Sha256 -Path $sharedPlanPath
if (
    [string]$sharedPlan.format -ne 'bodyrig-dual-candidate-ab-baseline-plan' -or
    [int]$sharedPlan.version -ne 1 -or
    [string]$sharedPlan.baseline_job_id -ne $BaselineJobId -or
    [string]$sharedPlan.person_id -notmatch '^person-[0-9a-f]{32}$' -or
    [string]$sharedPlan.throughput_candidate.ref -ne $PlannedThroughputRef -or
    (Need-Revision -Value ([string]$sharedPlan.throughput_candidate.revision) -Label 'planned throughput revision') -ne $PlannedThroughputRevision
) { throw 'Shared A/B plan does not bind the failed planned throughput candidate.' }
Require-ComparisonBoundary -Value $sharedPlan -Label 'shared A/B baseline plan'
$personId = [string]$sharedPlan.person_id

$oldRunPlanPath = Need-File -Path (Join-Path $planRoot "$BaselineJobId-throughput-$FailedCandidateJobId.json") -Label 'failed throughput candidate run plan'
$oldRunPlan = Read-Json -Path $oldRunPlanPath -Label 'failed throughput candidate run plan'
$oldRunPlanSha = File-Sha256 -Path $oldRunPlanPath
if (
    [string]$oldRunPlan.format -ne 'bodyrig-throughput-candidate-run-plan' -or
    [int]$oldRunPlan.version -ne 1 -or
    [string]$oldRunPlan.baseline_job_id -ne $BaselineJobId -or
    [string]$oldRunPlan.candidate_job_id -ne $FailedCandidateJobId -or
    [string]$oldRunPlan.person_id -ne $personId -or
    [string]$oldRunPlan.throughput_candidate_ref -ne $PlannedThroughputRef -or
    (Need-Revision -Value ([string]$oldRunPlan.throughput_candidate_revision) -Label 'failed run-plan throughput revision') -ne $PlannedThroughputRevision -or
    (Need-Sha256 -Value ([string]$oldRunPlan.baseline_plan_sha256) -Label 'failed run-plan baseline plan SHA') -ne $sharedPlanSha
) { throw 'Failed throughput candidate run plan no longer matches the shared A/B plan.' }
Require-ComparisonBoundary -Value $oldRunPlan -Label 'failed throughput candidate run plan'

$oldGatePath = Need-File -Path (Join-Path $planRoot "$BaselineJobId-throughput-$FailedCandidateJobId-pbr-gate.json") -Label 'PBR-to-throughput gate for failed candidate'
$oldGate = Read-Json -Path $oldGatePath -Label 'PBR-to-throughput gate for failed candidate'
$oldGateSha = File-Sha256 -Path $oldGatePath
if (
    [string]$oldGate.format -ne 'bodyrig-throughput-pbr-human-review-gate' -or
    [int]$oldGate.version -ne 1 -or
    [string]$oldGate.baseline_job_id -ne $BaselineJobId -or
    [string]$oldGate.candidate_job_id -ne $FailedCandidateJobId -or
    [string]$oldGate.person_id -ne $personId -or
    [string]$oldGate.throughput_candidate_ref -ne $PlannedThroughputRef -or
    (Need-Revision -Value ([string]$oldGate.throughput_candidate_revision) -Label 'failed PBR gate throughput revision') -ne $PlannedThroughputRevision -or
    (Need-Sha256 -Value ([string]$oldGate.baseline_plan_sha256) -Label 'failed PBR gate baseline plan SHA') -ne $sharedPlanSha -or
    (Need-Sha256 -Value ([string]$oldGate.candidate_run_plan_sha256) -Label 'failed PBR gate run-plan SHA') -ne $oldRunPlanSha -or
    $oldGate.human_visual_authority_recorded -ne $true
) { throw 'PBR-to-throughput gate no longer matches the failed candidate run.' }
Require-ComparisonBoundary -Value $oldGate -Label 'failed PBR-to-throughput gate'
$performerId = ([string]$oldGate.stash_performer_id).Trim()
if ([string]::IsNullOrWhiteSpace($performerId)) { throw 'PBR-to-throughput gate has no exact Stash performer id.' }
if ([IO.Path]::GetFullPath([string]$oldGate.pbr_run_dir) -ne [IO.Path]::GetFullPath($PbrRunDir)) { throw 'PBR run directory differs from the recorded PBR gate.' }

$pbrAuthorityPath = Need-File -Path (Join-Path $PbrRunDir 'plan-bound-human-review-authority.json') -Label 'PBR plan-bound human-review authority'
$pbrReviewPath = Need-File -Path (Join-Path $PbrRunDir 'human-review.json') -Label 'PBR human review'
$pbrAuthoritySha = File-Sha256 -Path $pbrAuthorityPath
$pbrReviewSha = File-Sha256 -Path $pbrReviewPath
if ($pbrAuthoritySha -ne (Need-Sha256 -Value ([string]$oldGate.pbr_human_review_authority_sha256) -Label 'PBR authority SHA in gate')) { throw 'PBR human-review authority bytes changed.' }
if ($pbrReviewSha -ne (Need-Sha256 -Value ([string]$oldGate.pbr_human_review_sha256) -Label 'PBR review SHA in gate')) { throw 'PBR human-review bytes changed.' }
$pbrReview = Read-Json -Path $pbrReviewPath -Label 'PBR human review'
if ($pbrReview.human_visual_review_confirmed -ne $true -or [string]$pbrReview.decision -ne [string]$oldGate.pbr_decision) { throw 'PBR human review is no longer the review bound by the sequencing gate.' }
Require-ComparisonBoundary -Value $pbrReview -Label 'PBR human review' -PromotionOptional

try { $failedJob = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/jobs/$FailedCandidateJobId" -TimeoutSec 10 }
catch { throw 'Failed throughput candidate job cannot be read from BodyRig.' }
$failedSource = $failedJob.source_enqueue_authority
if (
    [string]$failedJob.job_id -ne $FailedCandidateJobId -or
    [string]$failedJob.kind -ne 'body-build' -or
    [string]$failedJob.status -ne 'failed' -or
    [string]$failedJob.person_id -ne $personId -or
    (Need-Revision -Value ([string]$failedJob.bodyrig_revision) -Label 'failed job revision') -ne $PlannedThroughputRevision -or
    $null -eq $failedSource -or
    [string]$failedSource.person_id -ne $personId -or
    [string]$failedSource.stash_performer_id -ne $performerId
) { throw 'Failed job identity/source/revision does not match the planned throughput candidate.' }
$failedLogPath = Need-File -Path ([string]$failedJob.log_path) -Label 'failed throughput job log'
$failedLog = Get-Content -LiteralPath $failedLogPath -Raw -Encoding UTF8
if ($failedLog -notlike "*$ExpectedFailureNeedle*") { throw 'Failed candidate did not fail with the reviewed resume-signature defect.' }

$plannedFetchSpec = "+refs/heads/${PlannedThroughputRef}:refs/remotes/origin/${PlannedThroughputRef}"
$fixedFetchSpec = "+refs/heads/${FixedThroughputRef}:refs/remotes/origin/${FixedThroughputRef}"
$fetchRaw = @(& git -C $RepoRoot fetch --no-tags origin $plannedFetchSpec $fixedFetchSpec 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not fetch exact planned/fixed throughput refs: $($fetchRaw -join ' ')" }
$originPlanned = (& git -C $RepoRoot rev-parse "refs/remotes/origin/$PlannedThroughputRef").Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $originPlanned -ne $PlannedThroughputRevision) { throw 'Original planned throughput ref moved; retry migration is stale.' }
$originFixed = (& git -C $RepoRoot rev-parse "refs/remotes/origin/$FixedThroughputRef").Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $originFixed -ne $FixedThroughputRevision) { throw 'Fixed throughput ref is not at the reviewed green revision.' }
& git -C $RepoRoot merge-base --is-ancestor $PlannedThroughputRevision $FixedThroughputRevision
if ($LASTEXITCODE -ne 0) { throw 'Fixed throughput revision is not a descendant of the exact planned throughput revision.' }
$changedFiles = @(& git -C $RepoRoot diff --name-only "$PlannedThroughputRevision..$FixedThroughputRevision" -- 2>&1 | ForEach-Object { ([string]$_).Trim().Replace('\','/') } | Where-Object { $_ })
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect exact throughput fix diff.' }
$delta = @(Compare-Object -ReferenceObject @($ExpectedFixFiles | Sort-Object) -DifferenceObject @($changedFiles | Sort-Object))
if ($delta.Count -gt 0) { throw "Fixed throughput revision changed files outside the reviewed retry scope: $($changedFiles -join ', ')" }

$fixedSource = @(& git -C $RepoRoot show "${FixedThroughputRevision}:bodyrig/bridges/hmr2_resume_bridge.py" 2>&1)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect fixed hmr2_resume_bridge.py bytes.' }
$fixedText = $fixedSource -join "`n"
foreach ($needle in @('source_fps: float','effective_fps: float','_explicit_timing_matches_current','source_fps=source_fps','effective_fps=effective_fps')) {
    if ($fixedText -notlike "*$needle*") { throw "Fixed throughput implementation lacks reviewed timing-contract marker: $needle" }
}
$oldImplBlob = (& git -C $RepoRoot rev-parse "${PlannedThroughputRevision}:bodyrig/bridges/hmr2_resume_bridge.py").Trim().ToLowerInvariant()
$fixedImplBlob = (& git -C $RepoRoot rev-parse "${FixedThroughputRevision}:bodyrig/bridges/hmr2_resume_bridge.py").Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $oldImplBlob -notmatch '^[0-9a-f]{40}$' -or $fixedImplBlob -notmatch '^[0-9a-f]{40}$' -or $oldImplBlob -eq $fixedImplBlob) { throw 'Could not prove the exact hmr2 resume implementation delta.' }

try {
    $allJobs = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/jobs?person_id=$([uri]::EscapeDataString($personId))" -TimeoutSec 10
} catch { throw 'Could not inspect active jobs before throughput retry migration.' }
$active = @($allJobs.jobs | Where-Object { [string]$_.kind -eq 'body-build' -and [string]$_.status -in @('queued','running','cancelling') })
if ($active.Count -gt 0) { throw "A body-build is already active for ${personId}: $([string]$active[0].job_id)" }

Write-Host 'BodyRig throughput retry migration: preflight VERIFIED'
Write-Host "Failed candidate:    $FailedCandidateJobId @ $PlannedThroughputRevision"
Write-Host "Reviewed defect:     $ExpectedFailureNeedle"
Write-Host "Fixed candidate:     $FixedThroughputRef @ $FixedThroughputRevision"
Write-Host "Exact fix files:     $($changedFiles -join ', ')"
Write-Host 'Switching service/checkout to the exact fixed throughput revision...'

$updateScript = Need-File -Path (Join-Path $RepoRoot 'update-windows.ps1') -Label 'BodyRig updater'
$null = & $updateScript -Branch $FixedThroughputRef -NoBrowser -SkipPlan
Assert-Checkout -Root $RepoRoot -ExpectedBranch $FixedThroughputRef -ExpectedRevision $FixedThroughputRevision
Assert-ServiceRevision -ExpectedRevision $FixedThroughputRevision

$startScript = Need-File -Path (Join-Path $RepoRoot 'start-revision-bound-body-build.ps1') -Label 'revision-bound body-build launcher'
$startedRaw = @(& $startScript -PersonId $personId -ExpectedPerformerId $performerId -BaseUri $BaseUri)
if ($startedRaw.Count -ne 1) { throw 'Fixed throughput body-build launcher did not return exactly one machine-readable result.' }
try { $started = ([string]$startedRaw[0]) | ConvertFrom-Json -Depth 30 }
catch { throw 'Fixed throughput body-build launcher returned unreadable JSON.' }
$newJobId = [string]$started.job_id
$newSource = $started.source_enqueue_authority
if (
    $newJobId -notmatch '^job-[0-9a-f]{32}$' -or
    [string]$started.person_id -ne $personId -or
    (Need-Revision -Value ([string]$started.bodyrig_revision) -Label 'new throughput job revision') -ne $FixedThroughputRevision -or
    $null -eq $newSource -or
    [string]$newSource.person_id -ne $personId -or
    [string]$newSource.stash_performer_id -ne $performerId -or
    (Need-Revision -Value ([string]$newSource.expected_bodyrig_revision) -Label 'new job source revision') -ne $FixedThroughputRevision
) {
    if ($newJobId -match '^job-[0-9a-f]{32}$') { $cancel = Try-CancelJob -JobId $newJobId } else { $cancel = 'no canonical job id returned' }
    throw "Fixed throughput enqueue authority mismatch; $cancel."
}

try {
    $postFetch = @(& git -C $RepoRoot fetch --no-tags origin $fixedFetchSpec 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "fixed ref refresh failed: $($postFetch -join ' ')" }
    $originFixedAfter = (& git -C $RepoRoot rev-parse "refs/remotes/origin/$FixedThroughputRef").Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $originFixedAfter -ne $FixedThroughputRevision) { throw 'fixed throughput ref moved after enqueue' }
    Assert-Checkout -Root $RepoRoot -ExpectedBranch $FixedThroughputRef -ExpectedRevision $FixedThroughputRevision
    Assert-ServiceRevision -ExpectedRevision $FixedThroughputRevision
} catch {
    $cancel = Try-CancelJob -JobId $newJobId
    throw "Fixed throughput authority drifted after enqueue; $cancel. $($_.Exception.Message)"
}

$retryAuthorityPath = Join-Path $planRoot "$BaselineJobId-throughput-retry-$newJobId.json"
$retryAuthority = [ordered]@{
    format = 'bodyrig-throughput-retry-after-resume-signature-fix'
    version = 1
    baseline_job_id = $BaselineJobId
    baseline_plan_sha256 = $sharedPlanSha
    person_id = $personId
    stash_performer_id = $performerId
    pbr_run_dir = $PbrRunDir
    pbr_human_review_authority_sha256 = $pbrAuthoritySha
    pbr_human_review_sha256 = $pbrReviewSha
    pbr_decision = [string]$oldGate.pbr_decision
    original_pbr_to_throughput_gate_sha256 = $oldGateSha
    failed_candidate_job_id = $FailedCandidateJobId
    failed_candidate_run_plan_sha256 = $oldRunPlanSha
    failed_candidate_ref = $PlannedThroughputRef
    failed_candidate_revision = $PlannedThroughputRevision
    failure_signature = $ExpectedFailureNeedle
    fixed_candidate_ref = $FixedThroughputRef
    fixed_candidate_revision = $FixedThroughputRevision
    old_resume_bridge_blob_sha1 = $oldImplBlob
    fixed_resume_bridge_blob_sha1 = $fixedImplBlob
    reviewed_fix_files = @($changedFiles)
    candidate_job_id = $newJobId
    candidate_status_at_publish = [string]$started.status
    candidate_source_enqueue_authority = $newSource
    comparison_only = $true
    human_visual_authority_recorded = $true
    human_visual_authority_required = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
    created_at = [DateTime]::UtcNow.ToString('o')
}
try { Write-CreateOnlyJson -Path $retryAuthorityPath -Value $retryAuthority }
catch {
    $cancel = Try-CancelJob -JobId $newJobId
    throw "Could not publish create-only throughput retry authority; $cancel. $($_.Exception.Message)"
}

Write-Host ''
Write-Host 'BodyRig throughput retry candidate: STARTED'
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "Failed candidate:   $FailedCandidateJobId"
Write-Host "Fixed revision:     $FixedThroughputRevision"
Write-Host "Person:             $personId"
Write-Host "Stash performer:    $performerId"
Write-Host "Candidate job:      $newJobId"
Write-Host "Retry authority:    $retryAuthorityPath"
Write-Host 'Authority: comparison-only retry after exact reviewed software defect; no physical acceptance, promotion or production activation.'
Write-Host 'Do not run the ordinary plan-bound throughput continuation; this retry requires the matching retry continuation after the job succeeds.'

$retryAuthority | ConvertTo-Json -Depth 50 -Compress
