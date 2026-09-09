param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$CandidateJobId,

    [string]$OutRoot = "",
    [string]$RepoRoot = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
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

function Require-AuthorityBoundary {
    param([Parameter(Mandatory = $true)]$Value,[Parameter(Mandatory = $true)][string]$Label)
    if (
        $Value.comparison_only -ne $true -or
        $Value.human_visual_authority_required -ne $true -or
        $Value.physical_acceptance_authority -ne $false -or
        $Value.promotion_authority -ne $false -or
        $Value.production_activation -ne $false
    ) {
        throw "$Label crossed the comparison-only authority boundary."
    }
}

function Invoke-ReceiptProbe {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$JobId,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$ExpectedPersonId,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $oldPythonPath = [string]$env:PYTHONPATH
    $oldNoBytecode = [string]$env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" })
        $env:PYTHONDONTWRITEBYTECODE = "1"
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.body_job_receipt_authority as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound $Label validator." }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\body_job_receipt_authority.py"))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
            throw "$Label validator imported from wrong checkout: $actualModule"
        }
        $raw = @(& $Python -m bodyrig.body_job_receipt_authority --job-id $JobId --expected-revision $ExpectedRevision --expected-person-id $ExpectedPersonId 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "$Label validation failed: $($raw -join ' ')" }
        try { $value = ([string]$raw[0]) | ConvertFrom-Json }
        catch { throw "$Label validator returned unreadable JSON." }
        if ([string]$value.format -ne "bodyrig-succeeded-body-job-receipt-authority" -or [int]$value.version -ne 1) {
            throw "$Label validator returned wrong format/version."
        }
        Require-AuthorityBoundary -Value $value -Label $Label
        return $value
    }
    finally {
        if ([string]::IsNullOrEmpty($oldPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
        if ([string]::IsNullOrEmpty($oldNoBytecode)) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode }
    }
}

function Assert-ReceiptProbeStable {
    param(
        [Parameter(Mandatory = $true)]$Before,
        [Parameter(Mandatory = $true)]$After,
        [Parameter(Mandatory = $true)][string]$Label
    )
    foreach ($field in @(
        "body_job_id",
        "person_id",
        "bodyrig_revision",
        "body_revision",
        "canonical_body_id",
        "package_sha256",
        "job_json_sha256",
        "source_binding_sha256",
        "body_review_sha256",
        "source_evidence_kind",
        "source_evidence_sha256",
        "source_files_sha256"
    )) {
        if ([string]$Before.$field -ne [string]$After.$field) {
            throw "$Label changed while generating throughput review evidence: $field"
        }
    }
}

function Invoke-PbrSequencingGateProbe {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$BaselineJobId,
        [Parameter(Mandatory = $true)][string]$CandidateJobId,
        [Parameter(Mandatory = $true)][string]$SharedPlanSha,
        [Parameter(Mandatory = $true)][string]$RunPlanSha,
        [Parameter(Mandatory = $true)][string]$ContractSha,
        [Parameter(Mandatory = $true)][string]$ExpectedPersonId,
        [Parameter(Mandatory = $true)][string]$ExpectedMainRevision,
        [Parameter(Mandatory = $true)][string]$ExpectedThroughputRef,
        [Parameter(Mandatory = $true)][string]$ExpectedThroughputRevision
    )
    $gateReceiptPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$CandidateJobId-pbr-gate.json") -Label "PBR-to-throughput sequencing gate receipt"
    $gateReceiptSha = (Get-FileHash -LiteralPath $gateReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $gateReceipt = Read-Json -Path $gateReceiptPath -Label "PBR-to-throughput sequencing gate receipt"
    if ([string]$gateReceipt.format -ne "bodyrig-throughput-pbr-human-review-gate" -or [int]$gateReceipt.version -ne 1) {
        throw "PBR-to-throughput sequencing gate receipt format/version mismatch."
    }
    if (
        $gateReceipt.comparison_only -ne $true -or
        $gateReceipt.human_visual_authority_recorded -ne $true -or
        $gateReceipt.physical_acceptance_authority -ne $false -or
        $gateReceipt.promotion_authority -ne $false -or
        $gateReceipt.production_activation -ne $false
    ) {
        throw "PBR-to-throughput sequencing gate receipt crossed the comparison-only authority boundary."
    }
    if (
        [string]$gateReceipt.baseline_job_id -ne $BaselineJobId -or
        [string]$gateReceipt.candidate_job_id -ne $CandidateJobId -or
        [string]$gateReceipt.person_id -ne $ExpectedPersonId -or
        (Need-Sha256 -Value ([string]$gateReceipt.baseline_plan_sha256) -Label "PBR gate baseline plan SHA") -ne $SharedPlanSha -or
        (Need-Sha256 -Value ([string]$gateReceipt.candidate_run_plan_sha256) -Label "PBR gate candidate run plan SHA") -ne $RunPlanSha -or
        (Need-Sha256 -Value ([string]$gateReceipt.candidate_contract_sha256) -Label "PBR gate candidate contract SHA") -ne $ContractSha -or
        (Need-Revision -Value ([string]$gateReceipt.baseline_revision) -Label "PBR gate baseline revision") -ne $ExpectedMainRevision -or
        [string]$gateReceipt.throughput_candidate_ref -ne $ExpectedThroughputRef -or
        (Need-Revision -Value ([string]$gateReceipt.throughput_candidate_revision) -Label "PBR gate throughput revision") -ne $ExpectedThroughputRevision
    ) {
        throw "PBR-to-throughput sequencing gate receipt does not exactly match the selected shared plan and candidate run."
    }
    $pbrRunDir = [string]$gateReceipt.pbr_run_dir
    if ([string]::IsNullOrWhiteSpace($pbrRunDir)) { throw "PBR-to-throughput sequencing gate receipt has no exact PBR run directory." }
    $receiptPbrAuthoritySha = Need-Sha256 -Value ([string]$gateReceipt.pbr_human_review_authority_sha256) -Label "PBR gate human-review authority SHA"
    $receiptPbrReviewSha = Need-Sha256 -Value ([string]$gateReceipt.pbr_human_review_sha256) -Label "PBR gate human-review SHA"
    $receiptFingerprintSha = Need-Sha256 -Value ([string]$gateReceipt.pbr_stable_evidence_fingerprint_sha256) -Label "PBR gate evidence fingerprint SHA"

    $oldPythonPath = [string]$env:PYTHONPATH
    $oldNoBytecode = [string]$env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" })
        $env:PYTHONDONTWRITEBYTECODE = "1"
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.pbr_human_review_gate as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound PBR human-review gate validator." }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\pbr_human_review_gate.py"))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
            throw "PBR human-review gate validator imported from wrong checkout: $actualModule"
        }
        $raw = @(& $Python -m bodyrig.pbr_human_review_gate --repo-root $RepoRoot --baseline-job-id $BaselineJobId --pbr-run-dir $pbrRunDir 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "PBR human-review gate replay failed: $($raw -join ' ')" }
        try { $live = ([string]$raw[0]) | ConvertFrom-Json -Depth 40 }
        catch { throw "PBR human-review gate replay returned unreadable JSON." }
        if ([string]$live.format -ne "bodyrig-pbr-human-review-gate-context" -or [int]$live.version -ne 1) {
            throw "PBR human-review gate replay returned wrong format/version."
        }
        if (
            $live.comparison_only -ne $true -or
            $live.human_visual_authority_recorded -ne $true -or
            $live.physical_acceptance_authority -ne $false -or
            $live.promotion_authority -ne $false -or
            $live.production_activation -ne $false
        ) {
            throw "Replayed PBR human-review authority crossed the comparison-only authority boundary."
        }
        if (
            [string]$live.baseline_job_id -ne $BaselineJobId -or
            [string]$live.person_id -ne $ExpectedPersonId -or
            [string]$live.baseline_plan_sha256 -ne $SharedPlanSha -or
            [string]$live.candidate_contract_sha256 -ne $ContractSha -or
            [string]$live.baseline_revision -ne $ExpectedMainRevision -or
            [string]$live.throughput_candidate_ref -ne $ExpectedThroughputRef -or
            [string]$live.throughput_candidate_revision -ne $ExpectedThroughputRevision -or
            [string]$live.pbr_run_dir -ne $pbrRunDir -or
            (Need-Sha256 -Value ([string]$live.pbr_human_review_authority_sha256) -Label "replayed PBR human-review authority SHA") -ne $receiptPbrAuthoritySha -or
            (Need-Sha256 -Value ([string]$live.pbr_human_review_sha256) -Label "replayed PBR human-review SHA") -ne $receiptPbrReviewSha -or
            [string]$live.pbr_decision -ne [string]$gateReceipt.pbr_decision -or
            (Need-Sha256 -Value ([string]$live.stable_evidence_fingerprint_sha256) -Label "replayed PBR evidence fingerprint SHA") -ne $receiptFingerprintSha
        ) {
            throw "PBR human-review evidence no longer matches the sequencing receipt."
        }
        return [pscustomobject]@{
            gate_receipt_sha256 = $gateReceiptSha
            pbr_run_dir = $pbrRunDir
            pbr_human_review_authority_sha256 = $receiptPbrAuthoritySha
            pbr_human_review_sha256 = $receiptPbrReviewSha
            pbr_decision = [string]$gateReceipt.pbr_decision
            pbr_stable_evidence_fingerprint_sha256 = $receiptFingerprintSha
        }
    }
    finally {
        if ([string]::IsNullOrEmpty($oldPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
        if ([string]::IsNullOrEmpty($oldNoBytecode)) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode }
    }
}

function Assert-PbrSequencingGateStable {
    param([Parameter(Mandatory = $true)]$Before,[Parameter(Mandatory = $true)]$After)
    foreach ($field in @(
        "gate_receipt_sha256",
        "pbr_run_dir",
        "pbr_human_review_authority_sha256",
        "pbr_human_review_sha256",
        "pbr_decision",
        "pbr_stable_evidence_fingerprint_sha256"
    )) {
        if ([string]$Before.$field -ne [string]$After.$field) {
            throw "PBR-to-throughput sequencing authority changed while generating throughput review evidence: $field"
        }
    }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite continuation authority: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig throughput review continuation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required for A/B plan authority."
}
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) {
    throw "RepoRoot is not a BodyRig Git checkout: $RepoRoot"
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required for revision-bound throughput review authority."
}
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $BodyRigPython = $venvPython }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"

$sharedPlanPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId.json") -Label "shared A/B baseline plan"
$runPlanPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$CandidateJobId.json") -Label "throughput candidate run plan"
$sharedPlan = Read-Json -Path $sharedPlanPath -Label "shared A/B baseline plan"
$runPlan = Read-Json -Path $runPlanPath -Label "throughput candidate run plan"
$sharedPlanSha = (Get-FileHash -LiteralPath $sharedPlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
$runPlanSha = (Get-FileHash -LiteralPath $runPlanPath -Algorithm SHA256).Hash.ToLowerInvariant()

if ([string]$sharedPlan.format -ne "bodyrig-dual-candidate-ab-baseline-plan" -or [int]$sharedPlan.version -ne 1) {
    throw "Shared A/B baseline plan format/version mismatch."
}
Require-AuthorityBoundary -Value $sharedPlan -Label "shared A/B baseline plan"
if ([string]$runPlan.format -ne "bodyrig-throughput-candidate-run-plan" -or [int]$runPlan.version -ne 1) {
    throw "Throughput candidate run plan format/version mismatch."
}
Require-AuthorityBoundary -Value $runPlan -Label "throughput candidate run plan"

$mainRevision = Need-Revision -Value ([string]$sharedPlan.baseline_bodyrig_revision) -Label "baseline plan main revision"
$personId = [string]$sharedPlan.person_id
$contractSha = Need-Sha256 -Value ([string]$sharedPlan.candidate_contract_sha256) -Label "baseline plan candidate contract SHA"
$throughputRef = [string]$sharedPlan.throughput_candidate.ref
$throughputRevision = Need-Revision -Value ([string]$sharedPlan.throughput_candidate.revision) -Label "baseline plan throughput candidate revision"
if ($personId -notmatch '^person-[0-9a-f]{32}$' -or [string]::IsNullOrWhiteSpace($throughputRef)) {
    throw "Shared A/B baseline plan has invalid Person or throughput ref identity."
}
if (
    [string]$runPlan.baseline_plan_sha256 -ne $sharedPlanSha -or
    (Need-Sha256 -Value ([string]$runPlan.candidate_contract_sha256) -Label "run plan candidate contract SHA") -ne $contractSha -or
    [string]$runPlan.baseline_job_id -ne $BaselineJobId -or
    (Need-Revision -Value ([string]$runPlan.baseline_bodyrig_revision) -Label "run plan baseline revision") -ne $mainRevision -or
    [string]$runPlan.person_id -ne $personId -or
    [string]$runPlan.throughput_candidate_ref -ne $throughputRef -or
    (Need-Revision -Value ([string]$runPlan.throughput_candidate_revision) -Label "run plan candidate revision") -ne $throughputRevision -or
    [string]$runPlan.candidate_job_id -ne $CandidateJobId -or
    $runPlan.candidate_workspace_retained -ne $false
) {
    throw "Throughput candidate run plan does not exactly match the shared baseline plan and selected jobs."
}

$contractPath = Need-File -Path (Join-Path $RepoRoot "contracts\ab-baseline-candidates-v1.json") -Label "candidate byte contract"
if ((Get-FileHash -LiteralPath $contractPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $contractSha) {
    throw "Candidate byte contract bytes differ from the shared baseline plan."
}

$branchRaw = @(& git -C $RepoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne $throughputRef) {
    throw "Run throughput review continuation from the exact plan-bound candidate branch $throughputRef."
}
$dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Candidate checkout must be clean for throughput review continuation."
}
$headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve candidate checkout HEAD." }
$head = Need-Revision -Value ([string]$headRaw[0]) -Label "candidate checkout HEAD"
if ($head -ne $throughputRevision) { throw "Candidate checkout HEAD does not match the run plan." }

$fetchMain = "+refs/heads/main:refs/remotes/origin/main"
$fetchCandidate = "+refs/heads/${throughputRef}:refs/remotes/origin/${throughputRef}"
$fetchRaw = @(& git -C $RepoRoot fetch --no-tags origin $fetchMain $fetchCandidate 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not refresh plan-bound remote refs: $($fetchRaw -join ' ')" }
$originMainRaw = @(& git -C $RepoRoot rev-parse refs/remotes/origin/main 2>&1)
$originCandidateRaw = @(& git -C $RepoRoot rev-parse "refs/remotes/origin/$throughputRef" 2>&1)
if ($originMainRaw.Count -ne 1 -or $originCandidateRaw.Count -ne 1) { throw "Could not resolve plan-bound remote refs." }
$originMain = Need-Revision -Value ([string]$originMainRaw[0]) -Label "origin/main"
$originCandidate = Need-Revision -Value ([string]$originCandidateRaw[0]) -Label "origin candidate"
if ($originMain -ne $mainRevision) { throw "origin/main moved after the shared A/B baseline plan was created." }
if ($originCandidate -ne $throughputRevision) { throw "Throughput candidate ref moved after candidate-run authority was created." }

$pbrSequencingGate = Invoke-PbrSequencingGateProbe -RepoRoot $RepoRoot -Python $BodyRigPython -BaselineJobId $BaselineJobId -CandidateJobId $CandidateJobId -SharedPlanSha $sharedPlanSha -RunPlanSha $runPlanSha -ContractSha $contractSha -ExpectedPersonId $personId -ExpectedMainRevision $mainRevision -ExpectedThroughputRef $throughputRef -ExpectedThroughputRevision $throughputRevision

if (-not [string]::IsNullOrWhiteSpace($env:BODYRIG_DATA_DIR)) {
    $dataRoot = [IO.Path]::GetFullPath($env:BODYRIG_DATA_DIR)
} else {
    $dataRoot = Join-Path $env:LOCALAPPDATA "BodyRig"
}
$baselineJobPath = Need-File -Path (Join-Path $dataRoot "ui-jobs\$BaselineJobId\job.json") -Label "baseline body-build job"
$candidateJobPath = Need-File -Path (Join-Path $dataRoot "ui-jobs\$CandidateJobId\job.json") -Label "candidate body-build job"
$baselineJob = Read-Json -Path $baselineJobPath -Label "baseline body-build job"
$candidateJob = Read-Json -Path $candidateJobPath -Label "candidate body-build job"
$baselineJobSha = (Get-FileHash -LiteralPath $baselineJobPath -Algorithm SHA256).Hash.ToLowerInvariant()
$candidateJobSha = (Get-FileHash -LiteralPath $candidateJobPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ((Need-Sha256 -Value ([string]$runPlan.baseline_job_json_sha256) -Label "run plan baseline job SHA") -ne $baselineJobSha) {
    throw "Baseline job JSON changed after candidate-run authority was created."
}
if (
    [string]$baselineJob.format -ne "bodyrig-ui-job" -or [int]$baselineJob.version -ne 1 -or
    [string]$baselineJob.kind -ne "body-build" -or [string]$baselineJob.status -ne "succeeded" -or
    [string]$baselineJob.job_id -ne $BaselineJobId -or [string]$baselineJob.person_id -ne $personId -or
    (Need-Revision -Value ([string]$baselineJob.bodyrig_revision) -Label "baseline job revision") -ne $mainRevision
) {
    throw "Baseline body-build job no longer matches the shared baseline plan."
}
$retention = $baselineJob.ab_baseline_retention
if (
    $null -eq $retention -or
    [string]$retention.format -ne "bodyrig-ab-baseline-retention" -or [int]$retention.version -ne 1 -or
    $retention.retain_private_workspace -ne $true -or
    (Need-Revision -Value ([string]$retention.expected_bodyrig_revision) -Label "baseline retention revision") -ne $mainRevision -or
    [string]$retention.job_id -ne $BaselineJobId
) {
    throw "Baseline body-build no longer carries exact A/B retention authority."
}
if (
    [string]$candidateJob.format -ne "bodyrig-ui-job" -or [int]$candidateJob.version -ne 1 -or
    [string]$candidateJob.kind -ne "body-build" -or [string]$candidateJob.status -ne "succeeded" -or
    [string]$candidateJob.job_id -ne $CandidateJobId -or [string]$candidateJob.person_id -ne $personId -or
    (Need-Revision -Value ([string]$candidateJob.bodyrig_revision) -Label "candidate job revision") -ne $throughputRevision
) {
    throw "Candidate body-build job is not the exact succeeded plan-bound run."
}
if ($candidateJob.PSObject.Properties.Name -contains "ab_baseline_retention" -and $null -ne $candidateJob.ab_baseline_retention) {
    throw "Candidate body-build unexpectedly carries baseline-retention authority."
}

$baselineReceipts = Invoke-ReceiptProbe -RepoRoot $RepoRoot -Python $BodyRigPython -JobId $BaselineJobId -ExpectedRevision $mainRevision -ExpectedPersonId $personId -Label "baseline body-job receipt authority"
$candidateReceipts = Invoke-ReceiptProbe -RepoRoot $RepoRoot -Python $BodyRigPython -JobId $CandidateJobId -ExpectedRevision $throughputRevision -ExpectedPersonId $personId -Label "candidate body-job receipt authority"
if ([string]$baselineReceipts.job_json_sha256 -ne $baselineJobSha) {
    throw "Baseline receipt authority does not bind the exact candidate-run baseline job JSON."
}
if ([string]$candidateReceipts.job_json_sha256 -ne $candidateJobSha) {
    throw "Candidate receipt authority does not bind the exact succeeded candidate job JSON."
}
if (
    [string]$baselineReceipts.source_evidence_kind -ne "stash-physical-source-manifest-v1" -or
    [string]$candidateReceipts.source_evidence_kind -ne "stash-physical-source-manifest-v1" -or
    [string]$baselineReceipts.source_evidence_sha256 -ne [string]$candidateReceipts.source_evidence_sha256 -or
    [string]$baselineReceipts.source_files_sha256 -ne [string]$candidateReceipts.source_files_sha256
) {
    throw "Baseline and candidate body jobs are not bound to the same exact Stash physical source manifest and success-time source-file hashes."
}
$sourceManifestSha = Need-Sha256 -Value ([string]$baselineReceipts.source_evidence_sha256) -Label "shared Stash physical source manifest SHA"
$sourceFilesSha = Need-Sha256 -Value ([string]$baselineReceipts.source_files_sha256) -Label "shared success-time source-file hash-list SHA"

if ([string]::IsNullOrWhiteSpace($OutRoot)) {
    $OutRoot = Join-Path $dataRoot "recovery-throughput-plan-bound\$BaselineJobId--$CandidateJobId"
}
$finalRoot = [IO.Path]::GetFullPath($OutRoot)
if (Test-Path -LiteralPath $finalRoot) { throw "Refusing to overwrite existing plan-bound throughput review output: $finalRoot" }
$parentRoot = Split-Path -Parent $finalRoot
if (-not (Test-Path -LiteralPath $parentRoot -PathType Container)) { New-Item -ItemType Directory -Path $parentRoot -Force | Out-Null }
$tempRoot = Join-Path $parentRoot ("." + [IO.Path]::GetFileName($finalRoot) + ".tmp-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -ErrorAction Stop | Out-Null

try {
    $machinePath = Join-Path $tempRoot "machine-audit.json"
    $bundleDir = Join-Path $tempRoot "review-bundle"
    $authorityPath = Join-Path $tempRoot "continuation-authority.json"
    $compareScript = Need-File -Path (Join-Path $RepoRoot "compare-recovery-throughput.ps1") -Label "candidate-owned recovery throughput machine audit"
    $bundleScript = Need-File -Path (Join-Path $RepoRoot "build-recovery-throughput-review-bundle.ps1") -Label "candidate-owned recovery throughput review bundle builder"
    [void](Need-File -Path (Join-Path $RepoRoot "record-recovery-throughput-human-review.ps1") -Label "candidate-owned recovery throughput human review recorder")

    & $compareScript -BaselineJobId $BaselineJobId -CandidateJobId $CandidateJobId -BaselineBodyRigRevision $mainRevision -Out $machinePath -RepoRoot $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw "Plan-bound recovery throughput machine A/B did not PASS." }
    $machine = Read-Json -Path $machinePath -Label "plan-bound machine A/B audit"
    if (
        [string]$machine.format -ne "bodyrig-recovery-throughput-sampling-audit" -or [int]$machine.version -ne 1 -or
        $machine.machine_evidence_pass -ne $true -or [string]$machine.decision -ne "eligible-for-human-ab-review" -or
        [string]$machine.baseline_job_id -ne $BaselineJobId -or [string]$machine.candidate_job_id -ne $CandidateJobId -or
        (Need-Revision -Value ([string]$machine.baseline_bodyrig_revision) -Label "machine baseline revision") -ne $mainRevision -or
        (Need-Revision -Value ([string]$machine.candidate_bodyrig_revision) -Label "machine candidate revision") -ne $throughputRevision -or
        $machine.promotion_authority -ne $false -or $machine.production_activation -ne $false
    ) {
        throw "Machine A/B audit did not preserve exact plan-bound job/revision authority."
    }

    & $bundleScript -BaselineJobId $BaselineJobId -CandidateJobId $CandidateJobId -BaselineBodyRigRevision $mainRevision -Out $bundleDir -RepoRoot $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw "Plan-bound recovery throughput review bundle could not be built." }
    $bundleReceiptPath = Need-File -Path (Join-Path $bundleDir "review-bundle.json") -Label "immutable review bundle receipt"
    $bundle = Read-Json -Path $bundleReceiptPath -Label "immutable review bundle receipt"
    if (
        [string]$bundle.format -ne "bodyrig-recovery-throughput-review-bundle" -or [int]$bundle.version -ne 1 -or
        [string]$bundle.baseline_job_id -ne $BaselineJobId -or [string]$bundle.candidate_job_id -ne $CandidateJobId -or
        (Need-Revision -Value ([string]$bundle.baseline_bodyrig_revision) -Label "bundle baseline revision") -ne $mainRevision -or
        (Need-Revision -Value ([string]$bundle.candidate_bodyrig_revision) -Label "bundle candidate revision") -ne $throughputRevision -or
        $bundle.human_visual_review_required -ne $true -or
        $bundle.promotion_authority -ne $false -or $bundle.production_activation -ne $false
    ) {
        throw "Review bundle did not preserve exact plan-bound job/revision authority."
    }

    $headAfterRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    $dirtyAfter = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headAfterRaw.Count -ne 1 -or $dirtyAfter.Count -gt 0) {
        throw "Candidate checkout changed while generating plan-bound review evidence."
    }
    $headAfter = Need-Revision -Value ([string]$headAfterRaw[0]) -Label "post-review candidate HEAD"
    if ($headAfter -ne $throughputRevision) { throw "Candidate checkout revision changed while generating review evidence." }

    $refetchRaw = @(& git -C $RepoRoot fetch --no-tags origin $fetchMain $fetchCandidate 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not recheck remote refs after review evidence generation: $($refetchRaw -join ' ')" }
    $originMainAfterRaw = @(& git -C $RepoRoot rev-parse refs/remotes/origin/main 2>&1)
    $originCandidateAfterRaw = @(& git -C $RepoRoot rev-parse "refs/remotes/origin/$throughputRef" 2>&1)
    if ($originMainAfterRaw.Count -ne 1 -or $originCandidateAfterRaw.Count -ne 1) { throw "Could not resolve post-review remote refs." }
    $originMainAfter = Need-Revision -Value ([string]$originMainAfterRaw[0]) -Label "post-review origin/main"
    $originCandidateAfter = Need-Revision -Value ([string]$originCandidateAfterRaw[0]) -Label "post-review origin candidate"
    if ($originMainAfter -ne $mainRevision -or $originCandidateAfter -ne $throughputRevision) {
        throw "A/B refs moved while generating throughput review evidence. No continuation authority will be published."
    }

    $baselineReceiptsAfter = Invoke-ReceiptProbe -RepoRoot $RepoRoot -Python $BodyRigPython -JobId $BaselineJobId -ExpectedRevision $mainRevision -ExpectedPersonId $personId -Label "post-review baseline body-job receipt authority"
    $candidateReceiptsAfter = Invoke-ReceiptProbe -RepoRoot $RepoRoot -Python $BodyRigPython -JobId $CandidateJobId -ExpectedRevision $throughputRevision -ExpectedPersonId $personId -Label "post-review candidate body-job receipt authority"
    Assert-ReceiptProbeStable -Before $baselineReceipts -After $baselineReceiptsAfter -Label "Baseline persisted body-job receipt authority"
    Assert-ReceiptProbeStable -Before $candidateReceipts -After $candidateReceiptsAfter -Label "Candidate persisted body-job receipt authority"
    if (
        [string]$baselineReceiptsAfter.source_evidence_sha256 -ne $sourceManifestSha -or
        [string]$candidateReceiptsAfter.source_evidence_sha256 -ne $sourceManifestSha -or
        [string]$baselineReceiptsAfter.source_files_sha256 -ne $sourceFilesSha -or
        [string]$candidateReceiptsAfter.source_files_sha256 -ne $sourceFilesSha
    ) {
        throw "Shared Stash physical source authority changed while generating throughput review evidence."
    }

    $pbrSequencingGateAfter = Invoke-PbrSequencingGateProbe -RepoRoot $RepoRoot -Python $BodyRigPython -BaselineJobId $BaselineJobId -CandidateJobId $CandidateJobId -SharedPlanSha $sharedPlanSha -RunPlanSha $runPlanSha -ContractSha $contractSha -ExpectedPersonId $personId -ExpectedMainRevision $mainRevision -ExpectedThroughputRef $throughputRef -ExpectedThroughputRevision $throughputRevision
    Assert-PbrSequencingGateStable -Before $pbrSequencingGate -After $pbrSequencingGateAfter

    $authority = [ordered]@{
        format = "bodyrig-throughput-plan-bound-review-continuation"
        version = 1
        baseline_plan_sha256 = $sharedPlanSha
        candidate_run_plan_sha256 = $runPlanSha
        candidate_contract_sha256 = $contractSha
        baseline_job_id = $BaselineJobId
        candidate_job_id = $CandidateJobId
        person_id = $personId
        baseline_bodyrig_revision = $mainRevision
        throughput_candidate_ref = $throughputRef
        throughput_candidate_revision = $throughputRevision
        pbr_to_throughput_sequence_verified = $true
        pbr_gate_receipt_sha256 = [string]$pbrSequencingGate.gate_receipt_sha256
        pbr_human_review_authority_sha256 = [string]$pbrSequencingGate.pbr_human_review_authority_sha256
        pbr_human_review_sha256 = [string]$pbrSequencingGate.pbr_human_review_sha256
        pbr_stable_evidence_fingerprint_sha256 = [string]$pbrSequencingGate.pbr_stable_evidence_fingerprint_sha256
        pbr_decision = [string]$pbrSequencingGate.pbr_decision
        baseline_body_revision = [string]$baselineReceipts.body_revision
        candidate_body_revision = [string]$candidateReceipts.body_revision
        baseline_canonical_body_id = [string]$baselineReceipts.canonical_body_id
        candidate_canonical_body_id = [string]$candidateReceipts.canonical_body_id
        baseline_job_json_sha256 = [string]$baselineReceipts.job_json_sha256
        candidate_job_json_sha256 = [string]$candidateReceipts.job_json_sha256
        baseline_source_binding_sha256 = [string]$baselineReceipts.source_binding_sha256
        candidate_source_binding_sha256 = [string]$candidateReceipts.source_binding_sha256
        baseline_body_review_sha256 = [string]$baselineReceipts.body_review_sha256
        candidate_body_review_sha256 = [string]$candidateReceipts.body_review_sha256
        source_evidence_kind = "stash-physical-source-manifest-v1"
        source_evidence_sha256 = $sourceManifestSha
        source_files_sha256 = $sourceFilesSha
        source_manifest_parity_verified = $true
        source_file_hashes_parity_verified = $true
        machine_audit_sha256 = (Get-FileHash -LiteralPath $machinePath -Algorithm SHA256).Hash.ToLowerInvariant()
        review_bundle_receipt_sha256 = (Get-FileHash -LiteralPath $bundleReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
        comparison_only = $true
        human_visual_authority_required = $true
        physical_acceptance_authority = $false
        promotion_authority = $false
        production_activation = $false
    }
    Write-CreateOnlyJson -Path $authorityPath -Value $authority
    Move-Item -LiteralPath $tempRoot -Destination $finalRoot
} catch {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
    throw
}

$finalBundle = Join-Path $finalRoot "review-bundle"
$finalAuthority = Join-Path $finalRoot "continuation-authority.json"
$humanOut = "$finalRoot.human-review.json"
Write-Host "BodyRig throughput A/B: READY FOR EXPLICIT HUMAN REVIEW"
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "Candidate job:      $CandidateJobId"
Write-Host "Candidate revision: $throughputRevision"
Write-Host "PBR sequencing:     VERIFIED"
Write-Host "Source manifest:    $sourceManifestSha"
Write-Host "Source file hashes: $sourceFilesSha"
Write-Host "Review bundle:      $finalBundle"
Write-Host "Open:               $(Join-Path $finalBundle 'index.html')"
Write-Host "Continuation auth:  $finalAuthority"
Write-Host "After reviewing all four canonical views, record the real human decision through the plan-bound authority wrapper:"
Write-Host "  .\record-throughput-human-review-from-ab-plan.ps1 -BaselineJobId '$BaselineJobId' -CandidateJobId '$CandidateJobId' -RunDir '$finalRoot' -IdentityShape pass|fail -FaceIdentity pass|fail -SkinTextureAlignment pass|fail -GrossAnatomy pass|fail -Note '<human note>' -ConfirmVisualReview -Out '$humanOut'"
Write-Host "Authority: comparison-only; human decision still required; no physical acceptance, promotion or production activation."
