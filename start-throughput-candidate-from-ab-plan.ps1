param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [string]$PbrRunDir,

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')]
    [string]$BaseUri = "http://127.0.0.1:8775",

    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-JsonObject {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $Path" }
    if ($null -eq $value) { throw "$Label is empty: $Path" }
    return $value
}

function Require-ExactFields {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    $delta = @(Compare-Object -ReferenceObject $wanted -DifferenceObject $actual)
    if ($delta.Count -gt 0) {
        throw "$Label fields do not match the canonical contract."
    }
}

function Invoke-CheckoutPythonJson {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Module,
        [Parameter(Mandatory = $true)][string]$ExpectedModulePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $oldPythonPath = [string]$env:PYTHONPATH
    $oldNoBytecode = [string]$env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" })
        $env:PYTHONDONTWRITEBYTECODE = "1"

        $probeRaw = @(& $Python -c "import importlib,pathlib; m=importlib.import_module('$Module'); print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $probeRaw.Count -ne 1) {
            throw "Could not prove checkout-bound $Label module: $($probeRaw -join ' ')"
        }
        $expectedPath = [IO.Path]::GetFullPath((Join-Path $RepoRoot $ExpectedModulePath))
        $actualPath = [IO.Path]::GetFullPath(([string]$probeRaw[0]).Trim())
        if (-not [string]::Equals($actualPath, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
            throw "$Label module imported from wrong checkout: $actualPath"
        }

        $raw = @(& $Python -m $Module @Arguments 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) {
            throw "$Label failed: $($raw -join ' ')"
        }
        try { return (([string]$raw[0]) | ConvertFrom-Json) }
        catch { throw "$Label returned unreadable JSON." }
    }
    finally {
        if ([string]::IsNullOrEmpty($oldPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
        if ([string]::IsNullOrEmpty($oldNoBytecode)) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode }
    }
}

function Try-CancelCandidateJob {
    param(
        [Parameter(Mandatory = $true)][string]$JobId,
        [Parameter(Mandatory = $true)][string]$UriBase
    )
    try {
        $result = Invoke-RestMethod -Method Post -Uri "$UriBase/api/v1/jobs/$JobId/cancel" -TimeoutSec 10
        $status = [string]$result.status
        if ([string]$result.job_id -ne $JobId -or $status -notin @("canceled", "cancelling")) {
            return "cancel endpoint returned unexpected state '$status'"
        }
        return "cancel requested successfully ($status)"
    }
    catch {
        return "cancel request failed: $($_.Exception.Message)"
    }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite throughput candidate run plan: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temp -Encoding utf8
        Move-Item -LiteralPath $temp -Destination $Path
    }
    finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig throughput candidate launcher is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for revision-bound throughput candidate runs."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required for A/B plan authority."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$planPath = Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId.json"
$planPath = Need-File -Path $planPath -Label "shared A/B baseline plan"
$plan = Read-JsonObject -Path $planPath -Label "shared A/B baseline plan"
$planSha256 = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()

Require-ExactFields -Value $plan -Label "shared A/B baseline plan" -Expected @(
    "format", "version", "baseline_job_id", "person_id", "baseline_bodyrig_revision",
    "candidate_contract_sha256", "pbr_candidate", "throughput_candidate", "ab_baseline_retention",
    "comparison_only", "human_visual_authority_required", "physical_acceptance_authority",
    "promotion_authority", "production_activation"
)
if (
    [string]$plan.format -ne "bodyrig-dual-candidate-ab-baseline-plan" -or
    [int]$plan.version -ne 1 -or
    [string]$plan.baseline_job_id -ne $BaselineJobId -or
    [string]$plan.person_id -notmatch '^person-[0-9a-f]{32}$' -or
    [string]$plan.baseline_bodyrig_revision -notmatch '^[0-9a-f]{40}$' -or
    [string]$plan.candidate_contract_sha256 -notmatch '^[0-9a-f]{64}$' -or
    $plan.comparison_only -ne $true -or
    $plan.human_visual_authority_required -ne $true -or
    $plan.physical_acceptance_authority -ne $false -or
    $plan.promotion_authority -ne $false -or
    $plan.production_activation -ne $false
) {
    throw "Shared A/B baseline plan has invalid identity or authority semantics."
}
Require-ExactFields -Value $plan.pbr_candidate -Label "PBR candidate plan" -Expected @("ref", "revision", "retained_reconstruction_reuse")
Require-ExactFields -Value $plan.throughput_candidate -Label "throughput candidate plan" -Expected @("ref", "revision", "separate_candidate_body_build_required")
Require-ExactFields -Value $plan.ab_baseline_retention -Label "A/B retention plan" -Expected @("format", "version", "retain_private_workspace", "expected_bodyrig_revision", "job_id")

$mainRevision = ([string]$plan.baseline_bodyrig_revision).ToLowerInvariant()
$pbrRef = [string]$plan.pbr_candidate.ref
$pbrRevision = ([string]$plan.pbr_candidate.revision).ToLowerInvariant()
$throughputRef = [string]$plan.throughput_candidate.ref
$throughputRevision = ([string]$plan.throughput_candidate.revision).ToLowerInvariant()
$personId = [string]$plan.person_id
if (
    [string]::IsNullOrWhiteSpace($pbrRef) -or
    $pbrRevision -notmatch '^[0-9a-f]{40}$' -or
    $plan.pbr_candidate.retained_reconstruction_reuse -ne $true -or
    [string]::IsNullOrWhiteSpace($throughputRef) -or
    $throughputRevision -notmatch '^[0-9a-f]{40}$' -or
    $plan.throughput_candidate.separate_candidate_body_build_required -ne $true -or
    [string]$plan.ab_baseline_retention.format -ne "bodyrig-ab-baseline-retention" -or
    [int]$plan.ab_baseline_retention.version -ne 1 -or
    $plan.ab_baseline_retention.retain_private_workspace -ne $true -or
    ([string]$plan.ab_baseline_retention.expected_bodyrig_revision).ToLowerInvariant() -ne $mainRevision -or
    [string]$plan.ab_baseline_retention.job_id -ne $BaselineJobId
) {
    throw "Shared A/B baseline plan does not bind the canonical retained baseline and candidate identities."
}

$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Start the throughput candidate transition from branch main."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Current main checkout must be exact and clean before switching to the throughput candidate."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim().ToLowerInvariant() -ne $mainRevision) {
    throw "Current main checkout does not match the baseline plan revision $mainRevision."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $BodyRigPython = $venvPython }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"

$pbrPrerequisite = Invoke-CheckoutPythonJson `
    -RepoRoot $repoRoot `
    -Python $BodyRigPython `
    -Module "bodyrig.pbr_plan_bound_human_review_authority" `
    -ExpectedModulePath "bodyrig\pbr_plan_bound_human_review_authority.py" `
    -Label "plan-bound PBR human-review prerequisite" `
    -Arguments @(
        "--baseline-job-id", $BaselineJobId,
        "--run-dir", $PbrRunDir,
        "--shared-plan", $planPath,
        "--repo-root", $repoRoot
    )
if (
    [string]$pbrPrerequisite.format -ne "bodyrig-pbr-human-review-prerequisite" -or
    [int]$pbrPrerequisite.version -ne 1 -or
    [string]$pbrPrerequisite.baseline_job_id -ne $BaselineJobId -or
    [string]$pbrPrerequisite.person_id -ne $personId -or
    ([string]$pbrPrerequisite.baseline_revision).ToLowerInvariant() -ne $mainRevision -or
    [string]$pbrPrerequisite.pbr_candidate_ref -ne $pbrRef -or
    ([string]$pbrPrerequisite.pbr_candidate_revision).ToLowerInvariant() -ne $pbrRevision -or
    [string]$pbrPrerequisite.throughput_candidate_ref -ne $throughputRef -or
    ([string]$pbrPrerequisite.throughput_candidate_revision).ToLowerInvariant() -ne $throughputRevision -or
    ([string]$pbrPrerequisite.baseline_plan_sha256).ToLowerInvariant() -ne $planSha256 -or
    ([string]$pbrPrerequisite.candidate_contract_sha256).ToLowerInvariant() -ne ([string]$plan.candidate_contract_sha256).ToLowerInvariant() -or
    [string]$pbrPrerequisite.pbr_human_review_authority_sha256 -notmatch '^[0-9a-f]{64}$' -or
    [string]$pbrPrerequisite.pbr_human_review_sha256 -notmatch '^[0-9a-f]{64}$' -or
    $pbrPrerequisite.human_visual_authority_recorded -ne $true -or
    $pbrPrerequisite.comparison_only -ne $true -or
    $pbrPrerequisite.physical_acceptance_authority -ne $false -or
    $pbrPrerequisite.promotion_authority -ne $false -or
    $pbrPrerequisite.production_activation -ne $false
) {
    throw "Plan-bound PBR human review is not authoritative for this throughput transition."
}
$pbrRunDirBound = [string]$pbrPrerequisite.pbr_run_dir
$pbrAuthoritySha = ([string]$pbrPrerequisite.pbr_human_review_authority_sha256).ToLowerInvariant()
$pbrReviewSha = ([string]$pbrPrerequisite.pbr_human_review_sha256).ToLowerInvariant()
$pbrDecision = [string]$pbrPrerequisite.decision

$candidateAuthority = Invoke-CheckoutPythonJson `
    -RepoRoot $repoRoot `
    -Python $BodyRigPython `
    -Module "bodyrig.ab_baseline_candidates" `
    -ExpectedModulePath "bodyrig\ab_baseline_candidates.py" `
    -Label "dual-candidate A/B authority validation" `
    -Arguments @(
        "--repo-root", $repoRoot,
        "--expected-main-revision", $mainRevision,
        "--expected-pbr-revision", $pbrRevision,
        "--expected-throughput-revision", $throughputRevision
    )
if (
    [string]$candidateAuthority.format -ne "bodyrig-ab-baseline-candidate-authority" -or
    [int]$candidateAuthority.version -ne 1 -or
    [string]$candidateAuthority.main_revision -ne $mainRevision -or
    [string]$candidateAuthority.contract_sha256 -ne ([string]$plan.candidate_contract_sha256).ToLowerInvariant() -or
    [string]$candidateAuthority.candidates.pbr_v2.ref -ne $pbrRef -or
    [string]$candidateAuthority.candidates.pbr_v2.revision -ne $pbrRevision -or
    [string]$candidateAuthority.candidates.recovery_throughput_v3.ref -ne $throughputRef -or
    [string]$candidateAuthority.candidates.recovery_throughput_v3.revision -ne $throughputRevision -or
    $candidateAuthority.comparison_only -ne $true -or
    $candidateAuthority.human_visual_authority_required -ne $true -or
    $candidateAuthority.physical_acceptance_authority -ne $false -or
    $candidateAuthority.promotion_authority -ne $false -or
    $candidateAuthority.production_activation -ne $false
) {
    throw "Live candidate authority does not match the shared baseline plan."
}

$baselineSource = Invoke-CheckoutPythonJson `
    -RepoRoot $repoRoot `
    -Python $BodyRigPython `
    -Module "bodyrig.pbr_ab_body_job_source" `
    -ExpectedModulePath "bodyrig\pbr_ab_body_job_source.py" `
    -Label "retained baseline body-job validation" `
    -Arguments @("--job-id", $BaselineJobId, "--repo-root", $repoRoot, "--expected-revision", $mainRevision)
if (
    [string]$baselineSource.format -ne "bodyrig-pbr-ab-body-job-source" -or
    [int]$baselineSource.version -ne 1 -or
    [string]$baselineSource.body_job_id -ne $BaselineJobId -or
    [string]$baselineSource.person_id -ne $personId -or
    [string]$baselineSource.bodyrig_revision -ne $mainRevision -or
    $baselineSource.safe_source_lineage_passed -ne $true -or
    $baselineSource.comparison_only -ne $true -or
    $baselineSource.human_visual_authority_required -ne $true -or
    $baselineSource.physical_acceptance_authority -ne $false -or
    $baselineSource.production_activation -ne $false
) {
    throw "Succeeded retained baseline authority does not match the shared A/B plan."
}

Write-Host "Shared baseline and plan-bound PBR human review are exact. Switching BodyRig to throughput candidate $throughputRevision..."
$updateScript = Need-File -Path (Join-Path $repoRoot "update-windows.ps1") -Label "BodyRig updater"
& $updateScript -Branch $throughputRef -NoBrowser -SkipPlan

$afterHeadRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $afterHeadRaw.Count -ne 1 -or ([string]$afterHeadRaw[0]).Trim().ToLowerInvariant() -ne $throughputRevision) {
    throw "Candidate checkout after update does not match plan revision $throughputRevision. No candidate job was started."
}
$afterDirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $afterDirty.Count -gt 0) {
    throw "Candidate checkout is not clean after update. No candidate job was started."
}
try { $serviceAuthority = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/operator-authority" -TimeoutSec 3 }
catch { throw "Candidate BodyRig service does not expose operator authority. No candidate job was started." }
if ($serviceAuthority.ok -ne $true -or ([string]$serviceAuthority.bodyrig_revision).ToLowerInvariant() -ne $throughputRevision) {
    throw "Candidate BodyRig service revision does not match the plan. No candidate job was started."
}

$startScript = Need-File -Path (Join-Path $repoRoot "start-revision-bound-body-build.ps1") -Label "revision-bound body-build launcher"
$startedRaw = @(& $startScript -PersonId $personId -BaseUri $BaseUri)
if ($startedRaw.Count -ne 1) {
    throw "Revision-bound throughput candidate launcher did not return exactly one machine-readable job result."
}
try { $started = ([string]$startedRaw[0]) | ConvertFrom-Json }
catch { throw "Revision-bound throughput candidate launcher returned unreadable JSON." }
$candidateJobId = [string]$started.job_id
if (
    $candidateJobId -notmatch '^job-[0-9a-f]{32}$' -or
    [string]$started.person_id -ne $personId -or
    ([string]$started.bodyrig_revision).ToLowerInvariant() -ne $throughputRevision -or
    $null -ne $started.ab_baseline_retention
) {
    if ($candidateJobId -match '^job-[0-9a-f]{32}$') {
        $cancelState = Try-CancelCandidateJob -JobId $candidateJobId -UriBase $BaseUri
        throw "Candidate enqueue did not preserve exact non-retained plan authority; $cancelState."
    }
    throw "Candidate enqueue did not preserve exact non-retained plan authority."
}

try {
    $refspecMain = "+refs/heads/main:refs/remotes/origin/main"
    $refspecCandidate = "+refs/heads/${throughputRef}:refs/remotes/origin/${throughputRef}"
    $fetchRaw = @(& git -C $repoRoot fetch --no-tags origin $refspecMain $refspecCandidate 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "post-enqueue authority fetch failed: $($fetchRaw -join ' ')" }
    $originMain = (& git -C $repoRoot rev-parse refs/remotes/origin/main).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $originMain -ne $mainRevision) { throw "origin/main moved after baseline plan creation" }
    $originCandidate = (& git -C $repoRoot rev-parse "refs/remotes/origin/$throughputRef").Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $originCandidate -ne $throughputRevision) { throw "throughput candidate ref moved after baseline plan creation" }
    $currentHead = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $currentHead -ne $throughputRevision) { throw "candidate checkout moved after enqueue" }
    $currentDirty = @(& git -C $repoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $currentDirty.Count -gt 0) { throw "candidate checkout became dirty after enqueue" }
    $servicePost = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/operator-authority" -TimeoutSec 3
    if ($servicePost.ok -ne $true -or ([string]$servicePost.bodyrig_revision).ToLowerInvariant() -ne $throughputRevision) {
        throw "candidate service revision drifted after enqueue"
    }
    $pbrAfterEnqueue = Invoke-CheckoutPythonJson `
        -RepoRoot $repoRoot `
        -Python $BodyRigPython `
        -Module "bodyrig.pbr_plan_bound_human_review_authority" `
        -ExpectedModulePath "bodyrig\pbr_plan_bound_human_review_authority.py" `
        -Label "post-enqueue PBR human-review prerequisite replay" `
        -Arguments @(
            "--baseline-job-id", $BaselineJobId,
            "--run-dir", $pbrRunDirBound,
            "--shared-plan", $planPath,
            "--repo-root", $repoRoot
        )
    if (
        ([string]$pbrAfterEnqueue.pbr_human_review_authority_sha256).ToLowerInvariant() -ne $pbrAuthoritySha -or
        ([string]$pbrAfterEnqueue.pbr_human_review_sha256).ToLowerInvariant() -ne $pbrReviewSha -or
        [string]$pbrAfterEnqueue.pbr_run_dir -ne $pbrRunDirBound
    ) { throw "plan-bound PBR human-review prerequisite changed after candidate enqueue" }
}
catch {
    $cancelState = Try-CancelCandidateJob -JobId $candidateJobId -UriBase $BaseUri
    throw "Throughput candidate authority drifted after enqueue: $($_.Exception.Message). $cancelState. Job $candidateJobId is NOT A/B candidate-run authority."
}

$receiptDir = Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans"
$receiptPath = Join-Path $receiptDir "$BaselineJobId-throughput-$candidateJobId.json"
$receipt = [ordered]@{
    format = "bodyrig-throughput-candidate-run-plan"
    version = 1
    baseline_plan_sha256 = $planSha256
    candidate_contract_sha256 = ([string]$plan.candidate_contract_sha256).ToLowerInvariant()
    baseline_job_id = $BaselineJobId
    baseline_job_json_sha256 = [string]$baselineSource.job_json_sha256
    baseline_bodyrig_revision = $mainRevision
    person_id = $personId
    pbr_run_dir = $pbrRunDirBound
    pbr_human_review_authority_sha256 = $pbrAuthoritySha
    pbr_human_review_sha256 = $pbrReviewSha
    pbr_human_review_decision = $pbrDecision
    throughput_candidate_ref = $throughputRef
    throughput_candidate_revision = $throughputRevision
    candidate_job_id = $candidateJobId
    candidate_workspace_retained = $false
    comparison_only = $true
    human_visual_authority_required = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}
try { Write-CreateOnlyJson -Path $receiptPath -Value $receipt }
catch {
    $cancelState = Try-CancelCandidateJob -JobId $candidateJobId -UriBase $BaseUri
    throw "Could not publish create-only throughput candidate run plan: $($_.Exception.Message). $cancelState. Job $candidateJobId is NOT A/B candidate-run authority."
}

Write-Host "BodyRig throughput A/B candidate: STARTED"
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "Baseline revision:  $mainRevision"
Write-Host "PBR review run:     $pbrRunDirBound"
Write-Host "PBR review SHA:     $pbrAuthoritySha"
Write-Host "Candidate revision: $throughputRevision"
Write-Host "Person:             $personId"
Write-Host "Candidate job:      $candidateJobId"
Write-Host "Candidate plan:     $receiptPath"
Write-Host "Monitor:            .\watch-body-build.ps1 -JobId '$candidateJobId'"
Write-Host "After the candidate succeeds, remain on this exact clean candidate checkout and run:"
Write-Host "  .\compare-recovery-throughput.ps1 -BaselineJobId '$BaselineJobId' -CandidateJobId '$candidateJobId' -BaselineBodyRigRevision '$mainRevision' -Out '<create-only-audit.json>'"
Write-Host "Then build the immutable review bundle and record the explicit human review."
Write-Host "Authority: comparison-only; no physical acceptance, promotion or production activation."

$receipt | ConvertTo-Json -Depth 20 -Compress
