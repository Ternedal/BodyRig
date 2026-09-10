param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$CandidateJobId,

    [Parameter(Mandatory = $true)]
    [string]$RunDir,

    [Parameter(Mandatory = $true)][ValidateSet('pass','fail')][string]$IdentityShape,
    [Parameter(Mandatory = $true)][ValidateSet('pass','fail')][string]$FaceIdentity,
    [Parameter(Mandatory = $true)][ValidateSet('pass','fail')][string]$SkinTextureAlignment,
    [Parameter(Mandatory = $true)][ValidateSet('pass','fail')][string]$GrossAnatomy,
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$Note,
    [Parameter(Mandatory = $true)][switch]$ConfirmVisualReview,

    [string]$Reviewer = '',
    [string]$Out = '',
    [Parameter(Mandatory = $true)][string]$RepoRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedFixedRef = 'fix/throughput-v3-resume-signature-20260910'
$ExpectedFixedRevision = '5fa01deb08399fda64e83db1329d4d2e83ad1bc2'
$ExpectedFailedJobId = 'job-164250c1d8e04f66a8f8f6cf646c1a31'

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
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
function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite retry human-review authority: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $Value | ConvertTo-Json -Depth 60 | Set-Content -LiteralPath $Path -Encoding UTF8
}

if (-not $ConfirmVisualReview) { throw 'Pass -ConfirmVisualReview only after visually comparing all four canonical baseline/candidate views.' }
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw 'BodyRig throughput retry human review is Windows-only.' }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ is required.' }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }
if ([string]::IsNullOrWhiteSpace($Note.Trim())) { throw 'A non-empty human review note is required.' }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$RunDir = (Resolve-Path -LiteralPath $RunDir).Path

$branch = (& git -C $RepoRoot branch --show-current).Trim()
$head = (& git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant()
$dirty = @(& git -C $RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0 -or $branch -ne $ExpectedFixedRef -or (Need-Revision -Value $head -Label 'checkout HEAD') -ne $ExpectedFixedRevision -or $dirty.Count -gt 0) { throw 'Human review must run from the exact clean fixed throughput checkout.' }

$continuationPath = Need-File -Path (Join-Path $RunDir 'continuation-authority.json') -Label 'retry continuation authority'
$continuation = Read-Json -Path $continuationPath -Label 'retry continuation authority'
if (
    [string]$continuation.format -ne 'bodyrig-throughput-retry-review-continuation' -or [int]$continuation.version -ne 1 -or
    [string]$continuation.baseline_job_id -ne $BaselineJobId -or [string]$continuation.candidate_job_id -ne $CandidateJobId -or
    [string]$continuation.failed_candidate_job_id -ne $ExpectedFailedJobId -or
    [string]$continuation.fixed_candidate_ref -ne $ExpectedFixedRef -or
    (Need-Revision -Value ([string]$continuation.fixed_candidate_revision) -Label 'continuation fixed revision') -ne $ExpectedFixedRevision -or
    $continuation.comparison_only -ne $true -or $continuation.human_visual_authority_required -ne $true -or
    $continuation.physical_acceptance_authority -ne $false -or $continuation.promotion_authority -ne $false -or $continuation.production_activation -ne $false
) { throw 'Retry continuation authority is invalid or crossed authority boundaries.' }
$continuationSha = File-Sha256 -Path $continuationPath

$retryPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-retry-$CandidateJobId.json") -Label 'retry migration authority'
if ((File-Sha256 -Path $retryPath) -ne (Need-Sha256 -Value ([string]$continuation.retry_authority_sha256) -Label 'continuation retry-authority SHA')) { throw 'Retry migration authority bytes changed after continuation.' }
$retry = Read-Json -Path $retryPath -Label 'retry migration authority'
if ([string]$retry.candidate_job_id -ne $CandidateJobId -or [string]$retry.person_id -ne [string]$continuation.person_id -or [string]$retry.stash_performer_id -ne [string]$continuation.stash_performer_id -or (Need-Revision -Value ([string]$retry.fixed_candidate_revision) -Label 'retry fixed revision') -ne $ExpectedFixedRevision) { throw 'Retry migration authority no longer matches continuation.' }

$bundleDir = Join-Path $RunDir 'review-bundle'
$bundleReceipt = Need-File -Path (Join-Path $bundleDir 'review-bundle.json') -Label 'review bundle receipt'
$machinePath = Need-File -Path (Join-Path $RunDir 'machine-audit.json') -Label 'retry machine audit'
if ((File-Sha256 -Path $bundleReceipt) -ne (Need-Sha256 -Value ([string]$continuation.review_bundle_receipt_sha256) -Label 'continuation bundle SHA')) { throw 'Review bundle bytes changed after continuation.' }
if ((File-Sha256 -Path $machinePath) -ne (Need-Sha256 -Value ([string]$continuation.machine_audit_sha256) -Label 'continuation machine SHA')) { throw 'Machine A/B bytes changed after continuation.' }

if ([string]::IsNullOrWhiteSpace($Out)) { $Out = "$RunDir.human-review.json" }
$Out = [IO.Path]::GetFullPath($Out)
$authorityOut = "$RunDir.retry-human-review-authority.json"
if (Test-Path -LiteralPath $Out) { throw "Refusing to overwrite existing human review: $Out" }
if (Test-Path -LiteralPath $authorityOut) { throw "Retry human-review authority already exists: $authorityOut" }

$recorder = Need-File -Path (Join-Path $RepoRoot 'record-recovery-throughput-human-review.ps1') -Label 'candidate-owned human review recorder'
$params = @{
    BundleDir = $bundleDir
    IdentityShape = $IdentityShape
    FaceIdentity = $FaceIdentity
    SkinTextureAlignment = $SkinTextureAlignment
    GrossAnatomy = $GrossAnatomy
    Note = $Note.Trim()
    Out = $Out
    RepoRoot = $RepoRoot
}
if (-not [string]::IsNullOrWhiteSpace($Reviewer)) { $params.Reviewer = $Reviewer.Trim() }
& $recorder @params
if ($LASTEXITCODE -ne 0) { throw 'Candidate-owned throughput human review recorder failed.' }

$reviewPath = Need-File -Path $Out -Label 'throughput human review receipt'
$review = Read-Json -Path $reviewPath -Label 'throughput human review receipt'
if (
    [string]$review.format -ne 'bodyrig-recovery-throughput-human-review' -or [int]$review.version -ne 1 -or
    [string]$review.baseline_job_id -ne $BaselineJobId -or [string]$review.candidate_job_id -ne $CandidateJobId -or
    [string]$review.person_id -ne [string]$continuation.person_id -or
    (Need-Revision -Value ([string]$review.candidate_bodyrig_revision) -Label 'human review candidate revision') -ne $ExpectedFixedRevision -or
    $review.human_visual_review_completed -ne $true -or $review.promotion_authority -ne $false -or $review.production_activation -ne $false
) { throw 'Human review receipt does not match retry continuation authority.' }
if ([string]$review.review_bundle_receipt_sha256 -ne [string]$continuation.review_bundle_receipt_sha256 -or [string]$review.machine_audit_sha256 -ne [string]$continuation.machine_audit_sha256) { throw 'Human review does not bind the exact retry review bundle/machine audit.' }
if ((File-Sha256 -Path $continuationPath) -ne $continuationSha) { throw 'Continuation authority changed during human review.' }

$authority = [ordered]@{
    format = 'bodyrig-throughput-retry-human-review-authority'
    version = 1
    baseline_job_id = $BaselineJobId
    candidate_job_id = $CandidateJobId
    failed_candidate_job_id = $ExpectedFailedJobId
    person_id = [string]$continuation.person_id
    stash_performer_id = [string]$continuation.stash_performer_id
    fixed_candidate_ref = $ExpectedFixedRef
    fixed_candidate_revision = $ExpectedFixedRevision
    retry_authority_sha256 = [string]$continuation.retry_authority_sha256
    continuation_authority_sha256 = $continuationSha
    review_bundle_receipt_sha256 = [string]$review.review_bundle_receipt_sha256
    machine_audit_sha256 = [string]$review.machine_audit_sha256
    human_review_sha256 = (File-Sha256 -Path $reviewPath)
    human_visual_review_completed = $true
    human_visual_review_passed = [bool]$review.human_visual_review_passed
    decision = [string]$review.decision
    next_gate = [string]$review.next_gate
    criteria = $review.criteria
    note = [string]$review.note
    reviewer = [string]$review.reviewer
    comparison_only = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
    created_at = [DateTime]::UtcNow.ToString('o')
}
Write-CreateOnlyJson -Path $authorityOut -Value $authority

Write-Host ''
Write-Host 'BodyRig throughput retry human review: RECORDED'
Write-Host "Decision:       $([string]$review.decision)"
Write-Host "Visual PASS:    $([bool]$review.human_visual_review_passed)"
Write-Host "Human receipt:  $reviewPath"
Write-Host "Retry authority:$authorityOut"
Write-Host "Next gate:      $([string]$review.next_gate)"
Write-Host 'Authority: human comparison evidence only; no physical acceptance, promotion or production activation.'
