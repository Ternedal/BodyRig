param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$CandidateJobId,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [string]$OutRoot = '',

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')]
    [string]$BaseUri = 'http://127.0.0.1:8775'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBaselineRevision = '6e10351e4eba929062960ac46ec1582a467db259'
$ExpectedFailedRevision = 'ec743446d98809d693d01e51830f435fc3c09535'
$ExpectedFixedRef = 'fix/throughput-v3-resume-signature-20260910'
$ExpectedFixedRevision = '5fa01deb08399fda64e83db1329d4d2e83ad1bc2'
$ExpectedFailedJobId = 'job-164250c1d8e04f66a8f8f6cf646c1a31'
$ExpectedFailureNeedle = "_load_canonical_checkpoint() got an unexpected keyword argument 'source_fps'"

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
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60 }
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
    $value2 = $Value.Trim().ToLowerInvariant()
    if ($value2 -notmatch '^[0-9a-f]{40}$') { throw "$Label is not an exact Git revision." }
    return $value2
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $value2 = $Value.Trim().ToLowerInvariant()
    if ($value2 -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $value2
}

function Require-ComparisonBoundary {
    param([Parameter(Mandatory = $true)]$Value,[Parameter(Mandatory = $true)][string]$Label)
    if (
        $Value.comparison_only -ne $true -or
        $Value.physical_acceptance_authority -ne $false -or
        $Value.promotion_authority -ne $false -or
        $Value.production_activation -ne $false
    ) { throw "$Label crossed the comparison-only authority boundary." }
}

function Invoke-ReceiptProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$JobId,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$PersonId,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH','Process')
    $oldNoBytecode = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE','Process')
    try {
        $bound = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" }
        [Environment]::SetEnvironmentVariable('PYTHONPATH',$bound,'Process')
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE','1','Process')
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.body_job_receipt_authority as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound $Label module." }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepoRoot 'bodyrig\body_job_receipt_authority.py'))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) { throw "$Label imported from wrong checkout: $actualModule" }
        $raw = @(& $Python -m bodyrig.body_job_receipt_authority --job-id $JobId --expected-revision $ExpectedRevision --expected-person-id $PersonId 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "$Label failed: $($raw -join ' ')" }
        try { $receipt = ([string]$raw[0]) | ConvertFrom-Json -Depth 50 }
        catch { throw "$Label returned unreadable JSON." }
        if ([string]$receipt.format -ne 'bodyrig-succeeded-body-job-receipt-authority' -or [int]$receipt.version -ne 1) { throw "$Label returned wrong format/version." }
        Require-ComparisonBoundary -Value $receipt -Label $Label
        return $receipt
    }
    finally {
        [Environment]::SetEnvironmentVariable('PYTHONPATH',$oldPythonPath,'Process')
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE',$oldNoBytecode,'Process')
    }
}

function Assert-CheckoutAndService {
    $branchRaw = @(& git -C $RepoRoot branch --show-current 2>&1)
    if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne $ExpectedFixedRef) { throw "Checkout must remain attached to $ExpectedFixedRef." }
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or (Need-Revision -Value ([string]$headRaw[0]) -Label 'checkout HEAD') -ne $ExpectedFixedRevision) { throw 'Checkout is not at the exact reviewed fixed throughput revision.' }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw 'Fixed throughput checkout must be clean.' }
    try { $service = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/operator-authority" -TimeoutSec 5 }
    catch { throw 'BodyRig operator authority endpoint is unavailable.' }
    if ($service.ok -ne $true -or (Need-Revision -Value ([string]$service.bodyrig_revision) -Label 'service revision') -ne $ExpectedFixedRevision) { throw 'BodyRig service is not bound to the exact fixed throughput revision.' }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite retry continuation authority: $Path" }
    $Value | ConvertTo-Json -Depth 60 | Set-Content -LiteralPath $Path -Encoding UTF8 -NoNewline
    Add-Content -LiteralPath $Path -Value "`n" -Encoding UTF8
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw 'BodyRig throughput retry continuation is Windows-only.' }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ is required.' }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required.' }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
Need-Directory -Path (Join-Path $RepoRoot '.git') -Label 'BodyRig Git checkout' | Out-Null
$python = Need-File -Path (Join-Path $RepoRoot '.venv\Scripts\python.exe') -Label 'BodyRig Python'
Assert-CheckoutAndService

$dataRoot = if (-not [string]::IsNullOrWhiteSpace($env:BODYRIG_DATA_DIR)) { [IO.Path]::GetFullPath($env:BODYRIG_DATA_DIR) } else { Join-Path $env:LOCALAPPDATA 'BodyRig' }
$planRoot = Join-Path $env:LOCALAPPDATA 'BodyRig\ab-baseline-plans'
$retryPath = Need-File -Path (Join-Path $planRoot "$BaselineJobId-throughput-retry-$CandidateJobId.json") -Label 'throughput retry authority'
$retry = Read-Json -Path $retryPath -Label 'throughput retry authority'
$retrySha = File-Sha256 -Path $retryPath
if (
    [string]$retry.format -ne 'bodyrig-throughput-retry-after-resume-signature-fix' -or [int]$retry.version -ne 1 -or
    [string]$retry.baseline_job_id -ne $BaselineJobId -or [string]$retry.candidate_job_id -ne $CandidateJobId -or
    [string]$retry.failed_candidate_job_id -ne $ExpectedFailedJobId -or
    (Need-Revision -Value ([string]$retry.failed_candidate_revision) -Label 'retry failed revision') -ne $ExpectedFailedRevision -or
    [string]$retry.failure_signature -ne $ExpectedFailureNeedle -or
    [string]$retry.fixed_candidate_ref -ne $ExpectedFixedRef -or
    (Need-Revision -Value ([string]$retry.fixed_candidate_revision) -Label 'retry fixed revision') -ne $ExpectedFixedRevision -or
    $retry.human_visual_authority_recorded -ne $true -or $retry.human_visual_authority_required -ne $true
) { throw 'Retry authority does not match the reviewed physical-defect migration.' }
Require-ComparisonBoundary -Value $retry -Label 'throughput retry authority'
$personId = [string]$retry.person_id
$performerId = [string]$retry.stash_performer_id
if ($personId -notmatch '^person-[0-9a-f]{32}$' -or [string]::IsNullOrWhiteSpace($performerId)) { throw 'Retry authority has invalid Person/Stash identity.' }

$sharedPlanPath = Need-File -Path (Join-Path $planRoot "$BaselineJobId.json") -Label 'shared baseline plan'
if ((File-Sha256 -Path $sharedPlanPath) -ne (Need-Sha256 -Value ([string]$retry.baseline_plan_sha256) -Label 'retry baseline plan SHA')) { throw 'Shared baseline plan bytes changed after retry migration.' }
$sharedPlan = Read-Json -Path $sharedPlanPath -Label 'shared baseline plan'
if ((Need-Revision -Value ([string]$sharedPlan.baseline_bodyrig_revision) -Label 'baseline revision') -ne $ExpectedBaselineRevision -or [string]$sharedPlan.person_id -ne $personId) { throw 'Shared baseline plan no longer matches retry authority.' }
Require-ComparisonBoundary -Value $sharedPlan -Label 'shared baseline plan'

$oldGatePath = Need-File -Path (Join-Path $planRoot "$BaselineJobId-throughput-$ExpectedFailedJobId-pbr-gate.json") -Label 'original PBR-to-throughput gate'
if ((File-Sha256 -Path $oldGatePath) -ne (Need-Sha256 -Value ([string]$retry.original_pbr_to_throughput_gate_sha256) -Label 'retry original PBR gate SHA')) { throw 'Original PBR-to-throughput gate bytes changed.' }
$oldGate = Read-Json -Path $oldGatePath -Label 'original PBR-to-throughput gate'
Require-ComparisonBoundary -Value $oldGate -Label 'original PBR-to-throughput gate'
if ([string]$oldGate.person_id -ne $personId -or [string]$oldGate.stash_performer_id -ne $performerId -or [string]$oldGate.pbr_decision -ne [string]$retry.pbr_decision) { throw 'Original PBR gate identity/decision differs from retry authority.' }

$pbrRun = Need-Directory -Path ([string]$retry.pbr_run_dir) -Label 'PBR run directory'
$pbrAuthority = Need-File -Path (Join-Path $pbrRun 'plan-bound-human-review-authority.json') -Label 'PBR plan-bound human-review authority'
$pbrReview = Need-File -Path (Join-Path $pbrRun 'human-review.json') -Label 'PBR human review'
if ((File-Sha256 -Path $pbrAuthority) -ne (Need-Sha256 -Value ([string]$retry.pbr_human_review_authority_sha256) -Label 'retry PBR authority SHA')) { throw 'PBR authority bytes changed.' }
if ((File-Sha256 -Path $pbrReview) -ne (Need-Sha256 -Value ([string]$retry.pbr_human_review_sha256) -Label 'retry PBR review SHA')) { throw 'PBR human-review bytes changed.' }

$failedJobPath = Need-File -Path (Join-Path $dataRoot "ui-jobs\$ExpectedFailedJobId\job.json") -Label 'failed candidate job'
$failedJob = Read-Json -Path $failedJobPath -Label 'failed candidate job'
if ([string]$failedJob.status -ne 'failed' -or [string]$failedJob.person_id -ne $personId -or (Need-Revision -Value ([string]$failedJob.bodyrig_revision) -Label 'failed job revision') -ne $ExpectedFailedRevision) { throw 'Original failed job no longer matches retry authority.' }
$failedLogPath = Need-File -Path ([string]$failedJob.log_path) -Label 'failed candidate log'
if ((Get-Content -LiteralPath $failedLogPath -Raw -Encoding UTF8) -notlike "*$ExpectedFailureNeedle*") { throw 'Original failed job no longer contains the reviewed defect signature.' }

$baselineJobPath = Need-File -Path (Join-Path $dataRoot "ui-jobs\$BaselineJobId\job.json") -Label 'baseline job'
$candidateJobPath = Need-File -Path (Join-Path $dataRoot "ui-jobs\$CandidateJobId\job.json") -Label 'fixed candidate job'
$baselineJob = Read-Json -Path $baselineJobPath -Label 'baseline job'
$candidateJob = Read-Json -Path $candidateJobPath -Label 'fixed candidate job'
if ([string]$baselineJob.status -ne 'succeeded' -or [string]$baselineJob.person_id -ne $personId -or (Need-Revision -Value ([string]$baselineJob.bodyrig_revision) -Label 'baseline job revision') -ne $ExpectedBaselineRevision) { throw 'Baseline job is not the exact succeeded baseline.' }
if ([string]$candidateJob.status -ne 'succeeded' -or [string]$candidateJob.person_id -ne $personId -or (Need-Revision -Value ([string]$candidateJob.bodyrig_revision) -Label 'candidate job revision') -ne $ExpectedFixedRevision) { throw 'Retry candidate job is not succeeded on the exact fixed revision.' }

$sourceAuthority = $candidateJob.source_enqueue_authority
if ($null -eq $sourceAuthority -or [string]$sourceAuthority.person_id -ne $personId -or [string]$sourceAuthority.stash_performer_id -ne $performerId -or (Need-Revision -Value ([string]$sourceAuthority.expected_bodyrig_revision) -Label 'candidate source revision') -ne $ExpectedFixedRevision) { throw 'Retry candidate source enqueue authority mismatch.' }

$fetchMain = '+refs/heads/main:refs/remotes/origin/main'
$fetchOld = '+refs/heads/candidate/recovery-throughput-v3-current-main-20260908:refs/remotes/origin/candidate/recovery-throughput-v3-current-main-20260908'
$fetchFixed = "+refs/heads/${ExpectedFixedRef}:refs/remotes/origin/${ExpectedFixedRef}"
$fetchRaw = @(& git -C $RepoRoot fetch --no-tags origin $fetchMain $fetchOld $fetchFixed 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not refresh retry-bound refs: $($fetchRaw -join ' ')" }
if ((Need-Revision -Value ((& git -C $RepoRoot rev-parse refs/remotes/origin/main).Trim()) -Label 'origin/main') -ne $ExpectedBaselineRevision) { throw 'origin/main moved after baseline evidence.' }
if ((Need-Revision -Value ((& git -C $RepoRoot rev-parse refs/remotes/origin/candidate/recovery-throughput-v3-current-main-20260908).Trim()) -Label 'origin planned candidate') -ne $ExpectedFailedRevision) { throw 'Original throughput candidate ref moved.' }
if ((Need-Revision -Value ((& git -C $RepoRoot rev-parse "refs/remotes/origin/$ExpectedFixedRef").Trim()) -Label 'origin fixed candidate') -ne $ExpectedFixedRevision) { throw 'Fixed throughput ref moved.' }
Assert-CheckoutAndService

$baselineReceipts = Invoke-ReceiptProbe -Python $python -JobId $BaselineJobId -ExpectedRevision $ExpectedBaselineRevision -PersonId $personId -Label 'baseline body-job receipt authority'
$candidateReceipts = Invoke-ReceiptProbe -Python $python -JobId $CandidateJobId -ExpectedRevision $ExpectedFixedRevision -PersonId $personId -Label 'retry candidate body-job receipt authority'
if (
    [string]$baselineReceipts.stash_performer_id -ne $performerId -or [string]$candidateReceipts.stash_performer_id -ne $performerId -or
    [string]$baselineReceipts.source_evidence_kind -ne 'stash-physical-source-manifest-v1' -or [string]$candidateReceipts.source_evidence_kind -ne 'stash-physical-source-manifest-v1' -or
    [string]$baselineReceipts.source_evidence_sha256 -ne [string]$candidateReceipts.source_evidence_sha256 -or
    [string]$baselineReceipts.source_files_sha256 -ne [string]$candidateReceipts.source_files_sha256
) { throw 'Baseline and retry candidate are not bound to the same exact Stash physical source bytes.' }
$sourceManifestSha = Need-Sha256 -Value ([string]$baselineReceipts.source_evidence_sha256) -Label 'shared source manifest SHA'
$sourceFilesSha = Need-Sha256 -Value ([string]$baselineReceipts.source_files_sha256) -Label 'shared source-files SHA'

if ([string]::IsNullOrWhiteSpace($OutRoot)) { $OutRoot = Join-Path $dataRoot "recovery-throughput-retry-bound\$BaselineJobId--$CandidateJobId" }
$finalRoot = [IO.Path]::GetFullPath($OutRoot)
if (Test-Path -LiteralPath $finalRoot) { throw "Refusing to overwrite existing retry review output: $finalRoot" }
$parent = Split-Path -Parent $finalRoot
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
$tempRoot = Join-Path $parent ('.' + [IO.Path]::GetFileName($finalRoot) + '.tmp-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot -ErrorAction Stop | Out-Null

try {
    $machinePath = Join-Path $tempRoot 'machine-audit.json'
    $bundleDir = Join-Path $tempRoot 'review-bundle'
    $continuationPath = Join-Path $tempRoot 'continuation-authority.json'
    $compare = Need-File -Path (Join-Path $RepoRoot 'compare-recovery-throughput.ps1') -Label 'throughput machine A/B audit'
    $bundle = Need-File -Path (Join-Path $RepoRoot 'build-recovery-throughput-review-bundle.ps1') -Label 'throughput review bundle builder'

    & $compare -BaselineJobId $BaselineJobId -CandidateJobId $CandidateJobId -BaselineBodyRigRevision $ExpectedBaselineRevision -Out $machinePath -RepoRoot $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw 'Retry-bound throughput machine A/B failed.' }
    $machine = Read-Json -Path $machinePath -Label 'retry machine A/B'
    if ([string]$machine.format -ne 'bodyrig-recovery-throughput-sampling-audit' -or [int]$machine.version -ne 1 -or $machine.machine_evidence_pass -ne $true -or [string]$machine.decision -ne 'eligible-for-human-ab-review' -or [string]$machine.baseline_job_id -ne $BaselineJobId -or [string]$machine.candidate_job_id -ne $CandidateJobId -or (Need-Revision -Value ([string]$machine.baseline_bodyrig_revision) -Label 'machine baseline revision') -ne $ExpectedBaselineRevision -or (Need-Revision -Value ([string]$machine.candidate_bodyrig_revision) -Label 'machine candidate revision') -ne $ExpectedFixedRevision -or $machine.promotion_authority -ne $false -or $machine.production_activation -ne $false) { throw 'Retry machine A/B did not preserve exact job/revision authority.' }

    & $bundle -BaselineJobId $BaselineJobId -CandidateJobId $CandidateJobId -BaselineBodyRigRevision $ExpectedBaselineRevision -Out $bundleDir -RepoRoot $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw 'Retry throughput review bundle build failed.' }
    $bundleReceiptPath = Need-File -Path (Join-Path $bundleDir 'review-bundle.json') -Label 'retry review-bundle receipt'
    $bundleReceipt = Read-Json -Path $bundleReceiptPath -Label 'retry review-bundle receipt'
    if ([string]$bundleReceipt.format -ne 'bodyrig-recovery-throughput-review-bundle' -or [int]$bundleReceipt.version -ne 1 -or [string]$bundleReceipt.baseline_job_id -ne $BaselineJobId -or [string]$bundleReceipt.candidate_job_id -ne $CandidateJobId -or (Need-Revision -Value ([string]$bundleReceipt.baseline_bodyrig_revision) -Label 'bundle baseline revision') -ne $ExpectedBaselineRevision -or (Need-Revision -Value ([string]$bundleReceipt.candidate_bodyrig_revision) -Label 'bundle candidate revision') -ne $ExpectedFixedRevision -or $bundleReceipt.human_visual_review_required -ne $true -or $bundleReceipt.promotion_authority -ne $false -or $bundleReceipt.production_activation -ne $false) { throw 'Retry review bundle crossed authority or revision boundary.' }

    Assert-CheckoutAndService
    if ((File-Sha256 -Path $retryPath) -ne $retrySha) { throw 'Retry authority changed while review evidence was generated.' }
    $baselineReceiptsAfter = Invoke-ReceiptProbe -Python $python -JobId $BaselineJobId -ExpectedRevision $ExpectedBaselineRevision -PersonId $personId -Label 'post-review baseline receipt authority'
    $candidateReceiptsAfter = Invoke-ReceiptProbe -Python $python -JobId $CandidateJobId -ExpectedRevision $ExpectedFixedRevision -PersonId $personId -Label 'post-review candidate receipt authority'
    foreach ($field in @('stash_performer_id','source_evidence_sha256','source_files_sha256','body_revision','canonical_body_id','package_sha256','body_review_sha256')) {
        if ([string]$baselineReceipts.$field -ne [string]$baselineReceiptsAfter.$field) { throw "Baseline receipt changed during review generation: $field" }
        if ([string]$candidateReceipts.$field -ne [string]$candidateReceiptsAfter.$field) { throw "Candidate receipt changed during review generation: $field" }
    }

    $authority = [ordered]@{
        format = 'bodyrig-throughput-retry-review-continuation'
        version = 1
        baseline_job_id = $BaselineJobId
        candidate_job_id = $CandidateJobId
        failed_candidate_job_id = $ExpectedFailedJobId
        person_id = $personId
        stash_performer_id = $performerId
        baseline_bodyrig_revision = $ExpectedBaselineRevision
        failed_candidate_revision = $ExpectedFailedRevision
        fixed_candidate_ref = $ExpectedFixedRef
        fixed_candidate_revision = $ExpectedFixedRevision
        retry_authority_sha256 = $retrySha
        baseline_plan_sha256 = [string]$retry.baseline_plan_sha256
        original_pbr_to_throughput_gate_sha256 = [string]$retry.original_pbr_to_throughput_gate_sha256
        pbr_human_review_authority_sha256 = [string]$retry.pbr_human_review_authority_sha256
        pbr_human_review_sha256 = [string]$retry.pbr_human_review_sha256
        pbr_decision = [string]$retry.pbr_decision
        failure_signature = $ExpectedFailureNeedle
        baseline_body_revision = [string]$baselineReceipts.body_revision
        candidate_body_revision = [string]$candidateReceipts.body_revision
        baseline_canonical_body_id = [string]$baselineReceipts.canonical_body_id
        candidate_canonical_body_id = [string]$candidateReceipts.canonical_body_id
        baseline_job_json_sha256 = [string]$baselineReceipts.job_json_sha256
        candidate_job_json_sha256 = [string]$candidateReceipts.job_json_sha256
        baseline_body_review_sha256 = [string]$baselineReceipts.body_review_sha256
        candidate_body_review_sha256 = [string]$candidateReceipts.body_review_sha256
        source_evidence_kind = 'stash-physical-source-manifest-v1'
        source_evidence_sha256 = $sourceManifestSha
        source_files_sha256 = $sourceFilesSha
        source_performer_parity_verified = $true
        source_manifest_parity_verified = $true
        source_file_hashes_parity_verified = $true
        machine_audit_sha256 = File-Sha256 -Path $machinePath
        review_bundle_receipt_sha256 = File-Sha256 -Path $bundleReceiptPath
        comparison_only = $true
        human_visual_authority_required = $true
        physical_acceptance_authority = $false
        promotion_authority = $false
        production_activation = $false
        created_at = [DateTime]::UtcNow.ToString('o')
    }
    Write-CreateOnlyJson -Path $continuationPath -Value $authority
    Move-Item -LiteralPath $tempRoot -Destination $finalRoot
}
catch {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
    throw
}

$finalBundle = Join-Path $finalRoot 'review-bundle'
Write-Host ''
Write-Host 'BodyRig throughput retry A/B: READY FOR EXPLICIT HUMAN REVIEW'
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "Candidate job:      $CandidateJobId"
Write-Host "Candidate revision: $ExpectedFixedRevision"
Write-Host "Stash performer:    $performerId"
Write-Host "Source manifest:    $sourceManifestSha"
Write-Host "Review bundle:      $finalBundle"
Write-Host "Open:               $(Join-Path $finalBundle 'index.html')"
Write-Host "Continuation auth:  $(Join-Path $finalRoot 'continuation-authority.json')"
Write-Host 'Authority: comparison-only retry chain; human decision required; no physical acceptance, promotion or production activation.'
Write-Host "Next recorder (after reviewing all four views): retry-bound recorder for $CandidateJobId"
