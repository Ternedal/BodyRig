param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [string]$RigSetupReport = "",
    [ValidatePattern('^[A-Za-z0-9._/-]{1,200}$')]
    [string]$CandidateRef = "candidate/skin-pbr-v3-linear-light-20260909",
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$UnityExe = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical Git revision: $Value" }
    return $normalized
}

function Read-JsonObject {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
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
    if (@(Compare-Object -ReferenceObject $wanted -DifferenceObject $actual).Count -gt 0) {
        throw "$Label fields do not match the canonical contract."
    }
}

function Invoke-Git {
    param([Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Step)
    $raw = @(& git @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "$Step failed: $($raw -join ' ')" }
    return @($raw)
}

function Assert-CleanMain {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[Parameter(Mandatory = $true)][string]$ExpectedRevision)
    $branch = ((Invoke-Git -Arguments @("-C",$RepoRoot,"branch","--show-current") -Step "Resolve current branch") -join "").Trim()
    if ($branch -ne "main") { throw "Plan-bound PBR body-job reuse must be launched from branch main." }
    $head = Need-Revision -Value (((Invoke-Git -Arguments @("-C",$RepoRoot,"rev-parse","HEAD") -Step "Resolve current HEAD") -join "")) -Label "current HEAD"
    if ($head -ne $ExpectedRevision) { throw "BodyRig HEAD does not match the shared A/B baseline plan revision." }
    $dirty = @(Invoke-Git -Arguments @("-C",$RepoRoot,"status","--porcelain") -Step "Verify checkout cleanliness")
    if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; plan-bound PBR reuse requires exact clean main." }
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
        if ($LASTEXITCODE -ne 0 -or $probeRaw.Count -ne 1) { throw "Could not prove checkout-bound $Label module: $($probeRaw -join ' ')" }
        $expectedPath = [IO.Path]::GetFullPath((Join-Path $RepoRoot $ExpectedModulePath))
        $actualPath = [IO.Path]::GetFullPath(([string]$probeRaw[0]).Trim())
        if (-not [string]::Equals($actualPath,$expectedPath,[StringComparison]::OrdinalIgnoreCase)) {
            throw "$Label module imported from wrong checkout: $actualPath"
        }
        $raw = @(& $Python -m $Module @Arguments 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "$Label failed: $($raw -join ' ')" }
        try { return (([string]$raw[0]) | ConvertFrom-Json) }
        catch { throw "$Label returned unreadable JSON." }
    }
    finally {
        if ([string]::IsNullOrEmpty($oldPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
        if ([string]::IsNullOrEmpty($oldNoBytecode)) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode }
    }
}

function Validate-CandidateAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$MainRevision,
        [Parameter(Mandatory = $true)][string]$PbrRevision,
        [Parameter(Mandatory = $true)][string]$ThroughputRevision,
        [Parameter(Mandatory = $true)][string]$ContractSha256,
        [Parameter(Mandatory = $true)][string]$PbrRef,
        [Parameter(Mandatory = $true)][string]$ThroughputRef,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $authority = Invoke-CheckoutPythonJson `
        -RepoRoot $RepoRoot `
        -Python $Python `
        -Module "bodyrig.ab_baseline_candidates" `
        -ExpectedModulePath "bodyrig\ab_baseline_candidates.py" `
        -Label $Label `
        -Arguments @(
            "--repo-root", $RepoRoot,
            "--expected-main-revision", $MainRevision,
            "--expected-pbr-revision", $PbrRevision,
            "--expected-throughput-revision", $ThroughputRevision
        )
    if (
        [string]$authority.format -ne "bodyrig-ab-baseline-candidate-authority" -or
        [int]$authority.version -ne 1 -or
        [string]$authority.main_revision -ne $MainRevision -or
        [string]$authority.contract_sha256 -ne $ContractSha256 -or
        [string]$authority.candidates.pbr_v3.ref -ne $PbrRef -or
        [string]$authority.candidates.pbr_v3.revision -ne $PbrRevision -or
        [string]$authority.candidates.recovery_throughput_v3.ref -ne $ThroughputRef -or
        [string]$authority.candidates.recovery_throughput_v3.revision -ne $ThroughputRevision -or
        $authority.comparison_only -ne $true -or
        $authority.human_visual_authority_required -ne $true -or
        $authority.physical_acceptance_authority -ne $false -or
        $authority.promotion_authority -ne $false -or
        $authority.production_activation -ne $false
    ) {
        throw "$Label does not match the shared A/B baseline plan."
    }
    return $authority
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite plan-bound PBR authority: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    }
    finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig plan-bound PBR A/B reuse is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required for shared A/B plan authority." }
if ($CandidateRef.Contains("..") -or $CandidateRef.StartsWith("-") -or $CandidateRef.Contains("@{")) { throw "CandidateRef is unsafe." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$planPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId.json") -Label "shared A/B baseline plan"
$plan = Read-JsonObject -Path $planPath -Label "shared A/B baseline plan"
$planSha256 = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()

Require-ExactFields -Value $plan -Label "shared A/B baseline plan" -Expected @(
    "format","version","baseline_job_id","person_id","baseline_bodyrig_revision","candidate_contract_sha256",
    "pbr_candidate","throughput_candidate","ab_baseline_retention","comparison_only","human_visual_authority_required",
    "physical_acceptance_authority","promotion_authority","production_activation"
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
) { throw "Shared A/B baseline plan has invalid identity or authority semantics." }

Require-ExactFields -Value $plan.pbr_candidate -Label "PBR candidate plan" -Expected @("ref","revision","retained_reconstruction_reuse")
Require-ExactFields -Value $plan.throughput_candidate -Label "throughput candidate plan" -Expected @("ref","revision","separate_candidate_body_build_required")
Require-ExactFields -Value $plan.ab_baseline_retention -Label "A/B retention plan" -Expected @("format","version","retain_private_workspace","expected_bodyrig_revision","job_id")

$mainRevision = Need-Revision -Value ([string]$plan.baseline_bodyrig_revision) -Label "baseline plan main revision"
$pbrRef = [string]$plan.pbr_candidate.ref
$pbrRevision = Need-Revision -Value ([string]$plan.pbr_candidate.revision) -Label "baseline plan PBR revision"
$throughputRef = [string]$plan.throughput_candidate.ref
$throughputRevision = Need-Revision -Value ([string]$plan.throughput_candidate.revision) -Label "baseline plan throughput revision"
$contractSha256 = ([string]$plan.candidate_contract_sha256).ToLowerInvariant()
if (
    [string]::IsNullOrWhiteSpace($pbrRef) -or
    [string]::IsNullOrWhiteSpace($throughputRef) -or
    $CandidateRef -ne $pbrRef -or
    $plan.pbr_candidate.retained_reconstruction_reuse -ne $true -or
    $plan.throughput_candidate.separate_candidate_body_build_required -ne $true -or
    [string]$plan.ab_baseline_retention.format -ne "bodyrig-ab-baseline-retention" -or
    [int]$plan.ab_baseline_retention.version -ne 1 -or
    $plan.ab_baseline_retention.retain_private_workspace -ne $true -or
    ([string]$plan.ab_baseline_retention.expected_bodyrig_revision).ToLowerInvariant() -ne $mainRevision -or
    [string]$plan.ab_baseline_retention.job_id -ne $BaselineJobId
) { throw "Shared A/B baseline plan does not bind this exact PBR continuation." }

Assert-CleanMain -RepoRoot $repoRoot -ExpectedRevision $mainRevision
[void](Invoke-Git -Arguments @("-C",$repoRoot,"fetch","--no-tags","origin","+refs/heads/main:refs/remotes/origin/main") -Step "Fetch current origin/main")
$originMain = Need-Revision -Value (((Invoke-Git -Arguments @("-C",$repoRoot,"rev-parse","refs/remotes/origin/main") -Step "Resolve origin/main") -join "")) -Label "origin/main"
if ($originMain -ne $mainRevision) { throw "Shared A/B baseline plan is stale because origin/main moved." }

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

$before = Validate-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython -MainRevision $mainRevision -PbrRevision $pbrRevision -ThroughputRevision $throughputRevision -ContractSha256 $contractSha256 -PbrRef $pbrRef -ThroughputRef $throughputRef -Label "pre-run candidate authority"

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0,8)
    $OutputDir = Join-Path $env:LOCALAPPDATA "BodyRig\pbr-ab-body-job\$BaselineJobId-$stamp-$suffix"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "PBR A/B output already exists: $OutputDir" }

$internal = Need-File -Path (Join-Path $repoRoot "run-pbr-ab-from-body-job-internal.ps1") -Label "internal PBR body-job runner"
$internalArgs = @("-BaselineJobId",$BaselineJobId,"-CandidateRef",$pbrRef,"-OutputDir",$OutputDir,"-BodyRigPython",$BodyRigPython)
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $internalArgs += @("-RigSetupReport",$RigSetupReport) }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $internalArgs += @("-UnityExe",$UnityExe) }
& $internal @internalArgs
if ($LASTEXITCODE -ne 0) { throw "Internal PBR body-job runner failed with exit code $LASTEXITCODE" }

Assert-CleanMain -RepoRoot $repoRoot -ExpectedRevision $mainRevision
$after = Validate-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython -MainRevision $mainRevision -PbrRevision $pbrRevision -ThroughputRevision $throughputRevision -ContractSha256 $contractSha256 -PbrRef $pbrRef -ThroughputRef $throughputRef -Label "post-run candidate authority"
if ([string]$before.contract_sha256 -ne [string]$after.contract_sha256) { throw "Candidate contract changed during PBR A/B run." }

$runAuthorityPath = Need-File -Path (Join-Path $OutputDir "run-authority.json") -Label "PBR A/B run authority"
$runAuthority = Read-JsonObject -Path $runAuthorityPath -Label "PBR A/B run authority"
if (
    [string]$runAuthority.format -ne "bodyrig-pbr-ab-run" -or
    [int]$runAuthority.version -ne 1 -or
    ([string]$runAuthority.baseline_revision).ToLowerInvariant() -ne $mainRevision -or
    ([string]$runAuthority.candidate_revision).ToLowerInvariant() -ne $pbrRevision -or
    $runAuthority.comparison_only -ne $true -or
    $runAuthority.physical_acceptance_authority -ne $false -or
    $runAuthority.production_activation -ne $false
) { throw "PBR run authority does not bind the exact shared baseline plan revisions." }

$sourceAuthorityPath = Need-File -Path (Join-Path $OutputDir "body-job-source-authority.json") -Label "PBR body-job source authority"
$planAuthorityPath = Join-Path $OutputDir "body-job-plan-authority.json"
$planAuthority = [ordered]@{
    format = "bodyrig-pbr-ab-body-job-plan-authority"
    version = 1
    baseline_plan_sha256 = $planSha256
    candidate_contract_sha256 = $contractSha256
    baseline_job_id = $BaselineJobId
    person_id = [string]$plan.person_id
    baseline_revision = $mainRevision
    pbr_candidate_ref = $pbrRef
    pbr_candidate_revision = $pbrRevision
    throughput_candidate_ref = $throughputRef
    throughput_candidate_revision = $throughputRevision
    run_authority_sha256 = (Get-FileHash -LiteralPath $runAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
    source_authority_sha256 = (Get-FileHash -LiteralPath $sourceAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
    comparison_only = $true
    human_visual_authority_required = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}
Write-CreateOnlyJson -Path $planAuthorityPath -Value $planAuthority

Write-Host "BodyRig plan-bound PBR A/B: READY FOR HUMAN REVIEW"
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "Baseline revision:  $mainRevision"
Write-Host "PBR candidate:      $pbrRevision"
Write-Host "Run output:         $OutputDir"
Write-Host "Plan authority:     $planAuthorityPath"
Write-Host "Review:             $(Join-Path $OutputDir 'review.html')"
Write-Host "Authority: comparison-only; human review required; no promotion or production activation."
