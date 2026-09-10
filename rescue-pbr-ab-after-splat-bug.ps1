param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$OperatorPatchRevision,

    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$RigSetupReport = "",
    [string]$UnityExe = ""
)

$ErrorActionPreference = "Stop"
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

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40 }
    catch { throw "$Label is unreadable JSON: $Path" }
    if ($null -eq $value) { throw "$Label is empty: $Path" }
    return $value
}

function Invoke-Git {
    param([Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Step)
    $raw = @(& git @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "$Step failed: $($raw -join ' ')" }
    return @($raw)
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite rescue authority: $Path" }
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

function Write-AtomicUtf8Text {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Text)
    $parent = Split-Path -Parent $Path
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        Set-Content -LiteralPath $temp -Value $Text -Encoding UTF8 -NoNewline
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Assert-CleanMain {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$ExpectedRevision)
    $branch = ((Invoke-Git -Arguments @("-C",$Root,"branch","--show-current") -Step "Resolve current branch") -join "").Trim()
    if ($branch -ne "main") { throw "Rescue requires branch main." }
    $head = Need-Revision -Value (((Invoke-Git -Arguments @("-C",$Root,"rev-parse","HEAD") -Step "Resolve current HEAD") -join "")) -Label "current HEAD"
    if ($head -ne $ExpectedRevision) { throw "BodyRig HEAD does not match the baseline plan revision." }
    $dirty = @(Invoke-Git -Arguments @("-C",$Root,"status","--porcelain") -Step "Verify checkout cleanliness")
    if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; rescue requires exact clean main." }
}

function Invoke-CandidateAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$MainRevision,
        [Parameter(Mandatory = $true)][string]$PbrRevision,
        [Parameter(Mandatory = $true)][string]$ThroughputRevision
    )
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldNoBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
    try {
        $bound = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $Root } else { "$Root$([IO.Path]::PathSeparator)$oldPythonPath" }
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $bound, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.ab_baseline_candidates as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound candidate authority module." }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $Root "bodyrig\ab_baseline_candidates.py"))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) { throw "Candidate authority module imported from wrong checkout: $actualModule" }
        $raw = @(& $Python -m bodyrig.ab_baseline_candidates --repo-root $Root --expected-main-revision $MainRevision --expected-pbr-revision $PbrRevision --expected-throughput-revision $ThroughputRevision 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "Candidate authority validation failed: $($raw -join ' ')" }
        try { return ([string]$raw[0]) | ConvertFrom-Json -Depth 30 }
        catch { throw "Candidate authority validator returned unreadable JSON." }
    } finally {
        if ($null -eq $oldPythonPath) { [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process") } else { [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process") }
        if ($null -eq $oldNoBytecode) { [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $null, "Process") } else { [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $oldNoBytecode, "Process") }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig PBR launcher rescue is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$planPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId.json") -Label "shared A/B baseline plan"
$plan = Read-Json -Path $planPath -Label "shared A/B baseline plan"
if ([string]$plan.format -ne "bodyrig-dual-candidate-ab-baseline-plan" -or [int]$plan.version -ne 1) { throw "Shared A/B baseline plan format/version mismatch." }
if ([string]$plan.baseline_job_id -ne $BaselineJobId -or [string]$plan.person_id -notmatch '^person-[0-9a-f]{32}$') { throw "Shared A/B baseline plan identity mismatch." }
if ($plan.comparison_only -ne $true -or $plan.human_visual_authority_required -ne $true -or $plan.physical_acceptance_authority -ne $false -or $plan.promotion_authority -ne $false -or $plan.production_activation -ne $false) { throw "Shared A/B baseline plan crossed the comparison-only authority boundary." }

$mainRevision = Need-Revision -Value ([string]$plan.baseline_bodyrig_revision) -Label "baseline main revision"
$pbrRef = [string]$plan.pbr_candidate.ref
$pbrRevision = Need-Revision -Value ([string]$plan.pbr_candidate.revision) -Label "PBR candidate revision"
$throughputRef = [string]$plan.throughput_candidate.ref
$throughputRevision = Need-Revision -Value ([string]$plan.throughput_candidate.revision) -Label "throughput candidate revision"
$contractSha = Need-Sha256 -Value ([string]$plan.candidate_contract_sha256) -Label "candidate contract SHA"
if ($plan.pbr_candidate.retained_reconstruction_reuse -ne $true -or $plan.throughput_candidate.separate_candidate_body_build_required -ne $true) { throw "Shared A/B plan does not authorize the expected PBR/throughput sequence." }

Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision
[void](Invoke-Git -Arguments @("-C",$RepoRoot,"fetch","--no-tags","origin","+refs/heads/main:refs/remotes/origin/main","+refs/heads/$pbrRef`:refs/remotes/origin/$pbrRef","+refs/heads/$throughputRef`:refs/remotes/origin/$throughputRef") -Step "Refresh baseline/candidate refs")
$originMain = Need-Revision -Value (((Invoke-Git -Arguments @("-C",$RepoRoot,"rev-parse","refs/remotes/origin/main") -Step "Resolve origin/main") -join "")) -Label "origin/main"
$originPbr = Need-Revision -Value (((Invoke-Git -Arguments @("-C",$RepoRoot,"rev-parse","refs/remotes/origin/$pbrRef") -Step "Resolve PBR candidate") -join "")) -Label "origin PBR candidate"
$originThroughput = Need-Revision -Value (((Invoke-Git -Arguments @("-C",$RepoRoot,"rev-parse","refs/remotes/origin/$throughputRef") -Step "Resolve throughput candidate") -join "")) -Label "origin throughput candidate"
if ($originMain -ne $mainRevision -or $originPbr -ne $pbrRevision -or $originThroughput -ne $throughputRevision) { throw "Baseline or candidate refs moved after the shared A/B plan was created." }

$contractPath = Need-File -Path (Join-Path $RepoRoot "contracts\ab-baseline-candidates-v1.json") -Label "candidate byte contract"
if ((Get-FileHash -LiteralPath $contractPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $contractSha) { throw "Candidate byte contract no longer matches the shared A/B plan." }

$OperatorPatchRevision = Need-Revision -Value $OperatorPatchRevision -Label "operator patch revision"
$mergeBase = Need-Revision -Value (((Invoke-Git -Arguments @("-C",$RepoRoot,"merge-base",$mainRevision,$OperatorPatchRevision) -Step "Resolve operator patch merge base") -join "")) -Label "operator patch merge base"
if ($mergeBase -ne $mainRevision) { throw "Operator patch is not based exactly on the baseline main revision." }
$changed = @((Invoke-Git -Arguments @("-C",$RepoRoot,"diff","--name-only","--no-renames","$mainRevision..$OperatorPatchRevision","--") -Step "Inspect operator patch paths") | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
$expectedChanged = @(
    "rescue-pbr-ab-after-splat-bug.ps1",
    "run-pbr-ab-from-body-job.ps1",
    "tests/test_pbr_ab_plan_bound_wrapper.py",
    "tests/test_pbr_ab_splat_rescue_contract.py"
) | Sort-Object
if (@(Compare-Object -ReferenceObject $expectedChanged -DifferenceObject @($changed | Sort-Object)).Count -gt 0) { throw "Operator patch changed-file set is not the reviewed launcher-only rescue set." }
$patchedWrapper = ((Invoke-Git -Arguments @("-C",$RepoRoot,"show","${OperatorPatchRevision}:run-pbr-ab-from-body-job.ps1") -Step "Inspect patched canonical wrapper") -join "`n")
if ($patchedWrapper -notlike '*$internalParams = @{*' -or $patchedWrapper -notlike '*& $internal @internalParams*' -or $patchedWrapper -like '*& $internal @internalArgs*') { throw "Operator patch does not contain the reviewed named-splat launcher correction." }
$currentWrapper = Get-Content -LiteralPath (Join-Path $RepoRoot "run-pbr-ab-from-body-job.ps1") -Raw -Encoding UTF8
if ($currentWrapper -notlike '*$internalArgs = @(*' -or $currentWrapper -notlike '*& $internal @internalArgs*') { throw "Baseline checkout no longer contains the exact launcher defect this rescue is scoped to." }

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

$before = Invoke-CandidateAuthority -Root $RepoRoot -Python $BodyRigPython -MainRevision $mainRevision -PbrRevision $pbrRevision -ThroughputRevision $throughputRevision
if ([string]$before.contract_sha256 -ne $contractSha -or [string]$before.candidates.pbr_v3.ref -ne $pbrRef -or [string]$before.candidates.recovery_throughput_v3.ref -ne $throughputRef) { throw "Pre-run candidate authority does not match the shared A/B plan." }

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0,8)
    $OutputDir = Join-Path $env:LOCALAPPDATA "BodyRig\pbr-ab-body-job\$BaselineJobId-$stamp-$suffix"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "PBR A/B output already exists: $OutputDir" }

$internal = Need-File -Path (Join-Path $RepoRoot "run-pbr-ab-from-body-job-internal.ps1") -Label "baseline internal PBR runner"
$internalParams = @{
    BaselineJobId = $BaselineJobId
    CandidateRef = $pbrRef
    OutputDir = $OutputDir
    BodyRigPython = $BodyRigPython
}
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $internalParams.RigSetupReport = $RigSetupReport }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $internalParams.UnityExe = $UnityExe }
& $internal @internalParams
if ($LASTEXITCODE -ne 0) { throw "Baseline internal PBR runner failed with exit code $LASTEXITCODE" }

Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision
$after = Invoke-CandidateAuthority -Root $RepoRoot -Python $BodyRigPython -MainRevision $mainRevision -PbrRevision $pbrRevision -ThroughputRevision $throughputRevision
if ([string]$after.contract_sha256 -ne $contractSha) { throw "Candidate contract changed during rescued PBR A/B run." }

$OutputDir = Need-Directory -Path $OutputDir -Label "completed rescued PBR A/B run"
$runAuthorityPath = Need-File -Path (Join-Path $OutputDir "run-authority.json") -Label "PBR run authority"
$sourceAuthorityPath = Need-File -Path (Join-Path $OutputDir "body-job-source-authority.json") -Label "PBR source authority"
[void](Need-File -Path (Join-Path $OutputDir "machine-ab.json") -Label "PBR machine A/B evidence")
[void](Need-Directory -Path (Join-Path $OutputDir "baseline-render") -Label "baseline render set")
[void](Need-Directory -Path (Join-Path $OutputDir "candidate-render") -Label "candidate render set")
[void](Need-File -Path (Join-Path $OutputDir "review.html") -Label "PBR review page")
$runAuthority = Read-Json -Path $runAuthorityPath -Label "PBR run authority"
if ([string]$runAuthority.format -ne "bodyrig-pbr-ab-run" -or [int]$runAuthority.version -ne 1 -or (Need-Revision -Value ([string]$runAuthority.baseline_revision) -Label "run baseline revision") -ne $mainRevision -or (Need-Revision -Value ([string]$runAuthority.candidate_revision) -Label "run candidate revision") -ne $pbrRevision -or $runAuthority.comparison_only -ne $true -or $runAuthority.physical_acceptance_authority -ne $false -or $runAuthority.production_activation -ne $false) { throw "PBR run authority does not match the shared plan boundary." }

$planSha = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
$runSha = (Get-FileHash -LiteralPath $runAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sourceSha = (Get-FileHash -LiteralPath $sourceAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
$planAuthorityPath = Join-Path $OutputDir "body-job-plan-authority.json"
$planAuthority = [ordered]@{
    format = "bodyrig-pbr-ab-body-job-plan-authority"
    version = 1
    baseline_plan_sha256 = $planSha
    candidate_contract_sha256 = $contractSha
    baseline_job_id = $BaselineJobId
    person_id = [string]$plan.person_id
    baseline_revision = $mainRevision
    pbr_candidate_ref = $pbrRef
    pbr_candidate_revision = $pbrRevision
    throughput_candidate_ref = $throughputRef
    throughput_candidate_revision = $throughputRevision
    run_authority_sha256 = $runSha
    source_authority_sha256 = $sourceSha
    comparison_only = $true
    human_visual_authority_required = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}
Write-CreateOnlyJson -Path $planAuthorityPath -Value $planAuthority

$rescueAuthorityPath = Join-Path $OutputDir "launcher-rescue-authority.json"
$rescueAuthority = [ordered]@{
    format = "bodyrig-pbr-launcher-splat-rescue-authority"
    version = 1
    reason = "canonical-pbr-wrapper-positional-array-splat-bug"
    baseline_job_id = $BaselineJobId
    baseline_revision = $mainRevision
    operator_patch_revision = $OperatorPatchRevision
    operator_patch_changed_paths = $expectedChanged
    baseline_plan_sha256 = $planSha
    run_authority_sha256 = $runSha
    source_authority_sha256 = $sourceSha
    plan_authority_sha256 = (Get-FileHash -LiteralPath $planAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
    comparison_only = $true
    human_visual_authority_required = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}
Write-CreateOnlyJson -Path $rescueAuthorityPath -Value $rescueAuthority

$reviewNextPath = Join-Path $OutputDir "REVIEW-NEXT.txt"
$reviewText = @"
# BodyRig plan-bound PBR A/B human review after launcher-only rescue
# Open review.html and compare all four canonical LEFT/RIGHT views first.

.\record-pbr-ab-human-review-from-plan.ps1 ``
  -BaselineJobId '$BaselineJobId' ``
  -RunDir '$OutputDir' ``
  -Decision '<left|right|tie|reject-both>' ``
  -QualityNote '<actual visual assessment>' ``
  -ConfirmVisualReview
"@
Write-AtomicUtf8Text -Path $reviewNextPath -Text $reviewText

Write-Host "BodyRig PBR launcher rescue: READY FOR EXPLICIT HUMAN REVIEW"
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "Baseline revision:  $mainRevision"
Write-Host "Operator patch:     $OperatorPatchRevision"
Write-Host "Run output:         $OutputDir"
Write-Host "Review page:        $(Join-Path $OutputDir 'review.html')"
Write-Host "Review command:     $reviewNextPath"
Write-Host "Rescue authority:   $rescueAuthorityPath"
Write-Host "Authority: comparison-only; no physical acceptance, promotion or production activation."
exit 0
