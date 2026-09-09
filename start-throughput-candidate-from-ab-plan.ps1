param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [string]$PbrRunDir = "",

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')]
    [string]$BaseUri = "http://127.0.0.1:8775",

    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function File-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40 }
    catch { throw "$Label is unreadable JSON: $Path" }
    if ($null -eq $value) { throw "$Label is empty: $Path" }
    return $value
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite PBR-to-throughput gate receipt: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Try-CancelCandidateJob {
    param([Parameter(Mandatory = $true)][string]$JobId,[Parameter(Mandatory = $true)][string]$UriBase)
    try {
        $result = Invoke-RestMethod -Method Post -Uri "$UriBase/api/v1/jobs/$JobId/cancel" -TimeoutSec 10
        return "cancel requested ($([string]$result.status))"
    } catch {
        return "cancel request failed: $($_.Exception.Message)"
    }
}

function Invoke-PbrGateProbe {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$JobId,
        [string]$RunDir = ""
    )
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldNoBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
    try {
        $bound = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" }
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $bound, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.pbr_human_review_gate as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound PBR human-review gate validator." }
        $expected = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\pbr_human_review_gate.py"))
        $actual = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actual, $expected, [StringComparison]::OrdinalIgnoreCase)) { throw "PBR gate validator imported from wrong checkout: $actual" }
        $args = @("-m", "bodyrig.pbr_human_review_gate", "--repo-root", $RepoRoot, "--baseline-job-id", $JobId)
        if (-not [string]::IsNullOrWhiteSpace($RunDir)) { $args += @("--pbr-run-dir", $RunDir) }
        $raw = @(& $Python @args 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "PBR human-review gate validation failed: $($raw -join ' ')" }
        try { $value = ([string]$raw[0]) | ConvertFrom-Json -Depth 30 }
        catch { throw "PBR human-review gate validator returned unreadable JSON." }
        if ([string]$value.format -ne "bodyrig-pbr-human-review-gate-context" -or [int]$value.version -ne 1) { throw "PBR human-review gate validator returned wrong format/version." }
        if ($value.comparison_only -ne $true -or $value.human_visual_authority_recorded -ne $true -or $value.physical_acceptance_authority -ne $false -or $value.promotion_authority -ne $false -or $value.production_activation -ne $false) {
            throw "PBR human-review gate crossed the comparison-only authority boundary."
        }
        return $value
    } finally {
        if ($null -eq $oldPythonPath) { [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process") } else { [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process") }
        if ($null -eq $oldNoBytecode) { [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $null, "Process") } else { [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $oldNoBytecode, "Process") }
    }
}

function Assert-GateProbeStable {
    param([Parameter(Mandatory = $true)]$Before,[Parameter(Mandatory = $true)]$After)
    foreach ($field in @(
        "baseline_job_id","person_id","baseline_plan_sha256","candidate_contract_sha256","baseline_revision",
        "pbr_candidate_ref","pbr_candidate_revision","throughput_candidate_ref","throughput_candidate_revision",
        "pbr_run_dir","pbr_human_review_authority_sha256","pbr_human_review_sha256","pbr_decision",
        "stable_evidence_fingerprint_sha256"
    )) {
        if ([string]$Before.$field -ne [string]$After.$field) { throw "PBR human-review gate changed during throughput candidate launch: $field" }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig PBR-gated throughput candidate launcher is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required for PBR-to-throughput gate authority." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
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

$gateBefore = Invoke-PbrGateProbe -RepoRoot $repoRoot -Python $BodyRigPython -JobId $BaselineJobId -RunDir $PbrRunDir
Write-Host "Plan-bound PBR human review is exact and recorded. Starting throughput transition through internal launcher..."

$internal = Need-File -Path (Join-Path $repoRoot "start-throughput-candidate-from-ab-plan-internal.ps1") -Label "internal throughput candidate launcher"
$internalParams = @{ BaselineJobId = $BaselineJobId; BaseUri = $BaseUri; BodyRigPython = $BodyRigPython }
$raw = @(& $internal @internalParams)
if ($raw.Count -ne 1) { throw "Internal throughput candidate launcher did not return exactly one machine-readable result." }
try { $started = ([string]$raw[0]) | ConvertFrom-Json -Depth 30 }
catch { throw "Internal throughput candidate launcher returned unreadable JSON." }
$candidateJobId = [string]$started.candidate_job_id
if ([string]::IsNullOrWhiteSpace($candidateJobId)) { $candidateJobId = [string]$started.job_id }
if ($candidateJobId -notmatch '^job-[0-9a-f]{32}$') { throw "Internal throughput candidate launcher did not return a canonical candidate job id." }
if ([string]$started.person_id -ne [string]$gateBefore.person_id -or ([string]$started.throughput_candidate_revision -ne "" -and [string]$started.throughput_candidate_revision -ne [string]$gateBefore.throughput_candidate_revision)) {
    $cancel = Try-CancelCandidateJob -JobId $candidateJobId -UriBase $BaseUri
    throw "Internal throughput candidate result does not match PBR-gated Person/revision authority; $cancel."
}

$runPlanPath = Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$candidateJobId.json"
$runPlanPath = Need-File -Path $runPlanPath -Label "throughput candidate run plan"
$runPlanSha = File-Sha256 -Path $runPlanPath

try {
    $gateAfter = Invoke-PbrGateProbe -RepoRoot $repoRoot -Python $BodyRigPython -JobId $BaselineJobId -RunDir ([string]$gateBefore.pbr_run_dir)
    Assert-GateProbeStable -Before $gateBefore -After $gateAfter
} catch {
    $cancel = Try-CancelCandidateJob -JobId $candidateJobId -UriBase $BaseUri
    if (Test-Path -LiteralPath $runPlanPath -PathType Leaf) { Remove-Item -LiteralPath $runPlanPath -Force -ErrorAction SilentlyContinue }
    throw "PBR human-review authority drifted while starting throughput candidate; removed candidate-run authority when present. $cancel. $($_.Exception.Message)"
}

$gateReceiptPath = Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$candidateJobId-pbr-gate.json"
$gateReceipt = [ordered]@{
    format = "bodyrig-throughput-pbr-human-review-gate"
    version = 1
    baseline_job_id = $BaselineJobId
    candidate_job_id = $candidateJobId
    person_id = [string]$gateAfter.person_id
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
try { Write-CreateOnlyJson -Path $gateReceiptPath -Value $gateReceipt }
catch {
    $cancel = Try-CancelCandidateJob -JobId $candidateJobId -UriBase $BaseUri
    if (Test-Path -LiteralPath $runPlanPath -PathType Leaf) { Remove-Item -LiteralPath $runPlanPath -Force -ErrorAction SilentlyContinue }
    throw "Could not publish create-only PBR-to-throughput gate receipt; removed candidate-run authority when present. $cancel. $($_.Exception.Message)"
}

Write-Host "PBR-to-throughput gate: RECORDED"
Write-Host "Gate receipt: $gateReceiptPath"
Write-Host "Authority: PBR human review recorded; no physical acceptance, promotion or production activation."
[Console]::Out.WriteLine(([string]$raw[0]))
