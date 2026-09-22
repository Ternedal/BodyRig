param(
    [Parameter(Mandatory = $true)]
    [string]$SummaryPath,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedBodyRigRevision,
    [string]$ExpectedPerformerId = "42"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$requiredWorkflows = @(
    [pscustomobject]@{ Name = "ci"; Id = [long]340505769; Path = ".github/workflows/ci.yml" },
    [pscustomobject]@{ Name = "windows-log-handle-regression"; Id = [long]343740273; Path = ".github/workflows/windows-log-handle-regression.yml" },
    [pscustomobject]@{ Name = "loc-metrics"; Id = [long]355552908; Path = ".github/workflows/loc-metrics.yml" },
    [pscustomobject]@{ Name = "codeql"; Id = [long]354295800; Path = ".github/workflows/codeql.yml" }
)

$requiredCheckSources = @(
    [pscustomobject]@{ Name = "test (3.11)"; AppId = [long]15368 },
    [pscustomobject]@{ Name = "test (3.12)"; AppId = [long]15368 },
    [pscustomobject]@{ Name = "test-windows-python"; AppId = [long]15368 },
    [pscustomobject]@{ Name = "acceptance-windows"; AppId = [long]15368 },
    [pscustomobject]@{ Name = "adapter-log-handle"; AppId = [long]15368 },
    [pscustomobject]@{ Name = "CodeQL"; AppId = [long]57789 }
)

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is unreadable JSON: $Path" }
}

function Test-NumericExact {
    param([AllowNull()]$Value, [Parameter(Mandatory = $true)][double]$Expected)
    if ($null -eq $Value -or $Value -is [bool]) { return $false }
    try { $typeCode = [Type]::GetTypeCode($Value.GetType()) } catch { return $false }
    $numericTypes = @(
        [TypeCode]::Byte,[TypeCode]::Decimal,[TypeCode]::Double,[TypeCode]::Int16,
        [TypeCode]::Int32,[TypeCode]::Int64,[TypeCode]::SByte,[TypeCode]::Single,
        [TypeCode]::UInt16,[TypeCode]::UInt32,[TypeCode]::UInt64
    )
    if ($numericTypes -notcontains $typeCode) { return $false }
    $number = [double]$Value
    return (-not [double]::IsNaN($number)) -and (-not [double]::IsInfinity($number)) -and $number -eq $Expected
}

function Require-StrictBool {
    param([AllowNull()]$Value, [Parameter(Mandatory = $true)][bool]$Expected, [Parameter(Mandatory = $true)][string]$Label)
    if ($Value -isnot [bool] -or [bool]$Value -ne $Expected) {
        throw "$Label must be strict boolean $Expected."
    }
}

function Require-SamePath {
    param(
        [Parameter(Mandatory = $true)][string]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actualPath = [IO.Path]::GetFullPath($Actual)
    $expectedPath = [IO.Path]::GetFullPath($Expected)
    if (-not [string]::Equals($actualPath, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label path mismatch."
    }
    return $actualPath
}

function Get-VerifierProvenance {
    $relativePath = "review-tools/VERIFY_PHYSICAL_P0_READY.ps1"
    if ([string]::IsNullOrWhiteSpace([string]$PSCommandPath)) {
        throw "Readiness verifier must execute from its tracked script file."
    }
    $scriptPath = [IO.Path]::GetFullPath($PSCommandPath)

    try {
        $rootLines = @(& git -C $PSScriptRoot rev-parse --show-toplevel 2>&1)
    } catch {
        throw "Could not resolve the readiness verifier Git checkout: $($_.Exception.Message)"
    }
    if ($LASTEXITCODE -ne 0 -or $rootLines.Count -ne 1) {
        throw "Could not resolve the readiness verifier Git checkout."
    }
    $repoRoot = [IO.Path]::GetFullPath(([string]$rootLines[0]).Trim())
    $expectedScriptPath = [IO.Path]::GetFullPath((Join-Path $repoRoot $relativePath))
    if (-not [string]::Equals($scriptPath, $expectedScriptPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Readiness verifier is not executing from its tracked repository path."
    }

    $revisionLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $revisionLines.Count -ne 1) {
        throw "Could not resolve the readiness verifier Git revision."
    }
    $revision = ([string]$revisionLines[0]).Trim().ToLowerInvariant()
    if ($revision -notmatch '^[0-9a-f]{40}$') {
        throw "Readiness verifier Git revision is invalid."
    }

    $branchLines = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $branchLines.Count -ne 1 -or ([string]$branchLines[0]).Trim() -ne "main") {
        throw "Readiness verifier requires the canonical main branch."
    }
    $dirtyLines = @(& git -C $repoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirtyLines.Count -gt 0) {
        throw "Readiness verifier requires an exact clean checkout."
    }
    $originMainLines = @(& git -C $repoRoot rev-parse "refs/remotes/origin/main^{commit}" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $originMainLines.Count -ne 1) {
        throw "Readiness verifier could not resolve fetched origin/main."
    }
    $originMain = ([string]$originMainLines[0]).Trim().ToLowerInvariant()
    if ($originMain -ne $revision) {
        throw "Readiness verifier HEAD must equal fetched origin/main."
    }

    $expectedBlobLines = @(& git -C $repoRoot rev-parse "${revision}:$relativePath" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $expectedBlobLines.Count -ne 1) {
        throw "Readiness verifier is not tracked at its Git revision."
    }
    $expectedBlob = ([string]$expectedBlobLines[0]).Trim().ToLowerInvariant()
    if ($expectedBlob -notmatch '^[0-9a-f]{40}$') {
        throw "Readiness verifier tracked Git blob is invalid."
    }

    $workingBlobLines = @(& git -C $repoRoot hash-object "--path=$relativePath" $scriptPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $workingBlobLines.Count -ne 1) {
        throw "Could not hash the executing readiness verifier through Git filters."
    }
    $workingBlob = ([string]$workingBlobLines[0]).Trim().ToLowerInvariant()
    if ($workingBlob -ne $expectedBlob) {
        throw "Executing readiness verifier differs from the tracked Git blob at verifier HEAD."
    }

    $scriptSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $scriptPath).Hash.ToLowerInvariant()
    if ($scriptSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Could not bind readiness verifier SHA-256."
    }

    return [pscustomobject]@{
        Revision = $revision
        RepoRoot = $repoRoot
        RelativePath = $relativePath
        GitBlob = $expectedBlob
        ScriptSha256 = $scriptSha256
    }
}

function Test-HistoricalRevisionAncestor {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$EvidenceRevision,
        [Parameter(Mandatory = $true)][string]$VerifierRevision
    )

    if ($EvidenceRevision -eq $VerifierRevision) { return $true }
    & git -C $RepoRoot cat-file -e "$EvidenceRevision^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    & git -C $RepoRoot merge-base --is-ancestor $EvidenceRevision $VerifierRevision 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Test-HistoricalQualificationGapIsCodeQlOnly {
    param(
        [Parameter(Mandatory = $true)]$WorkflowEvidence,
        [Parameter(Mandatory = $true)]$CheckEvidence
    )

    $blockers = @($WorkflowEvidence.Blockers) + @($CheckEvidence.Blockers)
    if ($blockers.Count -eq 0) { return $false }
    foreach ($blocker in $blockers) {
        if ([string]$blocker -notmatch '(?i)codeql') { return $false }
    }
    return $true
}

function Get-GitHubHeaders {
    $headers = @{
        Accept = "application/vnd.github+json"
        "User-Agent" = "BodyRig-p0-readiness-verifier"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
        $headers.Authorization = "Bearer $($env:GITHUB_TOKEN)"
    }
    return $headers
}

function Get-ExactHeadWorkflowEvidence {
    param([Parameter(Mandatory = $true)][string]$Revision)

    $headers = Get-GitHubHeaders
    $uri = "https://api.github.com/repos/Ternedal/BodyRig/actions/runs?head_sha=$Revision&per_page=100"
    try {
        $response = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers
    } catch {
        throw "Could not query exact-head GitHub Actions evidence: $($_.Exception.Message)"
    }

    $allRuns = @($response.workflow_runs)
    $verified = [ordered]@{}
    $blockers = New-Object System.Collections.Generic.List[string]

    foreach ($required in $requiredWorkflows) {
        $name = [string]$required.Name
        $workflowId = [long]$required.Id
        $workflowPath = [string]$required.Path
        $matches = @(
            $allRuns |
                Where-Object {
                    [string]$_.head_sha -eq $Revision -and
                    [string]::Equals([string]$_.name, $name, [StringComparison]::OrdinalIgnoreCase) -and
                    [long]$_.workflow_id -eq $workflowId -and
                    [string]$_.path -eq $workflowPath
                } |
                Sort-Object -Property run_number -Descending
        )
        if ($matches.Count -eq 0) {
            $blockers.Add("missing exact-head workflow identity: $name ($workflowId, $workflowPath)")
            continue
        }

        $successful = @(
            $matches | Where-Object {
                [string]$_.status -eq "completed" -and [string]$_.conclusion -eq "success"
            }
        )
        $run = if ($successful.Count -gt 0) { $successful[0] } else { $matches[0] }
        $verified[$name] = [ordered]@{
            run_id = [long]$run.id
            workflow_id = [long]$run.workflow_id
            path = [string]$run.path
            name = [string]$run.name
            event = [string]$run.event
            status = [string]$run.status
            conclusion = [string]$run.conclusion
            head_sha = [string]$run.head_sha
            html_url = [string]$run.html_url
        }
        if ($successful.Count -eq 0) {
            $blockers.Add("workflow $name has no completed successful run for the exact head")
        }
    }

    return [pscustomobject]@{
        Verified = $verified
        Blockers = @($blockers)
    }
}

function Get-ExactHeadCheckEvidence {
    param([Parameter(Mandatory = $true)][string]$Revision)

    $headers = Get-GitHubHeaders
    $uri = "https://api.github.com/repos/Ternedal/BodyRig/commits/$Revision/check-runs?per_page=100"
    try {
        $response = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers
    } catch {
        throw "Could not query exact-head GitHub check evidence: $($_.Exception.Message)"
    }

    $allChecks = @($response.check_runs)
    $verified = [ordered]@{}
    $blockers = New-Object System.Collections.Generic.List[string]

    foreach ($required in $requiredCheckSources) {
        $name = [string]$required.Name
        $expectedAppId = [long]$required.AppId
        $matches = @(
            $allChecks |
                Where-Object {
                    [string]$_.head_sha -eq $Revision -and
                    [string]::Equals([string]$_.name, $name, [StringComparison]::Ordinal) -and
                    $null -ne $_.app -and [long]$_.app.id -eq $expectedAppId
                } |
                Sort-Object -Property id -Descending
        )
        if ($matches.Count -eq 0) {
            $blockers.Add("missing exact-head source-bound check: $name (app $expectedAppId)")
            continue
        }

        $successful = @(
            $matches | Where-Object {
                [string]$_.status -eq "completed" -and [string]$_.conclusion -eq "success"
            }
        )
        $check = if ($successful.Count -gt 0) { $successful[0] } else { $matches[0] }
        $verified[$name] = [ordered]@{
            check_run_id = [long]$check.id
            name = [string]$check.name
            app_id = [long]$check.app.id
            app_slug = [string]$check.app.slug
            status = [string]$check.status
            conclusion = [string]$check.conclusion
            head_sha = [string]$check.head_sha
            html_url = [string]$check.html_url
        }
        if ($successful.Count -eq 0) {
            $blockers.Add("check $name has no completed successful run from app $expectedAppId for the exact head")
        }
    }

    return [pscustomobject]@{
        Verified = $verified
        Blockers = @($blockers)
    }
}

$ExpectedBodyRigRevision = $ExpectedBodyRigRevision.Trim().ToLowerInvariant()
if ($ExpectedBodyRigRevision -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedBodyRigRevision must be one exact 40-character Git SHA."
}
if ([string]::IsNullOrWhiteSpace($ExpectedPerformerId)) {
    throw "ExpectedPerformerId must be non-empty."
}

$verifier = Get-VerifierProvenance
$verifierRevision = [string]$verifier.Revision
$verifierWorkflowEvidence = Get-ExactHeadWorkflowEvidence -Revision $verifierRevision
$verifierCheckEvidence = Get-ExactHeadCheckEvidence -Revision $verifierRevision
$verifierSoftwareQualified = @($verifierWorkflowEvidence.Blockers).Count -eq 0 -and @($verifierCheckEvidence.Blockers).Count -eq 0
Write-Host "verifier_bodyrig_revision=$verifierRevision"
Write-Host "verifier_software_qualification_complete=$($verifierSoftwareQualified.ToString().ToLowerInvariant())"
if (-not $verifierSoftwareQualified) {
    foreach ($blocker in @($verifierWorkflowEvidence.Blockers)) {
        Write-Host "Verifier workflow blocker: $blocker"
    }
    foreach ($blocker in @($verifierCheckEvidence.Blockers)) {
        Write-Host "Verifier check blocker: $blocker"
    }
    Write-Host "downstream_teacher_flow_ready=false"
    Write-Host "human_visual_acceptance_required=true"
    Write-Host "photoreal_acceptance_authority=false"
    Write-Host "production_activation=false"
    exit 2
}

$SummaryPath = (Resolve-Path -LiteralPath $SummaryPath).Path
$summary = Read-Json -Path $SummaryPath -Label "Photoreal overnight summary"

if ([string]$summary.format -ne "bodyrig-photoreal-v2-overnight-summary" -or -not (Test-NumericExact -Value $summary.version -Expected 1)) {
    throw "Overnight summary format/version mismatch."
}
if ([string]$summary.performer_id -ne $ExpectedPerformerId) {
    throw "Overnight summary performer mismatch."
}
if ([string]$summary.status -ne "completed" -or -not (Test-NumericExact -Value $summary.exit_code -Expected 0)) {
    throw "Overnight P0 is not a completed success."
}
if ([string]$summary.bodyrig_revision -ne $ExpectedBodyRigRevision) {
    throw "Overnight P0 revision does not match ExpectedBodyRigRevision."
}
Require-StrictBool -Value $summary.teacher_training_authorized -Expected $true -Label "summary.teacher_training_authorized"
Require-StrictBool -Value $summary.human_visual_acceptance_required -Expected $true -Label "summary.human_visual_acceptance_required"
Require-StrictBool -Value $summary.photoreal_acceptance_authority -Expected $false -Label "summary.photoreal_acceptance_authority"
Require-StrictBool -Value $summary.production_activation -Expected $false -Label "summary.production_activation"

if ([string]::IsNullOrWhiteSpace([string]$summary.output_root)) {
    throw "Overnight summary output_root is missing."
}
$outputRoot = [IO.Path]::GetFullPath([string]$summary.output_root)
if (-not (Test-Path -LiteralPath $outputRoot -PathType Container)) {
    throw "Overnight output_root is missing: $outputRoot"
}
if ([string]::IsNullOrWhiteSpace([string]$summary.p0_status)) {
    throw "Overnight summary p0_status is missing."
}
$p0StatusPath = Require-SamePath -Actual ([string]$summary.p0_status) -Expected (Join-Path $outputRoot "p0-status.json") -Label "summary.p0_status"
if (-not (Test-Path -LiteralPath $p0StatusPath -PathType Leaf)) {
    throw "Canonical p0-status.json is missing: $p0StatusPath"
}

$expectedStatusHash = ([string]$summary.p0_status_sha256).Trim().ToLowerInvariant()
if ($expectedStatusHash -notmatch '^[0-9a-f]{64}$') {
    throw "Overnight summary has an invalid p0_status_sha256."
}
$actualStatusHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $p0StatusPath).Hash.ToLowerInvariant()
if ($actualStatusHash -ne $expectedStatusHash) {
    throw "p0-status.json SHA-256 no longer matches the overnight summary."
}

$status = Read-Json -Path $p0StatusPath -Label "Photoreal P0 status"
if ([string]$status.format -ne "bodyrig-photoreal-p0-status" -or -not (Test-NumericExact -Value $status.version -Expected 1)) {
    throw "P0 status format/version mismatch."
}
if ([string]$status.performer_id -ne $ExpectedPerformerId) {
    throw "P0 status performer mismatch."
}
if ([string]$status.bodyrig_revision -ne $ExpectedBodyRigRevision) {
    throw "P0 status revision does not match ExpectedBodyRigRevision."
}
if ([string]$status.status -ne "teacher-training-authorized") {
    throw "P0 status is not canonical teacher-training-authorized."
}
Require-StrictBool -Value $status.teacher_training_authorized -Expected $true -Label "status.teacher_training_authorized"
Require-StrictBool -Value $status.human_visual_acceptance_required -Expected $true -Label "status.human_visual_acceptance_required"
Require-StrictBool -Value $status.photoreal_acceptance_authority -Expected $false -Label "status.photoreal_acceptance_authority"
Require-StrictBool -Value $status.production_activation -Expected $false -Label "status.production_activation"
if (@($status.blockers).Count -ne 0) {
    throw "P0 status still contains blockers."
}

$summaryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SummaryPath).Hash.ToLowerInvariant()
# Receipts belong to the exact P0 output root, not the shared overnight directory.
# Multiple runs may share one RunRoot; per-run placement prevents authority collisions.
$physicalOut = Join-Path $outputRoot "P0_PHYSICAL_VERIFICATION.json"

if (Test-Path -LiteralPath $physicalOut -PathType Leaf) {
    $physicalReceipt = Read-Json -Path $physicalOut -Label "Existing physical P0 verification"
    if ([string]$physicalReceipt.format -ne "bodyrig-photoreal-p0-physical-verification" -or -not (Test-NumericExact -Value $physicalReceipt.version -Expected 1)) {
        throw "Existing physical verification format/version mismatch."
    }
    if ([string]$physicalReceipt.performer_id -ne $ExpectedPerformerId -or [string]$physicalReceipt.exact_bodyrig_revision -ne $ExpectedBodyRigRevision) {
        throw "Existing physical verification authority does not match this P0."
    }
    if ([string]$physicalReceipt.overnight_summary_sha256 -ne $summaryHash -or [string]$physicalReceipt.p0_status_sha256 -ne $actualStatusHash) {
        throw "Existing physical verification is not bound to the current evidence bytes."
    }
    Require-StrictBool -Value $physicalReceipt.physical_p0_verified -Expected $true -Label "physical.physical_p0_verified"
    Require-StrictBool -Value $physicalReceipt.teacher_training_authorized -Expected $true -Label "physical.teacher_training_authorized"
    Require-StrictBool -Value $physicalReceipt.human_visual_acceptance_required -Expected $true -Label "physical.human_visual_acceptance_required"
    Require-StrictBool -Value $physicalReceipt.photoreal_acceptance_authority -Expected $false -Label "physical.photoreal_acceptance_authority"
    Require-StrictBool -Value $physicalReceipt.production_activation -Expected $false -Label "physical.production_activation"
    Write-Host "P0 physical verification: REUSED $physicalOut"
} else {
    $physicalReceipt = [ordered]@{
        format = "bodyrig-photoreal-p0-physical-verification"
        version = 1
        verified_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        performer_id = $ExpectedPerformerId
        exact_bodyrig_revision = $ExpectedBodyRigRevision
        overnight_summary = $SummaryPath
        overnight_summary_sha256 = $summaryHash
        p0_status = $p0StatusPath
        p0_status_sha256 = $actualStatusHash
        physical_p0_verified = $true
        teacher_training_authorized = $true
        human_visual_acceptance_required = $true
        photoreal_acceptance_authority = $false
        production_activation = $false
    }
    $physicalReceipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $physicalOut -Encoding UTF8
    Write-Host "P0 physical verification: CREATED $physicalOut"
}

$physicalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $physicalOut).Hash.ToLowerInvariant()
Write-Host "Physical SHA-256: $physicalHash"
Write-Host "physical_p0_verified=true"

if ($ExpectedBodyRigRevision -eq $verifierRevision) {
    $workflowEvidence = $verifierWorkflowEvidence
    $checkEvidence = $verifierCheckEvidence
} else {
    $workflowEvidence = Get-ExactHeadWorkflowEvidence -Revision $ExpectedBodyRigRevision
    $checkEvidence = Get-ExactHeadCheckEvidence -Revision $ExpectedBodyRigRevision
}
$evidenceExactHeadQualified = @($workflowEvidence.Blockers).Count -eq 0 -and @($checkEvidence.Blockers).Count -eq 0
$historicalAncestorRevalidation = $false
$softwareQualificationMode = "exact-head"

if ($evidenceExactHeadQualified) {
    $softwareQualified = $true
    if ($ExpectedBodyRigRevision -ne $verifierRevision) {
        $softwareQualificationMode = "historical-exact-head"
    }
} elseif (
    $ExpectedBodyRigRevision -ne $verifierRevision -and
    (Test-HistoricalQualificationGapIsCodeQlOnly -WorkflowEvidence $workflowEvidence -CheckEvidence $checkEvidence) -and
    (Test-HistoricalRevisionAncestor -RepoRoot ([string]$verifier.RepoRoot) -EvidenceRevision $ExpectedBodyRigRevision -VerifierRevision $verifierRevision)
) {
    $historicalAncestorRevalidation = $true
    $softwareQualificationMode = "historical-ancestor-revalidated-by-current-main"
    $softwareQualified = $verifierSoftwareQualified
} else {
    $softwareQualified = $false
}

Write-Host "evidence_exact_head_qualification_complete=$($evidenceExactHeadQualified.ToString().ToLowerInvariant())"
Write-Host "historical_ancestor_revalidation=$($historicalAncestorRevalidation.ToString().ToLowerInvariant())"
Write-Host "software_qualification_mode=$softwareQualificationMode"
Write-Host "software_qualification_complete=$($softwareQualified.ToString().ToLowerInvariant())"

if ($historicalAncestorRevalidation) {
    foreach ($blocker in @($workflowEvidence.Blockers)) {
        Write-Host "Historical exact-head gap (revalidated by current main): $blocker"
    }
    foreach ($blocker in @($checkEvidence.Blockers)) {
        Write-Host "Historical exact-head gap (revalidated by current main): $blocker"
    }
}

if (-not $softwareQualified) {
    foreach ($blocker in @($workflowEvidence.Blockers)) {
        Write-Host "Workflow blocker: $blocker"
    }
    foreach ($blocker in @($checkEvidence.Blockers)) {
        Write-Host "Check blocker: $blocker"
    }
    Write-Host "downstream_teacher_flow_ready=false"
    Write-Host "human_visual_acceptance_required=true"
    Write-Host "photoreal_acceptance_authority=false"
    Write-Host "production_activation=false"
    exit 2
}

$readiness = [ordered]@{
    format = "bodyrig-photoreal-p0-downstream-readiness"
    version = 1
    verified_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    performer_id = $ExpectedPerformerId
    exact_bodyrig_revision = $ExpectedBodyRigRevision
    verifier_bodyrig_revision = $verifierRevision
    verifier_script_path = [string]$verifier.RelativePath
    verifier_git_blob_oid = [string]$verifier.GitBlob
    verifier_script_sha256 = [string]$verifier.ScriptSha256
    verifier_software_qualification_complete = $true
    physical_verification = $physicalOut
    physical_verification_sha256 = $physicalHash
    overnight_summary = $SummaryPath
    overnight_summary_sha256 = $summaryHash
    p0_status = $p0StatusPath
    p0_status_sha256 = $actualStatusHash
    software_qualification_complete = $true
    software_qualification_mode = $softwareQualificationMode
    evidence_exact_head_qualification_complete = $evidenceExactHeadQualified
    historical_ancestor_revalidation = $historicalAncestorRevalidation
    physical_p0_verified = $true
    teacher_training_authorized = $true
    downstream_teacher_flow_ready = $true
    human_visual_acceptance_required = $true
    photoreal_acceptance_authority = $false
    production_activation = $false
    verifier_verified_runs = $verifierWorkflowEvidence.Verified
    verifier_verified_checks = $verifierCheckEvidence.Verified
    verified_runs = $workflowEvidence.Verified
    verified_checks = $checkEvidence.Verified
}

$readinessOut = Join-Path $outputRoot "P0_DOWNSTREAM_READINESS.json"
if (Test-Path -LiteralPath $readinessOut) {
    throw "Readiness receipt already exists: $readinessOut"
}
$readiness | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $readinessOut -Encoding UTF8
Write-Host "P0 downstream readiness: $readinessOut"
Write-Host "SHA-256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $readinessOut).Hash.ToLowerInvariant())"
Write-Host "downstream_teacher_flow_ready=true"
Write-Host "human_visual_acceptance_required=true"
Write-Host "photoreal_acceptance_authority=false"
Write-Host "production_activation=false"
