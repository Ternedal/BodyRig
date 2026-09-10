param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$CandidateJobId,

    [Parameter(Mandatory = $true)]
    [string]$PbrRunDir,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')]
    [string]$BaseUri = 'http://127.0.0.1:8775',

    [string]$BodyRigPython = ''
)

$ErrorActionPreference = 'Stop'
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

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite existing rescue/gate authority: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ('.' + [IO.Path]::GetFileName($Path) + '.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp -Encoding UTF8
        [IO.File]::Move($temp,$Path)
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Invoke-PbrGateProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$JobId,
        [Parameter(Mandatory = $true)][string]$RunDir
    )
    $oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH','Process')
    $oldNoBytecode = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE','Process')
    try {
        $bound = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $Root } else { "$Root$([IO.Path]::PathSeparator)$oldPythonPath" }
        [Environment]::SetEnvironmentVariable('PYTHONPATH',$bound,'Process')
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE','1','Process')
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.pbr_human_review_gate as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound PBR human-review gate module." }
        $expected = [IO.Path]::GetFullPath((Join-Path $Root 'bodyrig\pbr_human_review_gate.py'))
        $actual = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actual,$expected,[StringComparison]::OrdinalIgnoreCase)) { throw "PBR gate module imported from wrong checkout: $actual" }
        $raw = @(& $Python -m bodyrig.pbr_human_review_gate --repo-root $Root --baseline-job-id $JobId --pbr-run-dir $RunDir 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "PBR human-review gate validation failed: $($raw -join ' ')" }
        try { $value = ([string]$raw[0]) | ConvertFrom-Json -Depth 30 }
        catch { throw "PBR human-review gate returned unreadable JSON." }
        if ([string]$value.format -ne 'bodyrig-pbr-human-review-gate-context' -or [int]$value.version -ne 1) { throw "PBR human-review gate returned wrong format/version." }
        if ($value.comparison_only -ne $true -or $value.human_visual_authority_recorded -ne $true -or $value.physical_acceptance_authority -ne $false -or $value.promotion_authority -ne $false -or $value.production_activation -ne $false) {
            throw 'PBR human-review gate crossed the comparison-only authority boundary.'
        }
        return $value
    } finally {
        if ($null -eq $oldPythonPath) { [Environment]::SetEnvironmentVariable('PYTHONPATH',$null,'Process') } else { [Environment]::SetEnvironmentVariable('PYTHONPATH',$oldPythonPath,'Process') }
        if ($null -eq $oldNoBytecode) { [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE',$null,'Process') } else { [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE',$oldNoBytecode,'Process') }
    }
}

function Invoke-BaselineReceiptProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$JobId,
        [Parameter(Mandatory = $true)]$Gate
    )
    $oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH','Process')
    $oldNoBytecode = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE','Process')
    try {
        $bound = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $Root } else { "$Root$([IO.Path]::PathSeparator)$oldPythonPath" }
        [Environment]::SetEnvironmentVariable('PYTHONPATH',$bound,'Process')
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE','1','Process')
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.body_job_receipt_authority as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound baseline receipt module." }
        $expected = [IO.Path]::GetFullPath((Join-Path $Root 'bodyrig\body_job_receipt_authority.py'))
        $actual = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actual,$expected,[StringComparison]::OrdinalIgnoreCase)) { throw "Baseline receipt module imported from wrong checkout: $actual" }
        $raw = @(& $Python -m bodyrig.body_job_receipt_authority --job-id $JobId --expected-revision ([string]$Gate.baseline_revision) --expected-person-id ([string]$Gate.person_id) 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "Baseline body-job receipt validation failed: $($raw -join ' ')" }
        try { return (([string]$raw[0]) | ConvertFrom-Json -Depth 30) }
        catch { throw "Baseline body-job receipt validator returned unreadable JSON." }
    } finally {
        if ($null -eq $oldPythonPath) { [Environment]::SetEnvironmentVariable('PYTHONPATH',$null,'Process') } else { [Environment]::SetEnvironmentVariable('PYTHONPATH',$oldPythonPath,'Process') }
        if ($null -eq $oldNoBytecode) { [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE',$null,'Process') } else { [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE',$oldNoBytecode,'Process') }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw 'BodyRig throughput adoption rescue is Windows-only.' }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ (pwsh) is required.' }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$PbrRunDir = Need-Directory -Path $PbrRunDir -Label 'PBR run directory'
$planPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId.json") -Label 'shared A/B baseline plan'
$plan = Read-Json -Path $planPath -Label 'shared A/B baseline plan'
if ([string]$plan.format -ne 'bodyrig-dual-candidate-ab-baseline-plan' -or [int]$plan.version -ne 1 -or [string]$plan.baseline_job_id -ne $BaselineJobId) { throw 'Shared A/B baseline plan identity/format mismatch.' }
if ($plan.comparison_only -ne $true -or $plan.human_visual_authority_required -ne $true -or $plan.physical_acceptance_authority -ne $false -or $plan.promotion_authority -ne $false -or $plan.production_activation -ne $false) { throw 'Shared A/B plan crossed comparison-only authority.' }
$baselineRevision = Need-Revision -Value ([string]$plan.baseline_bodyrig_revision) -Label 'baseline revision'
$throughputRef = [string]$plan.throughput_candidate.ref
$throughputRevision = Need-Revision -Value ([string]$plan.throughput_candidate.revision) -Label 'throughput candidate revision'
$personId = [string]$plan.person_id
if ($personId -notmatch '^person-[0-9a-f]{32}$' -or [string]::IsNullOrWhiteSpace($throughputRef)) { throw 'Shared plan lacks canonical Person/throughput ref.' }

$branchRaw = @(& git -C $RepoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne $throughputRef) { throw "Rescue requires checkout attached to $throughputRef." }
$headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or (Need-Revision -Value ([string]$headRaw[0]) -Label 'current HEAD') -ne $throughputRevision) { throw 'Current checkout is not the exact throughput candidate revision.' }
$dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw 'Throughput adoption rescue requires an exact clean candidate checkout.' }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $BodyRigPython = $venvPython }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw 'BodyRig Python not found.' }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label 'BodyRig Python'

$gate = Invoke-PbrGateProbe -Root $RepoRoot -Python $BodyRigPython -JobId $BaselineJobId -RunDir $PbrRunDir
if ([string]$gate.baseline_job_id -ne $BaselineJobId -or [string]$gate.person_id -ne $personId -or [string]$gate.throughput_candidate_ref -ne $throughputRef -or (Need-Revision -Value ([string]$gate.throughput_candidate_revision) -Label 'PBR gate throughput revision') -ne $throughputRevision) { throw 'PBR human-review gate does not match shared throughput plan.' }
$baselineReceipt = Invoke-BaselineReceiptProbe -Root $RepoRoot -Python $BodyRigPython -JobId $BaselineJobId -Gate $gate
if ([string]$baselineReceipt.format -ne 'bodyrig-succeeded-body-job-receipt-authority' -or [int]$baselineReceipt.version -ne 1 -or [string]$baselineReceipt.body_job_id -ne $BaselineJobId -or [string]$baselineReceipt.person_id -ne $personId -or [string]$baselineReceipt.stash_performer_id -ne [string]$gate.stash_performer_id -or [string]$baselineReceipt.bodyrig_revision -ne [string]$gate.baseline_revision) { throw 'Baseline receipt no longer matches PBR-reviewed source identity.' }

$runPlanPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$CandidateJobId.json") -Label 'existing throughput candidate run plan'
$runPlan = Read-Json -Path $runPlanPath -Label 'existing throughput candidate run plan'
$planSha = File-Sha256 -Path $planPath
if (
    [string]$runPlan.format -ne 'bodyrig-throughput-candidate-run-plan' -or [int]$runPlan.version -ne 1 -or
    [string]$runPlan.baseline_plan_sha256 -ne $planSha -or [string]$runPlan.baseline_job_id -ne $BaselineJobId -or
    [string]$runPlan.person_id -ne $personId -or [string]$runPlan.throughput_candidate_ref -ne $throughputRef -or
    (Need-Revision -Value ([string]$runPlan.throughput_candidate_revision) -Label 'run-plan throughput revision') -ne $throughputRevision -or
    [string]$runPlan.candidate_job_id -ne $CandidateJobId -or $runPlan.candidate_workspace_retained -ne $false -or
    $runPlan.comparison_only -ne $true -or $runPlan.human_visual_authority_required -ne $true -or
    $runPlan.physical_acceptance_authority -ne $false -or $runPlan.promotion_authority -ne $false -or $runPlan.production_activation -ne $false
) { throw 'Existing candidate run plan does not match the exact shared-plan authority boundary.' }
if ([string]$runPlan.baseline_job_json_sha256 -ne [string]$baselineReceipt.job_json_sha256) { throw 'Candidate run plan baseline receipt differs from current succeeded baseline receipt.' }
$runPlanSha = File-Sha256 -Path $runPlanPath

try { $serviceAuthority = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/operator-authority" -TimeoutSec 3 }
catch { throw 'Candidate BodyRig service operator authority is unavailable.' }
if ($serviceAuthority.ok -ne $true -or (Need-Revision -Value ([string]$serviceAuthority.bodyrig_revision) -Label 'service revision') -ne $throughputRevision) { throw 'Running BodyRig service is not bound to the throughput candidate revision.' }

try { $candidateJob = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/jobs/$CandidateJobId" -TimeoutSec 10 }
catch { throw "Existing throughput candidate job cannot be read from BodyRig service: $CandidateJobId" }
$sourceAuthority = $candidateJob.source_enqueue_authority
if (
    [string]$candidateJob.job_id -ne $CandidateJobId -or [string]$candidateJob.kind -ne 'body-build' -or
    [string]$candidateJob.person_id -ne $personId -or (Need-Revision -Value ([string]$candidateJob.bodyrig_revision) -Label 'candidate job revision') -ne $throughputRevision -or
    $null -eq $sourceAuthority -or [string]$sourceAuthority.format -ne 'bodyrig-body-build-source-enqueue-authority' -or [int]$sourceAuthority.version -ne 1 -or
    [string]$sourceAuthority.job_id -ne $CandidateJobId -or [string]$sourceAuthority.person_id -ne $personId -or
    [string]$sourceAuthority.stash_performer_id -ne [string]$gate.stash_performer_id -or
    (Need-Revision -Value ([string]$sourceAuthority.expected_bodyrig_revision) -Label 'source enqueue revision') -ne $throughputRevision
) { throw 'Existing candidate job source enqueue authority differs from the PBR-reviewed source identity.' }

# Re-run the PBR gate after all candidate/run-plan reads so the adoption receipt is bound to stable reviewed evidence.
$gateAfter = Invoke-PbrGateProbe -Root $RepoRoot -Python $BodyRigPython -JobId $BaselineJobId -RunDir $PbrRunDir
foreach ($field in @('baseline_job_id','person_id','stash_performer_id','baseline_plan_sha256','candidate_contract_sha256','baseline_revision','pbr_candidate_ref','pbr_candidate_revision','throughput_candidate_ref','throughput_candidate_revision','pbr_run_dir','pbr_human_review_authority_sha256','pbr_human_review_sha256','pbr_decision','stable_evidence_fingerprint_sha256')) {
    if ([string]$gate.$field -ne [string]$gateAfter.$field) { throw "PBR human-review authority changed during adoption rescue: $field" }
}

$gateReceiptPath = Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$CandidateJobId-pbr-gate.json"
$gateReceipt = [ordered]@{
    format = 'bodyrig-throughput-pbr-human-review-gate'
    version = 1
    baseline_job_id = $BaselineJobId
    candidate_job_id = $CandidateJobId
    person_id = [string]$gateAfter.person_id
    stash_performer_id = [string]$gateAfter.stash_performer_id
    baseline_plan_sha256 = [string]$gateAfter.baseline_plan_sha256
    candidate_run_plan_sha256 = $runPlanSha
    candidate_contract_sha256 = [string]$gateAfter.candidate_contract_sha256
    baseline_revision = [string]$gateAfter.baseline_revision
    pbr_candidate_ref = [string]$gateAfter.pbr_candidate_ref
    pbr_candidate_revision = [string]$gateAfter.pbr_candidate_revision
    throughput_candidate_ref = [string]$gateAfter.throughput_candidate_ref
    throughput_candidate_revision = [string]$gateAfter.throughput_candidate_revision
    pbr_run_dir = [string]$gateAfter.pbr_run_dir
    pbr_human_review_authority_sha256 = [string]$gateAfter.pbr_human_review_authority_sha256
    pbr_human_review_sha256 = [string]$gateAfter.pbr_human_review_sha256
    pbr_decision = [string]$gateAfter.pbr_decision
    pbr_stable_evidence_fingerprint_sha256 = [string]$gateAfter.stable_evidence_fingerprint_sha256
    comparison_only = $true
    human_visual_authority_recorded = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}

if (Test-Path -LiteralPath $gateReceiptPath -PathType Leaf) {
    $existing = Read-Json -Path $gateReceiptPath -Label 'existing PBR-to-throughput gate receipt'
    foreach ($field in @('format','version','baseline_job_id','candidate_job_id','person_id','stash_performer_id','baseline_plan_sha256','candidate_run_plan_sha256','candidate_contract_sha256','baseline_revision','pbr_candidate_ref','pbr_candidate_revision','throughput_candidate_ref','throughput_candidate_revision','pbr_run_dir','pbr_human_review_authority_sha256','pbr_human_review_sha256','pbr_decision','pbr_stable_evidence_fingerprint_sha256','comparison_only','human_visual_authority_recorded','physical_acceptance_authority','promotion_authority','production_activation')) {
        if ([string]$existing.$field -ne [string]$gateReceipt.$field) { throw "Existing gate receipt differs from exact adoption authority: $field" }
    }
} else {
    Write-CreateOnlyJson -Path $gateReceiptPath -Value $gateReceipt
}
$gateReceiptSha = File-Sha256 -Path $gateReceiptPath

$rescueAuthorityPath = Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$CandidateJobId-wrapper-output-rescue.json"
$rescueAuthority = [ordered]@{
    format = 'bodyrig-throughput-wrapper-output-adoption-rescue'
    version = 1
    reason = 'outer-wrapper-required-single-success-stream-item-after-internal-candidate-start'
    baseline_job_id = $BaselineJobId
    candidate_job_id = $CandidateJobId
    throughput_candidate_revision = $throughputRevision
    candidate_run_plan_sha256 = $runPlanSha
    pbr_to_throughput_gate_sha256 = $gateReceiptSha
    candidate_job_status_at_adoption = [string]$candidateJob.status
    comparison_only = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}
if (-not (Test-Path -LiteralPath $rescueAuthorityPath -PathType Leaf)) { Write-CreateOnlyJson -Path $rescueAuthorityPath -Value $rescueAuthority }

Write-Host 'BodyRig throughput existing-job adoption: RECORDED'
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "Candidate job:      $CandidateJobId"
Write-Host "Candidate status:   $([string]$candidateJob.status)"
Write-Host "Candidate revision: $throughputRevision"
Write-Host "Gate receipt:       $gateReceiptPath"
Write-Host "Rescue authority:   $rescueAuthorityPath"
Write-Host "Monitor:            .\watch-throughput-candidate-from-ab-plan.ps1 -BaselineJobId '$BaselineJobId' -CandidateJobId '$CandidateJobId'"
Write-Host 'Authority: comparison-only; no physical acceptance, promotion or production activation.'
