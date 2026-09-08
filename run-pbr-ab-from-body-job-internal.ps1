param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [string]$RigSetupReport = "",
    [ValidatePattern('^[A-Za-z0-9._/-]{1,200}$')]
    [string]$CandidateRef = "candidate/skin-pbr-v2-current-main-20260908",
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$UnityExe = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    $valueNormalized = $Value.Trim().ToLowerInvariant()
    if ($valueNormalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical Git revision: $Value" }
    return $valueNormalized
}

function Invoke-Git {
    param([Parameter(Mandatory = $true)][object[]]$Arguments, [Parameter(Mandatory = $true)][string]$Step)
    $raw = @(& git @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "$Step failed: $($raw -join ' ')" }
    return @($raw)
}

function Assert-CleanMain {
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [Parameter(Mandatory = $true)][string]$ExpectedRevision)
    $branch = ((Invoke-Git -Arguments @("-C", $RepoRoot, "branch", "--show-current") -Step "Resolve current branch") -join "").Trim()
    if ($branch -ne "main") { throw "PBR body-job reuse must be launched from the canonical main branch." }
    $head = Need-Revision -Value (((Invoke-Git -Arguments @("-C", $RepoRoot, "rev-parse", "HEAD") -Step "Resolve current HEAD") -join "")) -Label "current HEAD"
    if ($head -ne $ExpectedRevision) { throw "BodyRig HEAD changed during body-job PBR preparation." }
    $dirty = @(Invoke-Git -Arguments @("-C", $RepoRoot, "status", "--porcelain") -Step "Verify checkout cleanliness")
    if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; body-job PBR reuse requires exact clean authority." }
}

function Invoke-SourceProbe {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$JobId,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision
    )
    $oldPythonPath = [string]$env:PYTHONPATH
    $oldNoBytecode = [string]$env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" })
        $env:PYTHONDONTWRITEBYTECODE = "1"
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.pbr_ab_body_job_source as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound PBR body-job source validator." }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\pbr_ab_body_job_source.py"))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
            throw "PBR body-job source validator imported from wrong checkout: $actualModule"
        }
        $raw = @(& $Python -m bodyrig.pbr_ab_body_job_source --job-id $JobId --repo-root $RepoRoot --expected-revision $ExpectedRevision 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "PBR body-job source validation failed: $($raw -join ' ')" }
        try { return ([string]$raw[0]) | ConvertFrom-Json }
        catch { throw "PBR body-job source validator returned unreadable JSON." }
    }
    finally {
        if ([string]::IsNullOrEmpty($oldPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
        if ([string]::IsNullOrEmpty($oldNoBytecode)) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode }
    }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite body-job source authority: $Path" }
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

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig body-job PBR A/B reuse is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required."
}
if ($CandidateRef.Contains("..") -or $CandidateRef.StartsWith("-") -or $CandidateRef.Contains("@{")) {
    throw "CandidateRef is unsafe."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Need-Revision -Value (((Invoke-Git -Arguments @("-C", $repoRoot, "rev-parse", "HEAD") -Step "Resolve BodyRig HEAD") -join "")) -Label "BodyRig HEAD"
Assert-CleanMain -RepoRoot $repoRoot -ExpectedRevision $head

$fetchMain = "+refs/heads/main:refs/remotes/origin/main"
[void](Invoke-Git -Arguments @("-C", $repoRoot, "fetch", "--no-tags", "origin", $fetchMain) -Step "Fetch current origin/main")
$originMain = Need-Revision -Value (((Invoke-Git -Arguments @("-C", $repoRoot, "rev-parse", "refs/remotes/origin/main") -Step "Resolve origin/main") -join "")) -Label "origin/main"
if ($originMain -ne $head) { throw "Local main is not exact current origin/main: local=$head, origin=$originMain" }

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

$sourceBefore = Invoke-SourceProbe -RepoRoot $repoRoot -Python $BodyRigPython -JobId $BaselineJobId -ExpectedRevision $head
if ([string]$sourceBefore.format -ne "bodyrig-pbr-ab-body-job-source" -or [int]$sourceBefore.version -ne 1 -or $sourceBefore.safe_source_lineage_passed -ne $true) {
    throw "Body-job source validator did not return canonical safe-source authority."
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required for default PBR A/B output." }
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $OutputDir = Join-Path $env:LOCALAPPDATA "BodyRig\pbr-ab-body-job\$BaselineJobId-$stamp-$suffix"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "PBR A/B output already exists: $OutputDir" }

$runner = Need-File -Path (Join-Path $repoRoot "run-pbr-ab-physical-review.ps1") -Label "strict PBR A/B runner"
$pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwsh) { throw "pwsh executable not found." }
$runnerArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner,
    "-BaselineCloneOutput", [string]$sourceBefore.baseline_clone_output,
    "-IdentityWorkspace", [string]$sourceBefore.identity_workspace,
    "-CandidateRef", $CandidateRef,
    "-OutputDir", $OutputDir,
    "-BodyRigPython", $BodyRigPython
)
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $runnerArgs += @("-RigSetupReport", $RigSetupReport) }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $runnerArgs += @("-UnityExe", $UnityExe) }

& $pwsh.Source @runnerArgs
if ($LASTEXITCODE -ne 0) { throw "Strict PBR A/B runner failed with exit code $LASTEXITCODE" }

Assert-CleanMain -RepoRoot $repoRoot -ExpectedRevision $head
$sourceAfter = Invoke-SourceProbe -RepoRoot $repoRoot -Python $BodyRigPython -JobId $BaselineJobId -ExpectedRevision $head
foreach ($field in @(
    "body_job_id",
    "person_id",
    "bodyrig_revision",
    "safe_source_floor_revision",
    "job_json_sha256",
    "producer_log_sha256",
    "reconstruction_sha256",
    "reconstruction_authority_sha256",
    "source_policy_sha256"
)) {
    if ([string]$sourceAfter.$field -ne [string]$sourceBefore.$field) {
        throw "Retained body-job source authority changed during PBR A/B run: $field"
    }
}

$runAuthority = Need-File -Path (Join-Path $OutputDir "run-authority.json") -Label "PBR A/B run authority"
$sourceAuthorityPath = Join-Path $OutputDir "body-job-source-authority.json"
$sourceAuthority = [ordered]@{
    format = "bodyrig-pbr-ab-body-job-source-authority"
    version = 1
    source_mode = "revision-bound-succeeded-body-build"
    body_job_id = [string]$sourceBefore.body_job_id
    person_id = [string]$sourceBefore.person_id
    bodyrig_revision = [string]$sourceBefore.bodyrig_revision
    safe_source_floor_revision = [string]$sourceBefore.safe_source_floor_revision
    safe_source_lineage_passed = $true
    body_job_json_sha256 = [string]$sourceBefore.job_json_sha256
    producer_log_sha256 = [string]$sourceBefore.producer_log_sha256
    reconstruction_sha256 = [string]$sourceBefore.reconstruction_sha256
    reconstruction_authority_sha256 = [string]$sourceBefore.reconstruction_authority_sha256
    source_policy_sha256 = [string]$sourceBefore.source_policy_sha256
    pbr_run_authority_sha256 = (Get-FileHash -LiteralPath $runAuthority -Algorithm SHA256).Hash.ToLowerInvariant()
    comparison_only = $true
    human_visual_authority_required = $true
    physical_acceptance_authority = $false
    production_activation = $false
}
Write-CreateOnlyJson -Path $sourceAuthorityPath -Value $sourceAuthority

Write-Host "BodyRig PBR A/B from retained body job: READY FOR HUMAN REVIEW"
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "BodyRig revision:   $head"
Write-Host "Safe-source floor:  $([string]$sourceBefore.safe_source_floor_revision)"
Write-Host "Run output:         $OutputDir"
Write-Host "Source authority:   $sourceAuthorityPath"
Write-Host "Review:             $(Join-Path $OutputDir 'review.html')"
Write-Host "Authority: comparison-only; human review required; no production activation."
