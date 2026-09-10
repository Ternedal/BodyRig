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

$CanonicalLauncherRescueRevision = "73d5af8c4bdadff00d5cb3685e2e7e8bbd945d04"

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

function Assert-CleanMain {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$ExpectedRevision)
    $branch = ((Invoke-Git -Arguments @("-C",$Root,"branch","--show-current") -Step "Resolve current branch") -join "").Trim()
    if ($branch -ne "main") { throw "Fidelity-mirror rescue requires branch main." }
    $head = Need-Revision -Value (((Invoke-Git -Arguments @("-C",$Root,"rev-parse","HEAD") -Step "Resolve current HEAD") -join "")) -Label "current HEAD"
    if ($head -ne $ExpectedRevision) { throw "BodyRig HEAD does not match the shared baseline revision." }
    $dirty = @(Invoke-Git -Arguments @("-C",$Root,"status","--porcelain") -Step "Verify checkout cleanliness")
    if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; fidelity-mirror rescue requires exact clean main." }
}

function Write-Or-ValidateRepairAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Expected
    )
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $existing = Read-Json -Path $Path -Label "fidelity mirror repair authority"
        foreach ($field in @(
            "format","version","reason","job_id","person_id","bodyrig_revision","body_review_sha256",
            "fidelity_review_mirror_sha256","comparison_only","human_visual_authority_created",
            "physical_acceptance_authority","promotion_authority","production_activation"
        )) {
            if ([string]$existing.$field -ne [string]$Expected.$field) {
                throw "Existing fidelity mirror repair authority does not match this exact repair: $field"
            }
        }
        return
    }
    $parent = Split-Path -Parent $Path
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Expected | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temp -Encoding UTF8
        [IO.File]::Move($temp,$Path)
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig fidelity-mirror rescue is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$planPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId.json") -Label "shared A/B baseline plan"
$plan = Read-Json -Path $planPath -Label "shared A/B baseline plan"
if ([string]$plan.format -ne "bodyrig-dual-candidate-ab-baseline-plan" -or [int]$plan.version -ne 1 -or [string]$plan.baseline_job_id -ne $BaselineJobId) {
    throw "Shared A/B baseline plan identity/format mismatch."
}
if ($plan.comparison_only -ne $true -or $plan.human_visual_authority_required -ne $true -or $plan.physical_acceptance_authority -ne $false -or $plan.promotion_authority -ne $false -or $plan.production_activation -ne $false) {
    throw "Shared A/B baseline plan crossed the comparison-only authority boundary."
}
$mainRevision = Need-Revision -Value ([string]$plan.baseline_bodyrig_revision) -Label "baseline revision"
Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision

[void](Invoke-Git -Arguments @("-C",$RepoRoot,"fetch","--no-tags","origin","+refs/heads/main:refs/remotes/origin/main") -Step "Refresh origin/main")
$originMain = Need-Revision -Value (((Invoke-Git -Arguments @("-C",$RepoRoot,"rev-parse","refs/remotes/origin/main") -Step "Resolve origin/main") -join "")) -Label "origin/main"
if ($originMain -ne $mainRevision) { throw "origin/main moved after the shared A/B baseline plan was created." }

$jobRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "BodyRig\ui-jobs\$BaselineJobId"))
$jobPath = Need-File -Path (Join-Path $jobRoot "job.json") -Label "succeeded baseline body job"
$job = Read-Json -Path $jobPath -Label "succeeded baseline body job"
if ([string]$job.format -ne "bodyrig-ui-job" -or [int]$job.version -ne 1 -or [string]$job.kind -ne "body-build" -or [string]$job.status -ne "succeeded") {
    throw "Fidelity-mirror rescue requires the exact succeeded BodyRig body-build job."
}
if ([string]$job.job_id -ne $BaselineJobId -or [string]$job.person_id -ne [string]$plan.person_id) { throw "Baseline job identity differs from shared A/B plan." }
if ((Need-Revision -Value ([string]$job.bodyrig_revision) -Label "job BodyRig revision") -ne $mainRevision) { throw "Baseline job revision differs from shared A/B plan." }
if ([string]$job.body_revision -notmatch '^body-r[0-9]{4}$' -or [string]::IsNullOrWhiteSpace([string]$job.canonical_body_id)) { throw "Succeeded baseline job lacks canonical body identity." }
$expectedReviewSha = Need-Sha256 -Value ([string]$job.body_review_sha256) -Label "job body review SHA"

$fidelityDir = Need-Directory -Path ([string]$job.fidelity_dir) -Label "baseline fidelity directory"
$expectedFidelityDir = [IO.Path]::GetFullPath((Join-Path $jobRoot "fidelity-review"))
if (-not [string]::Equals([IO.Path]::GetFullPath($fidelityDir),$expectedFidelityDir,[StringComparison]::OrdinalIgnoreCase)) {
    throw "Baseline fidelity directory is outside the canonical job root."
}
[void](Need-File -Path (Join-Path $fidelityDir "comparison-authority.json") -Label "baseline fidelity comparison authority")
[void](Need-File -Path (Join-Path $fidelityDir "snapshots\fidelity-render-set.json") -Label "baseline fidelity render-set manifest")

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

$oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$oldNoBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
try {
    $bound = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" }
    [Environment]::SetEnvironmentVariable("PYTHONPATH",$bound,"Process")
    [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE","1","Process")
    $moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig.person_body_review as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound body-review validator." }
    $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\person_body_review.py"))
    $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
    if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) { throw "Body-review validator imported from wrong checkout: $actualModule" }

    $probeCode = @'
import json,pathlib,sys
from bodyrig.storage import person_library,ui_jobs_dir
from bodyrig.person_profiles import load_profile
from bodyrig.person_body_review import read_review,validate_fidelity_output
job_id=sys.argv[1]
job_path=(ui_jobs_dir()/job_id/'job.json').resolve()
job=json.loads(job_path.read_text(encoding='utf-8-sig'))
profile=load_profile(person_library(),str(job['person_id']))
review=read_review(person_library(),profile,body_revision=str(job['body_revision']))
receipt=(pathlib.Path(review['root'])/'review.json').resolve()
validated=validate_fidelity_output(job['fidelity_dir'],body_id=str(review['body_id']),package_sha256=str(review['package_sha256']))
print(json.dumps({'receipt_path':str(receipt),'person_id':str(review['person_id']),'body_id':str(review['body_id']),'package_sha256':str(review['package_sha256']),'bodyrig_revision':str(review['bodyrig_revision']),'validated_body_id':str(validated['body_id']),'validated_package_sha256':str(validated['package_sha256'])},sort_keys=True,separators=(',',':')))
'@
    $probeRaw = @(& $BodyRigPython -c $probeCode $BaselineJobId 2>&1)
    if ($LASTEXITCODE -ne 0 -or $probeRaw.Count -ne 1) { throw "Canonical persisted/fidelity review revalidation failed: $($probeRaw -join ' ')" }
    try { $probe = ([string]$probeRaw[0]) | ConvertFrom-Json -Depth 20 }
    catch { throw "Canonical persisted/fidelity review revalidation returned unreadable JSON." }
} finally {
    if ($null -eq $oldPythonPath) { [Environment]::SetEnvironmentVariable("PYTHONPATH",$null,"Process") } else { [Environment]::SetEnvironmentVariable("PYTHONPATH",$oldPythonPath,"Process") }
    if ($null -eq $oldNoBytecode) { [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE",$null,"Process") } else { [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE",$oldNoBytecode,"Process") }
}

if ([string]$probe.person_id -ne [string]$job.person_id -or [string]$probe.body_id -ne [string]$job.canonical_body_id -or [string]$probe.validated_body_id -ne [string]$job.canonical_body_id) {
    throw "Canonical persisted review/fidelity output no longer matches the succeeded baseline body identity."
}
if ((Need-Revision -Value ([string]$probe.bodyrig_revision) -Label "persisted review BodyRig revision") -ne $mainRevision) { throw "Persisted review belongs to a different BodyRig revision." }
if ((Need-Sha256 -Value ([string]$probe.package_sha256) -Label "persisted review package SHA") -ne (Need-Sha256 -Value ([string]$probe.validated_package_sha256) -Label "fidelity package SHA")) {
    throw "Persisted review and baseline fidelity output disagree on package bytes."
}

$canonicalReview = Need-File -Path ([string]$probe.receipt_path) -Label "canonical persisted body review receipt"
$canonicalReviewSha = (Get-FileHash -LiteralPath $canonicalReview -Algorithm SHA256).Hash.ToLowerInvariant()
if ($canonicalReviewSha -ne $expectedReviewSha) { throw "Canonical persisted body review receipt no longer matches job.body_review_sha256." }

$mirrorPath = Join-Path $fidelityDir "review.json"
if (Test-Path -LiteralPath $mirrorPath -PathType Leaf) {
    $mirrorSha = (Get-FileHash -LiteralPath $mirrorPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($mirrorSha -ne $expectedReviewSha) { throw "Existing fidelity review mirror differs from canonical persisted review; refusing overwrite." }
} else {
    $tempMirror = Join-Path $fidelityDir (".review.json." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        [IO.File]::Copy($canonicalReview,$tempMirror,$false)
        $tempSha = (Get-FileHash -LiteralPath $tempMirror -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($tempSha -ne $expectedReviewSha) { throw "Fidelity review mirror changed while copying canonical receipt." }
        [IO.File]::Move($tempMirror,$mirrorPath)
    } finally {
        if (Test-Path -LiteralPath $tempMirror -PathType Leaf) { Remove-Item -LiteralPath $tempMirror -Force }
    }
    $mirrorSha = (Get-FileHash -LiteralPath $mirrorPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($mirrorSha -ne $expectedReviewSha) { throw "Persisted fidelity review mirror does not match canonical review bytes." }
}

$repairAuthorityPath = Join-Path $fidelityDir "review-mirror-repair-authority.json"
$repairAuthority = [ordered]@{
    format = "bodyrig-fidelity-review-mirror-repair-authority"
    version = 1
    reason = "succeeded-ui-job-persisted-review-not-mirrored-to-fidelity-output"
    job_id = $BaselineJobId
    person_id = [string]$job.person_id
    bodyrig_revision = $mainRevision
    body_review_sha256 = $expectedReviewSha
    fidelity_review_mirror_sha256 = $mirrorSha
    comparison_only = $true
    human_visual_authority_created = $false
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}
Write-Or-ValidateRepairAuthority -Path $repairAuthorityPath -Expected $repairAuthority

Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision
[void](Invoke-Git -Arguments @("-C",$RepoRoot,"cat-file","-e","$CanonicalLauncherRescueRevision^{commit}") -Step "Resolve canonical launcher rescue revision")
$rescueText = @((Invoke-Git -Arguments @("-C",$RepoRoot,"show","${CanonicalLauncherRescueRevision}:rescue-pbr-ab-after-splat-bug.ps1") -Step "Read canonical launcher rescue") )
if ($rescueText.Count -lt 1) { throw "Canonical launcher rescue script is empty." }
$tempRescue = Join-Path $env:TEMP "bodyrig-pbr-launcher-rescue-$CanonicalLauncherRescueRevision.ps1"
$rescueText | Set-Content -LiteralPath $tempRescue -Encoding UTF8

$params = @{
    BaselineJobId = $BaselineJobId
    RepoRoot = $RepoRoot
    OperatorPatchRevision = $CanonicalLauncherRescueRevision
    BodyRigPython = $BodyRigPython
}
if (-not [string]::IsNullOrWhiteSpace($OutputDir)) { $params.OutputDir = $OutputDir }
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $params.RigSetupReport = $RigSetupReport }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $params.UnityExe = $UnityExe }

Write-Host "BodyRig fidelity mirror rescue: VERIFIED"
Write-Host "Baseline job:       $BaselineJobId"
Write-Host "Body review SHA:    $expectedReviewSha"
Write-Host "Mirror:             $mirrorPath"
Write-Host "Repair authority:   $repairAuthorityPath"
Write-Host "Continuing through canonical launcher rescue $CanonicalLauncherRescueRevision"
& $tempRescue @params
if ($LASTEXITCODE -ne 0) { throw "Canonical launcher rescue failed with exit code $LASTEXITCODE" }
exit 0
