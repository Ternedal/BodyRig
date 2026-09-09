param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$CandidateJobId,

    [ValidateRange(1, 300)]
    [int]$IntervalSeconds = 5,

    [switch]$Once,
    [switch]$NoClear
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40 }
    catch { throw "$Label is unreadable JSON: $Path" }
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
    if (@(Compare-Object -ReferenceObject $wanted -DifferenceObject $actual).Count -gt 0) {
        throw "$Label fields do not match the canonical contract."
    }
}

function File-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-BodyRigDataRoot {
    $configured = [string][Environment]::GetEnvironmentVariable("BODYRIG_DATA_DIR")
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        return [IO.Path]::GetFullPath($configured)
    }
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "BODYRIG_DATA_DIR or LOCALAPPDATA is required for throughput candidate monitoring."
    }
    return Join-Path $env:LOCALAPPDATA "BodyRig"
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required for plan-bound throughput continuation routing."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$watcher = Need-File -Path (Join-Path $repoRoot "watch-body-build.ps1") -Label "generic body-build watcher"
$watchParams = @{
    JobId = $CandidateJobId
    IntervalSeconds = $IntervalSeconds
}
if ($Once) { $watchParams.Once = $true }
if ($NoClear) { $watchParams.NoClear = $true }

& $watcher @watchParams

$dataRoot = Get-BodyRigDataRoot
$jobPath = Need-File -Path (Join-Path (Join-Path (Join-Path $dataRoot "ui-jobs") $CandidateJobId) "job.json") -Label "throughput candidate job"
$job = Read-JsonFile -Path $jobPath -Label "throughput candidate job"
$status = [string]$job.status
$terminal = @("succeeded","failed","canceled","interrupted") -contains $status
if (-not $terminal) {
    Write-Host ""
    Write-Host "=== THROUGHPUT CANDIDATE CONTINUATION PENDING ==="
    Write-Host "Candidate job status is '$status'. Continuation routing is emitted only after a terminal state."
    exit 0
}

$planRoot = Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans"
$runPlanPath = Join-Path $planRoot "$BaselineJobId-throughput-$CandidateJobId.json"
$gatePath = Join-Path $planRoot "$BaselineJobId-throughput-$CandidateJobId-pbr-gate.json"

function Write-Blocked {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host ""
    Write-Host "=== THROUGHPUT CANDIDATE CONTINUATION BLOCKED ==="
    Write-Host $Message
    Write-Host "Candidate plan: $runPlanPath"
    Write-Host "PBR gate:       $gatePath"
}

if (-not (Test-Path -LiteralPath $runPlanPath -PathType Leaf)) {
    Write-Blocked -Message "The exact plan-bound throughput candidate run plan is missing; no continuation is emitted."
    exit 0
}
if (-not (Test-Path -LiteralPath $gatePath -PathType Leaf)) {
    Write-Blocked -Message "The exact PBR-to-throughput sequencing gate receipt is missing; no continuation is emitted."
    exit 0
}

try {
    $runPlan = Read-JsonFile -Path $runPlanPath -Label "throughput candidate run plan"
    Require-ExactFields -Value $runPlan -Label "throughput candidate run plan" -Expected @(
        "format","version","baseline_plan_sha256","candidate_contract_sha256","baseline_job_id",
        "baseline_job_json_sha256","baseline_bodyrig_revision","person_id","throughput_candidate_ref",
        "throughput_candidate_revision","candidate_job_id","candidate_workspace_retained","comparison_only",
        "human_visual_authority_required","physical_acceptance_authority","promotion_authority","production_activation"
    )

    $sourceAuthority = $job.source_enqueue_authority
    if (
        [string]$job.format -ne "bodyrig-ui-job" -or
        [int]$job.version -ne 1 -or
        [string]$job.kind -ne "body-build" -or
        [string]$job.job_id -ne $CandidateJobId -or
        [string]$runPlan.format -ne "bodyrig-throughput-candidate-run-plan" -or
        [int]$runPlan.version -ne 1 -or
        [string]$runPlan.baseline_job_id -ne $BaselineJobId -or
        [string]$runPlan.candidate_job_id -ne $CandidateJobId -or
        [string]$runPlan.person_id -notmatch '^person-[0-9a-f]{32}$' -or
        [string]$runPlan.person_id -ne [string]$job.person_id -or
        [string]$runPlan.baseline_plan_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$runPlan.candidate_contract_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$runPlan.baseline_job_json_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$runPlan.baseline_bodyrig_revision -notmatch '^[0-9a-f]{40}$' -or
        [string]::IsNullOrWhiteSpace([string]$runPlan.throughput_candidate_ref) -or
        [string]$runPlan.throughput_candidate_revision -notmatch '^[0-9a-f]{40}$' -or
        ([string]$runPlan.throughput_candidate_revision).ToLowerInvariant() -ne ([string]$job.bodyrig_revision).ToLowerInvariant() -or
        $runPlan.candidate_workspace_retained -ne $false -or
        $runPlan.comparison_only -ne $true -or
        $runPlan.human_visual_authority_required -ne $true -or
        $runPlan.physical_acceptance_authority -ne $false -or
        $runPlan.promotion_authority -ne $false -or
        $runPlan.production_activation -ne $false -or
        $null -eq $sourceAuthority -or
        [string]$sourceAuthority.format -ne "bodyrig-body-build-source-enqueue-authority" -or
        [int]$sourceAuthority.version -ne 1 -or
        [string]$sourceAuthority.job_id -ne $CandidateJobId -or
        [string]$sourceAuthority.person_id -ne [string]$runPlan.person_id -or
        [string]::IsNullOrWhiteSpace([string]$sourceAuthority.stash_performer_id) -or
        ([string]$sourceAuthority.expected_bodyrig_revision).ToLowerInvariant() -ne ([string]$runPlan.throughput_candidate_revision).ToLowerInvariant()
    ) {
        throw "candidate run plan does not structurally match this exact job/source/revision"
    }

    $gate = Read-JsonFile -Path $gatePath -Label "PBR-to-throughput sequencing gate"
    Require-ExactFields -Value $gate -Label "PBR-to-throughput sequencing gate" -Expected @(
        "format","version","baseline_job_id","candidate_job_id","person_id","stash_performer_id",
        "baseline_plan_sha256","candidate_run_plan_sha256","candidate_contract_sha256","baseline_revision",
        "pbr_candidate_ref","pbr_candidate_revision","throughput_candidate_ref","throughput_candidate_revision",
        "pbr_run_dir","pbr_human_review_authority_sha256","pbr_human_review_sha256","pbr_decision",
        "pbr_stable_evidence_fingerprint_sha256","comparison_only","human_visual_authority_recorded",
        "physical_acceptance_authority","promotion_authority","production_activation"
    )

    $runPlanSha = File-Sha256 -Path $runPlanPath
    if (
        [string]$gate.format -ne "bodyrig-throughput-pbr-human-review-gate" -or
        [int]$gate.version -ne 1 -or
        [string]$gate.baseline_job_id -ne $BaselineJobId -or
        [string]$gate.candidate_job_id -ne $CandidateJobId -or
        [string]$gate.person_id -ne [string]$runPlan.person_id -or
        [string]$gate.stash_performer_id -ne [string]$sourceAuthority.stash_performer_id -or
        ([string]$gate.baseline_plan_sha256).ToLowerInvariant() -ne ([string]$runPlan.baseline_plan_sha256).ToLowerInvariant() -or
        ([string]$gate.candidate_run_plan_sha256).ToLowerInvariant() -ne $runPlanSha -or
        ([string]$gate.candidate_contract_sha256).ToLowerInvariant() -ne ([string]$runPlan.candidate_contract_sha256).ToLowerInvariant() -or
        ([string]$gate.baseline_revision).ToLowerInvariant() -ne ([string]$runPlan.baseline_bodyrig_revision).ToLowerInvariant() -or
        [string]$gate.throughput_candidate_ref -ne [string]$runPlan.throughput_candidate_ref -or
        ([string]$gate.throughput_candidate_revision).ToLowerInvariant() -ne ([string]$runPlan.throughput_candidate_revision).ToLowerInvariant() -or
        [string]$gate.pbr_candidate_ref -eq "" -or
        [string]$gate.pbr_candidate_revision -notmatch '^[0-9a-f]{40}$' -or
        [string]$gate.pbr_human_review_authority_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$gate.pbr_human_review_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$gate.pbr_stable_evidence_fingerprint_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]::IsNullOrWhiteSpace([string]$gate.pbr_run_dir) -or
        [string]::IsNullOrWhiteSpace([string]$gate.pbr_decision) -or
        $gate.comparison_only -ne $true -or
        $gate.human_visual_authority_recorded -ne $true -or
        $gate.physical_acceptance_authority -ne $false -or
        $gate.promotion_authority -ne $false -or
        $gate.production_activation -ne $false
    ) {
        throw "PBR sequencing gate does not structurally match the exact candidate run plan/job/source"
    }
}
catch {
    Write-Blocked -Message "Plan-bound throughput routing evidence is invalid: $($_.Exception.Message). No continuation is emitted."
    exit 0
}

if ($status -ne "succeeded") {
    Write-Blocked -Message "The exact plan-bound candidate routing evidence matches, but job status is '$status'. Continuation requires the candidate job to succeed normally."
    exit 0
}

Write-Host ""
Write-Host "=== THROUGHPUT CANDIDATE CONTINUATION ==="
Write-Host "Matching create-only candidate-run plan and PBR sequencing gate found. This watcher grants no authority; the continuation wrapper revalidates full receipt, source, checkout, machine-evidence and PBR lineage before publication."
Write-Host "Candidate plan: $runPlanPath"
Write-Host "PBR gate:       $gatePath"
Write-Host "Next command (downstream revalidates full authority):"
Write-Host "  .\continue-throughput-review-from-ab-plan.ps1 -BaselineJobId '$BaselineJobId' -CandidateJobId '$CandidateJobId'"
Write-Host "Authority: advisory routing only; no physical acceptance, promotion or production activation."
exit 0
