param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$RigSetupReport = "",
    [string]$UnityExe = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedBaselineRevision = "6e10351e4eba929062960ac46ec1582a467db259"
$CanonicalLauncherRescueRevision = "73d5af8c4bdadff00d5cb3685e2e7e8bbd945d04"
$ExpectedStrictRunnerBlob = "daa5361880a32c341a87342a58c6f8fc575882c7"
$ExpectedInternalRunnerBlob = "0c4d6cc1cdd07081ae88e3b08ea07d8550c9b83f"
$ExpectedLauncherRescueBlob = "1535e07b88ad7fdafb9b26f03abb1ae0bfcd550b"

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
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
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

function Git-One {
    param([Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Step)
    $raw = @(Invoke-Git -Arguments $Arguments -Step $Step)
    if ($raw.Count -ne 1) { throw "$Step returned $($raw.Count) lines; expected exactly one." }
    return ([string]$raw[0]).Trim()
}

function Assert-CleanMain {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$ExpectedRevision)
    $branch = Git-One -Arguments @("-C",$Root,"branch","--show-current") -Step "Resolve current branch"
    if ($branch -ne "main") { throw "Strict-fetch rescue requires branch main." }
    $head = Need-Revision -Value (Git-One -Arguments @("-C",$Root,"rev-parse","HEAD") -Step "Resolve current HEAD") -Label "current HEAD"
    if ($head -ne $ExpectedRevision) { throw "BodyRig HEAD differs from the exact baseline revision." }
    $dirty = @(Invoke-Git -Arguments @("-C",$Root,"status","--porcelain") -Step "Verify checkout cleanliness")
    if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; strict-fetch rescue refuses hidden checkout mutation." }
}

function Replace-ExactOnce {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Old,
        [Parameter(Mandatory = $true)][string]$New,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $count = [regex]::Matches($Text,[regex]::Escape($Old)).Count
    if ($count -ne 1) { throw "$Label source shape changed; expected exactly one reviewed match, got $count." }
    return $Text.Replace($Old,$New)
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite strict-fetch rescue authority: $Path" }
    $parent = Split-Path -Parent $Path
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temp -Encoding UTF8
        [IO.File]::Move($temp,$Path)
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig strict-fetch rescue is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$planPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId.json") -Label "shared A/B baseline plan"
$plan = Read-Json -Path $planPath -Label "shared A/B baseline plan"
if ([string]$plan.format -ne "bodyrig-dual-candidate-ab-baseline-plan" -or [int]$plan.version -ne 1 -or [string]$plan.baseline_job_id -ne $BaselineJobId) {
    throw "Shared A/B baseline plan identity/format mismatch."
}
if ($plan.comparison_only -ne $true -or $plan.human_visual_authority_required -ne $true -or $plan.physical_acceptance_authority -ne $false -or $plan.promotion_authority -ne $false -or $plan.production_activation -ne $false) {
    throw "Shared A/B plan crossed the comparison-only authority boundary."
}
$mainRevision = Need-Revision -Value ([string]$plan.baseline_bodyrig_revision) -Label "baseline revision"
if ($mainRevision -ne $ExpectedBaselineRevision) { throw "This rescue is scoped only to baseline $ExpectedBaselineRevision, not $mainRevision." }
Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision

[void](Invoke-Git -Arguments @("-C",$RepoRoot,"fetch","--no-tags","origin","+refs/heads/main:refs/remotes/origin/main") -Step "Refresh origin/main")
$originMain = Need-Revision -Value (Git-One -Arguments @("-C",$RepoRoot,"rev-parse","refs/remotes/origin/main") -Step "Resolve origin/main") -Label "origin/main"
if ($originMain -ne $mainRevision) { throw "origin/main moved after the shared A/B plan was created." }
Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision

$jobRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "BodyRig\ui-jobs\$BaselineJobId"))
$jobPath = Need-File -Path (Join-Path $jobRoot "job.json") -Label "succeeded baseline job"
$job = Read-Json -Path $jobPath -Label "succeeded baseline job"
if ([string]$job.format -ne "bodyrig-ui-job" -or [int]$job.version -ne 1 -or [string]$job.kind -ne "body-build" -or [string]$job.status -ne "succeeded") {
    throw "Strict-fetch rescue requires the exact succeeded body-build job."
}
if ([string]$job.job_id -ne $BaselineJobId -or [string]$job.person_id -ne [string]$plan.person_id) { throw "Baseline job identity differs from the shared plan." }
if ((Need-Revision -Value ([string]$job.bodyrig_revision) -Label "job revision") -ne $mainRevision) { throw "Baseline job revision differs from shared plan." }
$expectedReviewSha = Need-Sha256 -Value ([string]$job.body_review_sha256) -Label "job body review SHA"
$fidelityDir = Need-Directory -Path ([string]$job.fidelity_dir) -Label "baseline fidelity directory"
$mirrorPath = Need-File -Path (Join-Path $fidelityDir "review.json") -Label "repaired fidelity review mirror"
$mirrorSha = (Get-FileHash -LiteralPath $mirrorPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($mirrorSha -ne $expectedReviewSha) { throw "Repaired fidelity review mirror no longer matches job.body_review_sha256." }
$repairAuthorityPath = Need-File -Path (Join-Path $fidelityDir "review-mirror-repair-authority.json") -Label "fidelity mirror repair authority"
$repairAuthority = Read-Json -Path $repairAuthorityPath -Label "fidelity mirror repair authority"
if ([string]$repairAuthority.format -ne "bodyrig-fidelity-review-mirror-repair-authority" -or [int]$repairAuthority.version -ne 1 -or
    [string]$repairAuthority.reason -ne "succeeded-ui-job-persisted-review-not-mirrored-to-fidelity-output" -or
    [string]$repairAuthority.job_id -ne $BaselineJobId -or [string]$repairAuthority.person_id -ne [string]$job.person_id -or
    (Need-Revision -Value ([string]$repairAuthority.bodyrig_revision) -Label "repair authority revision") -ne $mainRevision -or
    (Need-Sha256 -Value ([string]$repairAuthority.body_review_sha256) -Label "repair body review SHA") -ne $expectedReviewSha -or
    (Need-Sha256 -Value ([string]$repairAuthority.fidelity_review_mirror_sha256) -Label "repair mirror SHA") -ne $mirrorSha -or
    $repairAuthority.comparison_only -ne $true -or $repairAuthority.human_visual_authority_created -ne $false -or
    $repairAuthority.physical_acceptance_authority -ne $false -or $repairAuthority.promotion_authority -ne $false -or $repairAuthority.production_activation -ne $false) {
    throw "Fidelity mirror repair authority is missing, stale or crossed the comparison-only boundary."
}
$repairAuthoritySha = (Get-FileHash -LiteralPath $repairAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()

$strictBlob = (Git-One -Arguments @("-C",$RepoRoot,"rev-parse","${mainRevision}:run-pbr-ab-physical-review.ps1") -Step "Resolve strict runner blob").ToLowerInvariant()
$internalBlob = (Git-One -Arguments @("-C",$RepoRoot,"rev-parse","${mainRevision}:run-pbr-ab-from-body-job-internal.ps1") -Step "Resolve internal runner blob").ToLowerInvariant()
$launcherBlob = (Git-One -Arguments @("-C",$RepoRoot,"rev-parse","${CanonicalLauncherRescueRevision}:rescue-pbr-ab-after-splat-bug.ps1") -Step "Resolve launcher rescue blob").ToLowerInvariant()
if ($strictBlob -ne $ExpectedStrictRunnerBlob) { throw "Strict runner blob changed from reviewed baseline bytes." }
if ($internalBlob -ne $ExpectedInternalRunnerBlob) { throw "Internal runner blob changed from reviewed baseline bytes." }
if ($launcherBlob -ne $ExpectedLauncherRescueBlob) { throw "Canonical launcher rescue blob changed from reviewed bytes." }

$strictText = (Invoke-Git -Arguments @("-C",$RepoRoot,"show","${mainRevision}:run-pbr-ab-physical-review.ps1") -Step "Read baseline strict runner") -join "`n"
$internalText = (Invoke-Git -Arguments @("-C",$RepoRoot,"show","${mainRevision}:run-pbr-ab-from-body-job-internal.ps1") -Step "Read baseline internal runner") -join "`n"
$launcherText = (Invoke-Git -Arguments @("-C",$RepoRoot,"show","${CanonicalLauncherRescueRevision}:rescue-pbr-ab-after-splat-bug.ps1") -Step "Read canonical launcher rescue") -join "`n"

$oldRepoRoot = '$repoRoot = (Resolve-Path $PSScriptRoot).Path'
$newRepoRoot = '$repoRoot = [IO.Path]::GetFullPath([Environment]::GetEnvironmentVariable("BODYRIG_RESCUE_REPO_ROOT","Process"))'
$strictText = Replace-ExactOnce -Text $strictText -Old $oldRepoRoot -New $newRepoRoot -Label "strict runner repo-root overlay"

$oldInitialFetch = '[void](Invoke-Git -Arguments @("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs -Step "Fetch baseline/candidate refs")'
$newInitialFetch = '[void](Invoke-Git -Arguments (@("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs) -Step "Fetch baseline/candidate refs")'
$strictText = Replace-ExactOnce -Text $strictText -Old $oldInitialFetch -New $newInitialFetch -Label "strict runner initial fetch binding"

$oldFinalFetch = '[void](Invoke-Git -Arguments @("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs -Step "Recheck remote refs after A/B")'
$newFinalFetch = '[void](Invoke-Git -Arguments (@("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs) -Step "Recheck remote refs after A/B")'
$strictText = Replace-ExactOnce -Text $strictText -Old $oldFinalFetch -New $newFinalFetch -Label "strict runner terminal fetch binding"

$internalText = Replace-ExactOnce -Text $internalText -Old $oldRepoRoot -New $newRepoRoot -Label "internal runner repo-root overlay"
$oldRunnerBinding = '$runner = Need-File -Path (Join-Path $repoRoot "run-pbr-ab-physical-review.ps1") -Label "strict PBR A/B runner"'
$newRunnerBinding = '$runner = Need-File -Path ([Environment]::GetEnvironmentVariable("BODYRIG_RESCUE_STRICT_RUNNER","Process")) -Label "strict PBR A/B runner"'
$internalText = Replace-ExactOnce -Text $internalText -Old $oldRunnerBinding -New $newRunnerBinding -Label "internal strict-runner overlay binding"

$oldInternalBinding = '$internal = Need-File -Path (Join-Path $RepoRoot "run-pbr-ab-from-body-job-internal.ps1") -Label "baseline internal PBR runner"'
$newInternalBinding = '$internal = Need-File -Path ([Environment]::GetEnvironmentVariable("BODYRIG_RESCUE_INTERNAL","Process")) -Label "baseline internal PBR runner"'
$launcherText = Replace-ExactOnce -Text $launcherText -Old $oldInternalBinding -New $newInternalBinding -Label "launcher internal-runner overlay binding"

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

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0,8)
    $OutputDir = Join-Path $env:LOCALAPPDATA "BodyRig\pbr-ab-body-job\$BaselineJobId-$stamp-$suffix"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "PBR A/B output already exists: $OutputDir" }

$tempRoot = Join-Path $env:TEMP ("bodyrig-pbr-strict-fetch-rescue-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$strictTemp = Join-Path $tempRoot "run-pbr-ab-physical-review.rescue.ps1"
$internalTemp = Join-Path $tempRoot "run-pbr-ab-from-body-job-internal.rescue.ps1"
$launcherTemp = Join-Path $tempRoot "rescue-pbr-ab-after-splat-bug.overlay.ps1"
$strictText | Set-Content -LiteralPath $strictTemp -Encoding UTF8
$internalText | Set-Content -LiteralPath $internalTemp -Encoding UTF8
$launcherText | Set-Content -LiteralPath $launcherTemp -Encoding UTF8

$oldRepoEnv = [Environment]::GetEnvironmentVariable("BODYRIG_RESCUE_REPO_ROOT","Process")
$oldStrictEnv = [Environment]::GetEnvironmentVariable("BODYRIG_RESCUE_STRICT_RUNNER","Process")
$oldInternalEnv = [Environment]::GetEnvironmentVariable("BODYRIG_RESCUE_INTERNAL","Process")
try {
    [Environment]::SetEnvironmentVariable("BODYRIG_RESCUE_REPO_ROOT",$RepoRoot,"Process")
    [Environment]::SetEnvironmentVariable("BODYRIG_RESCUE_STRICT_RUNNER",$strictTemp,"Process")
    [Environment]::SetEnvironmentVariable("BODYRIG_RESCUE_INTERNAL",$internalTemp,"Process")

    Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision
    $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($null -eq $pwsh) { throw "pwsh executable not found." }
    $args = @(
        "-NoProfile","-ExecutionPolicy","Bypass","-File",$launcherTemp,
        "-BaselineJobId",$BaselineJobId,
        "-RepoRoot",$RepoRoot,
        "-OperatorPatchRevision",$CanonicalLauncherRescueRevision,
        "-OutputDir",$OutputDir,
        "-BodyRigPython",$BodyRigPython
    )
    if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $args += @("-RigSetupReport",$RigSetupReport) }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $args += @("-UnityExe",$UnityExe) }

    Write-Host "BodyRig strict-fetch rescue: VERIFIED"
    Write-Host "Baseline job:       $BaselineJobId"
    Write-Host "Baseline revision:  $mainRevision"
    Write-Host "Strict runner blob: $strictBlob"
    Write-Host "Overlay:            temp-only; checkout remains untouched"
    Write-Host "Run output:         $OutputDir"
    & $pwsh.Source @args
    if ($LASTEXITCODE -ne 0) { throw "Overlay launcher rescue failed with exit code $LASTEXITCODE" }

    Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision
    $runAuthorityPath = Need-File -Path (Join-Path $OutputDir "run-authority.json") -Label "PBR run authority"
    $sourceAuthorityPath = Need-File -Path (Join-Path $OutputDir "body-job-source-authority.json") -Label "PBR source authority"
    $planAuthorityPath = Need-File -Path (Join-Path $OutputDir "body-job-plan-authority.json") -Label "PBR plan authority"
    $launcherAuthorityPath = Need-File -Path (Join-Path $OutputDir "launcher-rescue-authority.json") -Label "launcher rescue authority"
    [void](Need-File -Path (Join-Path $OutputDir "review.html") -Label "PBR human review page")
    [void](Need-File -Path (Join-Path $OutputDir "REVIEW-NEXT.txt") -Label "PBR plan-bound review command")

    $strictAuthorityPath = Join-Path $OutputDir "strict-fetch-rescue-authority.json"
    $strictAuthority = [ordered]@{
        format = "bodyrig-pbr-strict-fetch-binding-rescue-authority"
        version = 1
        reason = "strict-pbr-runner-array-concatenation-outside-arguments-parameter-binding"
        baseline_job_id = $BaselineJobId
        baseline_revision = $mainRevision
        strict_runner_original_blob = $strictBlob
        internal_runner_original_blob = $internalBlob
        launcher_rescue_revision = $CanonicalLauncherRescueRevision
        launcher_rescue_blob = $launcherBlob
        initial_fetch_binding_repaired = $true
        terminal_fetch_binding_repaired = $true
        repo_checkout_mutated = $false
        fidelity_mirror_repair_authority_sha256 = $repairAuthoritySha
        run_authority_sha256 = (Get-FileHash -LiteralPath $runAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
        source_authority_sha256 = (Get-FileHash -LiteralPath $sourceAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
        plan_authority_sha256 = (Get-FileHash -LiteralPath $planAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
        launcher_rescue_authority_sha256 = (Get-FileHash -LiteralPath $launcherAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
        comparison_only = $true
        human_visual_authority_required = $true
        physical_acceptance_authority = $false
        promotion_authority = $false
        production_activation = $false
    }
    Write-CreateOnlyJson -Path $strictAuthorityPath -Value $strictAuthority

    Write-Host ""
    Write-Host "BodyRig strict-fetch rescue: READY FOR EXPLICIT HUMAN REVIEW"
    Write-Host "Review page:        $(Join-Path $OutputDir 'review.html')"
    Write-Host "Review command:     $(Join-Path $OutputDir 'REVIEW-NEXT.txt')"
    Write-Host "Rescue authority:   $strictAuthorityPath"
    Write-Host "Authority: comparison-only; no physical acceptance, promotion or production activation."
} finally {
    if ($null -eq $oldRepoEnv) { [Environment]::SetEnvironmentVariable("BODYRIG_RESCUE_REPO_ROOT",$null,"Process") } else { [Environment]::SetEnvironmentVariable("BODYRIG_RESCUE_REPO_ROOT",$oldRepoEnv,"Process") }
    if ($null -eq $oldStrictEnv) { [Environment]::SetEnvironmentVariable("BODYRIG_RESCUE_STRICT_RUNNER",$null,"Process") } else { [Environment]::SetEnvironmentVariable("BODYRIG_RESCUE_STRICT_RUNNER",$oldStrictEnv,"Process") }
    if ($null -eq $oldInternalEnv) { [Environment]::SetEnvironmentVariable("BODYRIG_RESCUE_INTERNAL",$null,"Process") } else { [Environment]::SetEnvironmentVariable("BODYRIG_RESCUE_INTERNAL",$oldInternalEnv,"Process") }
    if (Test-Path -LiteralPath $tempRoot -PathType Container) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}

exit 0
