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

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
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

function Require-ComparisonBoundary {
    param([Parameter(Mandatory = $true)]$Value,[Parameter(Mandatory = $true)][string]$Label)
    if (
        $Value.comparison_only -ne $true -or
        $Value.human_visual_authority_required -ne $true -or
        $Value.physical_acceptance_authority -ne $false -or
        $Value.promotion_authority -ne $false -or
        $Value.production_activation -ne $false
    ) { throw "$Label crossed the comparison-only authority boundary." }
}

function Invoke-ReceiptProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$JobId,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$ExpectedPersonId,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldNoBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
    try {
        $boundPythonPath = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" }
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $boundPythonPath, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.body_job_receipt_authority as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not resolve checkout-bound $Label validator." }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\body_job_receipt_authority.py"))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
            throw "$Label validator imported BodyRig from a different checkout: $actualModule"
        }
        $raw = @(& $Python -m bodyrig.body_job_receipt_authority --job-id $JobId --expected-revision $ExpectedRevision --expected-person-id $ExpectedPersonId 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "$Label validation failed: $($raw -join ' ')" }
        try { $value = ([string]$raw[0]) | ConvertFrom-Json -Depth 40 }
        catch { throw "$Label validator returned unreadable JSON." }
        if ([string]$value.format -ne "bodyrig-succeeded-body-job-receipt-authority" -or [int]$value.version -ne 1) {
            throw "$Label validator returned wrong format/version."
        }
        Require-ComparisonBoundary -Value $value -Label $Label
        return $value
    }
    finally {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $oldNoBytecode, "Process")
    }
}

function Assert-ReceiptMatchesContinuation {
    param(
        [Parameter(Mandatory = $true)]$Probe,
        [Parameter(Mandatory = $true)]$Authority,
        [Parameter(Mandatory = $true)][ValidateSet("baseline", "candidate")][string]$Role
    )
    $map = if ($Role -eq "baseline") {
        @{
            body_job_id = "baseline_job_id"
            bodyrig_revision = "baseline_bodyrig_revision"
            body_revision = "baseline_body_revision"
            canonical_body_id = "baseline_canonical_body_id"
            job_json_sha256 = "baseline_job_json_sha256"
            source_binding_sha256 = "baseline_source_binding_sha256"
            body_review_sha256 = "baseline_body_review_sha256"
        }
    } else {
        @{
            body_job_id = "candidate_job_id"
            bodyrig_revision = "throughput_candidate_revision"
            body_revision = "candidate_body_revision"
            canonical_body_id = "candidate_canonical_body_id"
            job_json_sha256 = "candidate_job_json_sha256"
            source_binding_sha256 = "candidate_source_binding_sha256"
            body_review_sha256 = "candidate_body_review_sha256"
        }
    }
    foreach ($entry in $map.GetEnumerator()) {
        $property = $Authority.PSObject.Properties[$entry.Value]
        if ($null -eq $property -or [string]$Probe.($entry.Key) -ne [string]$property.Value) {
            throw "$Role body-job receipt authority no longer matches continuation authority: $($entry.Key)"
        }
    }
    foreach ($field in @("person_id", "source_evidence_kind", "source_evidence_sha256", "source_files_sha256")) {
        $property = $Authority.PSObject.Properties[$field]
        if ($null -eq $property -or [string]$Probe.$field -ne [string]$property.Value) {
            throw "$Role body-job receipt authority no longer matches shared continuation authority: $field"
        }
    }
}

function Assert-CheckoutAndRefs {
    param(
        [Parameter(Mandatory = $true)][string]$CandidateRef,
        [Parameter(Mandatory = $true)][string]$MainRevision,
        [Parameter(Mandatory = $true)][string]$CandidateRevision
    )
    $branchRaw = @(& git -C $RepoRoot branch --show-current 2>&1)
    if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne $CandidateRef) {
        throw "Plan-bound throughput human review must run from candidate branch $CandidateRef."
    }
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve candidate checkout HEAD." }
    $head = Need-Revision -Value ([string]$headRaw[0]) -Label "candidate checkout HEAD"
    if ($head -ne $CandidateRevision) { throw "Candidate checkout HEAD no longer matches continuation authority." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Plan-bound throughput human review requires an exact clean candidate checkout." }

    $fetchMain = "+refs/heads/main:refs/remotes/origin/main"
    $fetchCandidate = "+refs/heads/${CandidateRef}:refs/remotes/origin/${CandidateRef}"
    $fetchRaw = @(& git -C $RepoRoot fetch --no-tags origin $fetchMain $fetchCandidate 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not refresh plan-bound refs during human review: $($fetchRaw -join ' ')" }
    $mainRaw = @(& git -C $RepoRoot rev-parse refs/remotes/origin/main 2>&1)
    $candidateRaw = @(& git -C $RepoRoot rev-parse "refs/remotes/origin/$CandidateRef" 2>&1)
    if ($mainRaw.Count -ne 1 -or $candidateRaw.Count -ne 1) { throw "Could not resolve plan-bound remote refs during human review." }
    if ((Need-Revision -Value ([string]$mainRaw[0]) -Label "origin/main") -ne $MainRevision) {
        throw "origin/main moved after throughput continuation authority was created."
    }
    if ((Need-Revision -Value ([string]$candidateRaw[0]) -Label "origin throughput candidate") -ne $CandidateRevision) {
        throw "Throughput candidate ref moved after continuation authority was created."
    }
}

function Invoke-HumanReviewVerify {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$ReviewPath,
        [Parameter(Mandatory = $true)][string]$BundleDir
    )
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldNoBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
    try {
        $boundPythonPath = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" }
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $boundPythonPath, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")
        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.recovery_throughput_human_review as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not resolve checkout-bound throughput human-review verifier." }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\recovery_throughput_human_review.py"))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Throughput human review verifier imported BodyRig from a different checkout: $actualModule"
        }
        $code = "import json,sys; from bodyrig.recovery_throughput_human_review import verify_review; print(json.dumps(verify_review(sys.argv[1],bundle_dir=sys.argv[2]),sort_keys=True,separators=(',',':'),allow_nan=False))"
        $raw = @(& $Python -c $code $ReviewPath $BundleDir 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "Throughput human review verification failed: $($raw -join ' ')" }
        try { return (([string]$raw[0]) | ConvertFrom-Json -Depth 40) }
        catch { throw "Throughput human review verifier returned unreadable JSON." }
    }
    finally {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $oldNoBytecode, "Process")
    }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite plan-bound throughput human-review authority: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig plan-bound throughput human review is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required for A/B plan authority." }
if (-not $ConfirmVisualReview) { throw "Pass -ConfirmVisualReview only after visually comparing all four canonical baseline/candidate views." }
if ([string]::IsNullOrWhiteSpace($Note) -or $Note.Trim() -match '^<[^>]+>$') { throw "Note must contain the operator's actual visual A/B assessment." }
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) { throw "RepoRoot is not a BodyRig Git checkout: $RepoRoot" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git is required for plan-bound throughput human-review authority." }
$pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwsh) { throw "pwsh is required to isolate the candidate-owned human review recorder." }
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

$RunDir = Need-Directory -Path $RunDir -Label "plan-bound throughput continuation directory"
$continuationPath = Need-File -Path (Join-Path $RunDir "continuation-authority.json") -Label "throughput continuation authority"
$machinePath = Need-File -Path (Join-Path $RunDir "machine-audit.json") -Label "throughput machine A/B audit"
$bundleDir = Need-Directory -Path (Join-Path $RunDir "review-bundle") -Label "immutable throughput review bundle"
$bundleReceiptPath = Need-File -Path (Join-Path $bundleDir "review-bundle.json") -Label "immutable throughput review bundle receipt"
$bundleMachinePath = Need-File -Path (Join-Path $bundleDir "machine-audit.json") -Label "bundle machine A/B audit"
$humanScript = Need-File -Path (Join-Path $RepoRoot "record-recovery-throughput-human-review.ps1") -Label "candidate-owned throughput human review recorder"
$contractPath = Need-File -Path (Join-Path $RepoRoot "contracts\ab-baseline-candidates-v1.json") -Label "candidate byte contract"

$continuation = Read-Json -Path $continuationPath -Label "throughput continuation authority"
if ([string]$continuation.format -ne "bodyrig-throughput-plan-bound-review-continuation" -or [int]$continuation.version -ne 1) {
    throw "Throughput continuation authority format/version mismatch."
}
Require-ComparisonBoundary -Value $continuation -Label "throughput continuation authority"
if ([string]$continuation.baseline_job_id -ne $BaselineJobId -or [string]$continuation.candidate_job_id -ne $CandidateJobId) {
    throw "Throughput continuation authority does not match selected jobs."
}
if ($continuation.source_manifest_parity_verified -ne $true -or $continuation.source_file_hashes_parity_verified -ne $true) {
    throw "Throughput continuation authority does not prove exact source parity."
}
$personId = [string]$continuation.person_id
if ($personId -notmatch '^person-[0-9a-f]{32}$') { throw "Throughput continuation authority has invalid Person identity." }
$mainRevision = Need-Revision -Value ([string]$continuation.baseline_bodyrig_revision) -Label "continuation baseline revision"
$throughputRevision = Need-Revision -Value ([string]$continuation.throughput_candidate_revision) -Label "continuation candidate revision"
$throughputRef = [string]$continuation.throughput_candidate_ref
if ([string]::IsNullOrWhiteSpace($throughputRef)) { throw "Throughput continuation authority has no candidate ref." }
$contractSha = Need-Sha256 -Value ([string]$continuation.candidate_contract_sha256) -Label "continuation candidate contract SHA"
$sourceManifestSha = Need-Sha256 -Value ([string]$continuation.source_evidence_sha256) -Label "continuation source manifest SHA"
$sourceFilesSha = Need-Sha256 -Value ([string]$continuation.source_files_sha256) -Label "continuation source-file hash-list SHA"
$continuationSha = File-Sha256 -Path $continuationPath

$sharedPlanPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId.json") -Label "shared A/B baseline plan"
$runPlanPath = Need-File -Path (Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans\$BaselineJobId-throughput-$CandidateJobId.json") -Label "throughput candidate run plan"
$sharedPlan = Read-Json -Path $sharedPlanPath -Label "shared A/B baseline plan"
$runPlan = Read-Json -Path $runPlanPath -Label "throughput candidate run plan"
$sharedPlanSha = File-Sha256 -Path $sharedPlanPath
$runPlanSha = File-Sha256 -Path $runPlanPath
if ([string]$sharedPlan.format -ne "bodyrig-dual-candidate-ab-baseline-plan" -or [int]$sharedPlan.version -ne 1) { throw "Shared A/B baseline plan format/version mismatch." }
if ([string]$runPlan.format -ne "bodyrig-throughput-candidate-run-plan" -or [int]$runPlan.version -ne 1) { throw "Throughput candidate run plan format/version mismatch." }
Require-ComparisonBoundary -Value $sharedPlan -Label "shared A/B baseline plan"
Require-ComparisonBoundary -Value $runPlan -Label "throughput candidate run plan"
if (
    [string]$continuation.baseline_plan_sha256 -ne $sharedPlanSha -or
    [string]$continuation.candidate_run_plan_sha256 -ne $runPlanSha -or
    [string]$sharedPlan.baseline_job_id -ne $BaselineJobId -or
    [string]$sharedPlan.person_id -ne $personId -or
    (Need-Revision -Value ([string]$sharedPlan.baseline_bodyrig_revision) -Label "shared plan baseline revision") -ne $mainRevision -or
    [string]$sharedPlan.throughput_candidate.ref -ne $throughputRef -or
    (Need-Revision -Value ([string]$sharedPlan.throughput_candidate.revision) -Label "shared plan throughput revision") -ne $throughputRevision -or
    [string]$runPlan.baseline_job_id -ne $BaselineJobId -or
    [string]$runPlan.candidate_job_id -ne $CandidateJobId -or
    [string]$runPlan.person_id -ne $personId -or
    [string]$runPlan.throughput_candidate_ref -ne $throughputRef -or
    (Need-Revision -Value ([string]$runPlan.throughput_candidate_revision) -Label "run plan throughput revision") -ne $throughputRevision
) { throw "Plan-bound throughput human review plans do not match continuation authority." }
if ((File-Sha256 -Path $contractPath) -ne $contractSha) { throw "Candidate byte contract changed after continuation authority was created." }

$machineSha = File-Sha256 -Path $machinePath
$bundleReceiptSha = File-Sha256 -Path $bundleReceiptPath
if ((Need-Sha256 -Value ([string]$continuation.machine_audit_sha256) -Label "continuation machine-audit SHA") -ne $machineSha) {
    throw "Throughput root machine audit changed after continuation authority was created."
}
if ((Need-Sha256 -Value ([string]$continuation.review_bundle_receipt_sha256) -Label "continuation bundle receipt SHA") -ne $bundleReceiptSha) {
    throw "Throughput review-bundle receipt changed after continuation authority was created."
}
if ((File-Sha256 -Path $bundleMachinePath) -ne $machineSha) {
    throw "Human review bundle machine-audit bytes do not match the machine audit bound by continuation authority."
}

Assert-CheckoutAndRefs -CandidateRef $throughputRef -MainRevision $mainRevision -CandidateRevision $throughputRevision
$baselineProbe = Invoke-ReceiptProbe -Python $BodyRigPython -JobId $BaselineJobId -ExpectedRevision $mainRevision -ExpectedPersonId $personId -Label "baseline body-job receipt authority at human review"
$candidateProbe = Invoke-ReceiptProbe -Python $BodyRigPython -JobId $CandidateJobId -ExpectedRevision $throughputRevision -ExpectedPersonId $personId -Label "candidate body-job receipt authority at human review"
Assert-ReceiptMatchesContinuation -Probe $baselineProbe -Authority $continuation -Role baseline
Assert-ReceiptMatchesContinuation -Probe $candidateProbe -Authority $continuation -Role candidate
if ([string]$baselineProbe.source_evidence_sha256 -ne $sourceManifestSha -or [string]$candidateProbe.source_evidence_sha256 -ne $sourceManifestSha -or [string]$baselineProbe.source_files_sha256 -ne $sourceFilesSha -or [string]$candidateProbe.source_files_sha256 -ne $sourceFilesSha) {
    throw "Shared source authority no longer matches continuation authority."
}

if ([string]::IsNullOrWhiteSpace($Out)) { $Out = "$RunDir.human-review.json" }
$humanReviewPath = [IO.Path]::GetFullPath($Out)
$humanAuthorityPath = "$RunDir.plan-bound-human-review-authority.json"
if (Test-Path -LiteralPath $humanReviewPath) { throw "Human throughput A/B review already exists: $humanReviewPath" }
if (Test-Path -LiteralPath $humanAuthorityPath) { throw "Plan-bound throughput human-review authority already exists: $humanAuthorityPath" }

$stablePaths = @($continuationPath, $sharedPlanPath, $runPlanPath, $contractPath, $machinePath, $bundleReceiptPath, $bundleMachinePath)
$stableHashes = @{}
foreach ($path in $stablePaths) { $stableHashes[$path] = File-Sha256 -Path $path }

$childArgs = @(
    "-NoLogo", "-NoProfile", "-File", $humanScript,
    "-BundleDir", $bundleDir,
    "-IdentityShape", $IdentityShape,
    "-FaceIdentity", $FaceIdentity,
    "-SkinTextureAlignment", $SkinTextureAlignment,
    "-GrossAnatomy", $GrossAnatomy,
    "-Note", $Note.Trim(),
    "-Out", $humanReviewPath,
    "-RepoRoot", $RepoRoot
)
if (-not [string]::IsNullOrWhiteSpace($Reviewer)) { $childArgs += @("-Reviewer", $Reviewer.Trim()) }

try {
    & $pwsh.Source @childArgs
    if ($LASTEXITCODE -ne 0) { throw "Candidate-owned throughput human review recorder failed with exit code $LASTEXITCODE." }
    [void](Need-File -Path $humanReviewPath -Label "throughput human review receipt")
    $review = Invoke-HumanReviewVerify -Python $BodyRigPython -ReviewPath $humanReviewPath -BundleDir $bundleDir

    if (
        [string]$review.person_id -ne $personId -or
        [string]$review.baseline_job_id -ne $BaselineJobId -or
        [string]$review.candidate_job_id -ne $CandidateJobId -or
        (Need-Revision -Value ([string]$review.baseline_bodyrig_revision) -Label "human review baseline revision") -ne $mainRevision -or
        (Need-Revision -Value ([string]$review.candidate_bodyrig_revision) -Label "human review candidate revision") -ne $throughputRevision -or
        $review.human_visual_review_completed -ne $true -or
        $review.promotion_authority -ne $false -or $review.production_activation -ne $false
    ) { throw "Human review receipt did not preserve exact plan-bound throughput authority." }

    Assert-CheckoutAndRefs -CandidateRef $throughputRef -MainRevision $mainRevision -CandidateRevision $throughputRevision
    $baselineAfter = Invoke-ReceiptProbe -Python $BodyRigPython -JobId $BaselineJobId -ExpectedRevision $mainRevision -ExpectedPersonId $personId -Label "post-human baseline body-job receipt authority"
    $candidateAfter = Invoke-ReceiptProbe -Python $BodyRigPython -JobId $CandidateJobId -ExpectedRevision $throughputRevision -ExpectedPersonId $personId -Label "post-human candidate body-job receipt authority"
    Assert-ReceiptMatchesContinuation -Probe $baselineAfter -Authority $continuation -Role baseline
    Assert-ReceiptMatchesContinuation -Probe $candidateAfter -Authority $continuation -Role candidate
    foreach ($path in $stablePaths) {
        if ((File-Sha256 -Path $path) -ne [string]$stableHashes[$path]) { throw "Plan-bound throughput evidence changed during human review: $path" }
    }
    $review = Invoke-HumanReviewVerify -Python $BodyRigPython -ReviewPath $humanReviewPath -BundleDir $bundleDir
} catch {
    if (Test-Path -LiteralPath $humanReviewPath -PathType Leaf) { Remove-Item -LiteralPath $humanReviewPath -Force -ErrorAction SilentlyContinue }
    throw "Plan-bound throughput human review failed closed; removed non-authoritative human receipt when present: $($_.Exception.Message)"
}

$authority = [ordered]@{
    format = "bodyrig-throughput-plan-bound-human-review-authority"
    version = 1
    baseline_job_id = $BaselineJobId
    candidate_job_id = $CandidateJobId
    person_id = $personId
    baseline_plan_sha256 = $sharedPlanSha
    candidate_run_plan_sha256 = $runPlanSha
    continuation_authority_sha256 = $continuationSha
    candidate_contract_sha256 = $contractSha
    baseline_bodyrig_revision = $mainRevision
    throughput_candidate_ref = $throughputRef
    throughput_candidate_revision = $throughputRevision
    baseline_source_binding_sha256 = [string]$continuation.baseline_source_binding_sha256
    candidate_source_binding_sha256 = [string]$continuation.candidate_source_binding_sha256
    baseline_body_review_sha256 = [string]$continuation.baseline_body_review_sha256
    candidate_body_review_sha256 = [string]$continuation.candidate_body_review_sha256
    source_evidence_sha256 = $sourceManifestSha
    source_files_sha256 = $sourceFilesSha
    machine_audit_sha256 = $machineSha
    review_bundle_receipt_sha256 = $bundleReceiptSha
    human_review_sha256 = File-Sha256 -Path $humanReviewPath
    human_visual_review_completed = $true
    human_visual_review_passed = [bool]$review.human_visual_review_passed
    decision = [string]$review.decision
    next_gate = [string]$review.next_gate
    comparison_only = $true
    human_visual_authority_recorded = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}

try {
    Write-CreateOnlyJson -Path $humanAuthorityPath -Value $authority
    Assert-CheckoutAndRefs -CandidateRef $throughputRef -MainRevision $mainRevision -CandidateRevision $throughputRevision
    foreach ($path in $stablePaths) {
        if ((File-Sha256 -Path $path) -ne [string]$stableHashes[$path]) { throw "Plan-bound throughput evidence changed before terminal human-review authority publication: $path" }
    }
    if ((File-Sha256 -Path $continuationPath) -ne $continuationSha) { throw "Continuation authority changed before terminal human-review authority publication." }
    if ((File-Sha256 -Path $humanReviewPath) -ne [string]$authority.human_review_sha256) { throw "Human review receipt changed before terminal authority publication." }
    $baselineTerminal = Invoke-ReceiptProbe -Python $BodyRigPython -JobId $BaselineJobId -ExpectedRevision $mainRevision -ExpectedPersonId $personId -Label "terminal baseline body-job receipt authority"
    $candidateTerminal = Invoke-ReceiptProbe -Python $BodyRigPython -JobId $CandidateJobId -ExpectedRevision $throughputRevision -ExpectedPersonId $personId -Label "terminal candidate body-job receipt authority"
    Assert-ReceiptMatchesContinuation -Probe $baselineTerminal -Authority $continuation -Role baseline
    Assert-ReceiptMatchesContinuation -Probe $candidateTerminal -Authority $continuation -Role candidate
    [void](Invoke-HumanReviewVerify -Python $BodyRigPython -ReviewPath $humanReviewPath -BundleDir $bundleDir)
} catch {
    if (Test-Path -LiteralPath $humanAuthorityPath -PathType Leaf) { Remove-Item -LiteralPath $humanAuthorityPath -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $humanReviewPath -PathType Leaf) { Remove-Item -LiteralPath $humanReviewPath -Force -ErrorAction SilentlyContinue }
    throw
}

Write-Host "BodyRig plan-bound throughput human review: RECORDED"
Write-Host "Baseline job:   $BaselineJobId"
Write-Host "Candidate job:  $CandidateJobId"
Write-Host "Decision:       $($review.decision)"
Write-Host "Human receipt:  $humanReviewPath"
Write-Host "Plan authority: $humanAuthorityPath"
Write-Host "Authority: comparison-only human evidence; no physical acceptance, promotion or production activation."
exit 0
