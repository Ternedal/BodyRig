param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$CandidateJobId,

    [Parameter(Mandatory = $true)]
    [string]$RunDir,

    [Parameter(Mandatory = $true)]
    [ValidateSet("pass", "fail")]
    [string]$IdentityShape,

    [Parameter(Mandatory = $true)]
    [ValidateSet("pass", "fail")]
    [string]$FaceIdentity,

    [Parameter(Mandatory = $true)]
    [ValidateSet("pass", "fail")]
    [string]$SkinTextureAlignment,

    [Parameter(Mandatory = $true)]
    [ValidateSet("pass", "fail")]
    [string]$GrossAnatomy,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Note,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmVisualReview,

    [string]$Reviewer = "",
    [string]$Out = "",
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
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
    catch { throw "$Label is unreadable JSON: $Path" }
    if ($null -eq $value) { throw "$Label is empty: $Path" }
    return $value
}

function File-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite PBR-sequenced throughput human-review authority: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Invoke-PbrGateProbe {
    param([Parameter(Mandatory = $true)][string]$Python,[Parameter(Mandatory = $true)][string]$RunPath)
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldNoBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
    try {
        $bound = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" }
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $bound, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.pbr_human_review_gate as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound PBR gate validator." }
        $expected = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\pbr_human_review_gate.py"))
        $actual = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actual, $expected, [StringComparison]::OrdinalIgnoreCase)) { throw "PBR gate validator imported from wrong checkout: $actual" }
        $raw = @(& $Python -m bodyrig.pbr_human_review_gate --repo-root $RepoRoot --baseline-job-id $BaselineJobId --pbr-run-dir $RunPath 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "PBR gate validation failed at throughput human review: $($raw -join ' ')" }
        try { $value = ([string]$raw[0]) | ConvertFrom-Json -Depth 40 }
        catch { throw "PBR gate validator returned unreadable JSON." }
        if ([string]$value.format -ne "bodyrig-pbr-human-review-gate-context" -or [int]$value.version -ne 1) { throw "PBR gate validator returned wrong format/version." }
        return $value
    } finally {
        if ($null -eq $oldPythonPath) { [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process") } else { [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process") }
        if ($null -eq $oldNoBytecode) { [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $null, "Process") } else { [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $oldNoBytecode, "Process") }
    }
}

function Assert-GateMatchesProbe {
    param([Parameter(Mandatory = $true)]$Gate,[Parameter(Mandatory = $true)]$Probe)
    if ([string]$Gate.format -ne "bodyrig-throughput-pbr-human-review-gate" -or [int]$Gate.version -ne 1) { throw "PBR-to-throughput gate format/version mismatch." }
    if ($Gate.comparison_only -ne $true -or $Gate.human_visual_authority_recorded -ne $true -or $Gate.physical_acceptance_authority -ne $false -or $Gate.promotion_authority -ne $false -or $Gate.production_activation -ne $false) { throw "PBR-to-throughput gate crossed authority boundary." }
    foreach ($field in @(
        "baseline_job_id","person_id","stash_performer_id","baseline_plan_sha256","candidate_contract_sha256","baseline_revision",
        "pbr_candidate_ref","pbr_candidate_revision","throughput_candidate_ref","throughput_candidate_revision",
        "pbr_run_dir","pbr_human_review_authority_sha256","pbr_human_review_sha256","pbr_decision"
    )) {
        $probeField = if ($field -eq "pbr_run_dir") { "pbr_run_dir" } else { $field }
        if ([string]$Gate.$field -ne [string]$Probe.$probeField) { throw "PBR-to-throughput gate no longer matches PBR authority: $field" }
    }
    if ([string]$Gate.pbr_stable_evidence_fingerprint_sha256 -ne [string]$Probe.stable_evidence_fingerprint_sha256) { throw "PBR-to-throughput stable evidence fingerprint changed." }
    if ([string]$Gate.baseline_job_id -ne $BaselineJobId -or [string]$Gate.candidate_job_id -ne $CandidateJobId) { throw "PBR-to-throughput gate does not match selected jobs." }
}

if (-not $ConfirmVisualReview) { throw "Pass -ConfirmVisualReview only after visually comparing all four canonical baseline/candidate views." }
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig PBR-sequenced throughput human review is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required for PBR-sequenced throughput authority." }
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
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

$gatePath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$CandidateJobId-pbr-gate.json") -Label "PBR-to-throughput gate receipt"
$gate = Read-Json -Path $gatePath -Label "PBR-to-throughput gate receipt"
$probeBefore = Invoke-PbrGateProbe -Python $BodyRigPython -RunPath ([string]$gate.pbr_run_dir)
Assert-GateMatchesProbe -Gate $gate -Probe $probeBefore
$runPlanPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$CandidateJobId.json") -Label "throughput candidate run plan"
if ([string]$gate.candidate_run_plan_sha256 -ne (File-Sha256 -Path $runPlanPath)) { throw "PBR-to-throughput gate no longer binds the exact candidate-run plan bytes." }
$gateSha = File-Sha256 -Path $gatePath
$runPlanSha = File-Sha256 -Path $runPlanPath

$RunDir = [IO.Path]::GetFullPath($RunDir)
$intermediateAuthorityPath = "$RunDir.plan-bound-human-review-authority.json"
$sequencedAuthorityPath = "$RunDir.pbr-sequenced-human-review-authority.json"
if (Test-Path -LiteralPath $sequencedAuthorityPath) { throw "PBR-sequenced throughput human-review authority already exists: $sequencedAuthorityPath" }

if (-not (Test-Path -LiteralPath $intermediateAuthorityPath -PathType Leaf)) {
    $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($null -eq $pwsh) { throw "pwsh is required to isolate the internal plan-bound throughput human review recorder." }
    $internal = Need-File -Path (Join-Path $RepoRoot "record-throughput-human-review-from-ab-plan-internal.ps1") -Label "internal plan-bound throughput human review recorder"
    $childArgs = @(
        "-NoLogo","-NoProfile","-File",$internal,
        "-BaselineJobId",$BaselineJobId,
        "-CandidateJobId",$CandidateJobId,
        "-RunDir",$RunDir,
        "-IdentityShape",$IdentityShape,
        "-FaceIdentity",$FaceIdentity,
        "-SkinTextureAlignment",$SkinTextureAlignment,
        "-GrossAnatomy",$GrossAnatomy,
        "-Note",$Note.Trim(),
        "-ConfirmVisualReview",
        "-RepoRoot",$RepoRoot,
        "-BodyRigPython",$BodyRigPython
    )
    if (-not [string]::IsNullOrWhiteSpace($Reviewer)) { $childArgs += @("-Reviewer",$Reviewer.Trim()) }
    if (-not [string]::IsNullOrWhiteSpace($Out)) { $childArgs += @("-Out",$Out) }
    & $pwsh.Source @childArgs
    if ($LASTEXITCODE -ne 0) { throw "Internal plan-bound throughput human review recorder failed with exit code $LASTEXITCODE." }
}

$intermediateAuthorityPath = Need-File -Path $intermediateAuthorityPath -Label "intermediate plan-bound throughput human-review authority"
$intermediate = Read-Json -Path $intermediateAuthorityPath -Label "intermediate plan-bound throughput human-review authority"
if ([string]$intermediate.format -ne "bodyrig-throughput-plan-bound-human-review-authority" -or [int]$intermediate.version -ne 1) { throw "Intermediate throughput human-review authority format/version mismatch." }
if ([string]$intermediate.baseline_job_id -ne $BaselineJobId -or [string]$intermediate.candidate_job_id -ne $CandidateJobId -or [string]$intermediate.person_id -ne [string]$gate.person_id) { throw "Intermediate throughput human-review authority does not match PBR-gated jobs/Person." }
if ([string]$intermediate.baseline_plan_sha256 -ne [string]$gate.baseline_plan_sha256 -or [string]$intermediate.candidate_run_plan_sha256 -ne $runPlanSha -or [string]$intermediate.candidate_contract_sha256 -ne [string]$gate.candidate_contract_sha256) { throw "Intermediate throughput human-review authority does not bind PBR-gated plan bytes." }
if ([string]$intermediate.baseline_bodyrig_revision -ne [string]$gate.baseline_revision -or [string]$intermediate.throughput_candidate_ref -ne [string]$gate.throughput_candidate_ref -or [string]$intermediate.throughput_candidate_revision -ne [string]$gate.throughput_candidate_revision) { throw "Intermediate throughput human-review authority does not bind PBR-gated revisions." }
if ($intermediate.human_visual_authority_recorded -ne $true -or $intermediate.human_visual_review_completed -ne $true -or $intermediate.comparison_only -ne $true -or $intermediate.physical_acceptance_authority -ne $false -or $intermediate.promotion_authority -ne $false -or $intermediate.production_activation -ne $false) { throw "Intermediate throughput human-review authority crossed canonical boundary." }
$intermediateSha = File-Sha256 -Path $intermediateAuthorityPath

$probeAfter = Invoke-PbrGateProbe -Python $BodyRigPython -RunPath ([string]$gate.pbr_run_dir)
Assert-GateMatchesProbe -Gate $gate -Probe $probeAfter
if ((File-Sha256 -Path $gatePath) -ne $gateSha -or (File-Sha256 -Path $runPlanPath) -ne $runPlanSha) { throw "PBR gate or candidate-run plan changed during throughput human review." }

$sequenced = [ordered]@{
    format = "bodyrig-throughput-pbr-sequenced-human-review-authority"
    version = 1
    baseline_job_id = $BaselineJobId
    candidate_job_id = $CandidateJobId
    person_id = [string]$gate.person_id
    stash_performer_id = [string]$gate.stash_performer_id
    pbr_gate_sha256 = $gateSha
    pbr_human_review_authority_sha256 = [string]$gate.pbr_human_review_authority_sha256
    pbr_human_review_sha256 = [string]$gate.pbr_human_review_sha256
    pbr_decision = [string]$gate.pbr_decision
    candidate_run_plan_sha256 = $runPlanSha
    plan_bound_human_review_authority_sha256 = $intermediateSha
    throughput_human_review_sha256 = [string]$intermediate.human_review_sha256
    human_visual_review_completed = $true
    human_visual_review_passed = [bool]$intermediate.human_visual_review_passed
    decision = [string]$intermediate.decision
    next_gate = [string]$intermediate.next_gate
    pbr_human_visual_authority_recorded = $true
    human_visual_authority_recorded = $true
    comparison_only = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}
try {
    Write-CreateOnlyJson -Path $sequencedAuthorityPath -Value $sequenced
    $terminalProbe = Invoke-PbrGateProbe -Python $BodyRigPython -RunPath ([string]$gate.pbr_run_dir)
    Assert-GateMatchesProbe -Gate $gate -Probe $terminalProbe
    if ((File-Sha256 -Path $gatePath) -ne $gateSha -or (File-Sha256 -Path $runPlanPath) -ne $runPlanSha -or (File-Sha256 -Path $intermediateAuthorityPath) -ne $intermediateSha) { throw "Sequenced throughput authority inputs changed before terminal publication." }
} catch {
    if (Test-Path -LiteralPath $sequencedAuthorityPath -PathType Leaf) { Remove-Item -LiteralPath $sequencedAuthorityPath -Force -ErrorAction SilentlyContinue }
    throw
}

Write-Host "BodyRig PBR-sequenced throughput human review: RECORDED"
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "Candidate job:      $CandidateJobId"
Write-Host "Stash performer:    $($gate.stash_performer_id)"
Write-Host "PBR decision:       $($gate.pbr_decision)"
Write-Host "Throughput decision:$($intermediate.decision)"
Write-Host "Sequenced authority:$sequencedAuthorityPath"
Write-Host "Authority: comparison-only human evidence; no physical acceptance, promotion or production activation."
exit 0
