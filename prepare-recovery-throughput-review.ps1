param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^person-[0-9a-f]{32}$')]
    [string]$PersonId,

    [string]$Out = "",
    [string]$RepoRoot = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-JsonPropertyValue {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = $PSScriptRoot
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$autoComparator = Join-Path $RepoRoot "compare-recovery-throughput-auto.ps1"
$bundleBuilder = Join-Path $RepoRoot "build-recovery-throughput-review-bundle.ps1"
if (-not (Test-Path -LiteralPath $autoComparator -PathType Leaf)) {
    throw "BodyRig automatic recovery A/B comparator not found: $autoComparator"
}
if (-not (Test-Path -LiteralPath $bundleBuilder -PathType Leaf)) {
    throw "BodyRig recovery review-bundle builder not found: $bundleBuilder"
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) {
    throw "RepoRoot is not a BodyRig Git checkout: $RepoRoot"
}

$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$scratchAudit = Join-Path ([System.IO.Path]::GetTempPath()) ("bodyrig-recovery-throughput-auto-" + [Guid]::NewGuid().ToString("N") + ".json")

try {
    Write-Host "BodyRig recovery throughput review preparation"
    Write-Host "Person: $PersonId"
    Write-Host "Step 1/2: canonical auto-discovery + fail-closed machine A/B audit"

    & $pwsh `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $autoComparator `
        -PersonId $PersonId `
        -Out $scratchAudit `
        -RepoRoot $RepoRoot
    $autoExit = $LASTEXITCODE
    if ($autoExit -ne 0) {
        throw "Canonical recovery A/B machine audit did not pass (exit $autoExit). No review bundle was created."
    }
    if (-not (Test-Path -LiteralPath $scratchAudit -PathType Leaf)) {
        throw "Canonical recovery A/B audit reported success but did not create its scratch report."
    }

    try {
        $audit = Get-Content -LiteralPath $scratchAudit -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    } catch {
        throw "Canonical recovery A/B scratch report is not valid JSON."
    }

    $format = [string](Get-JsonPropertyValue -Object $audit -Name "format")
    $version = Get-JsonPropertyValue -Object $audit -Name "version"
    $auditPerson = [string](Get-JsonPropertyValue -Object $audit -Name "person_id")
    $machinePass = Get-JsonPropertyValue -Object $audit -Name "machine_evidence_pass"
    $decision = [string](Get-JsonPropertyValue -Object $audit -Name "decision")
    $promotion = Get-JsonPropertyValue -Object $audit -Name "promotion_authority"
    $production = Get-JsonPropertyValue -Object $audit -Name "production_activation"
    $baselineJobId = [string](Get-JsonPropertyValue -Object $audit -Name "baseline_job_id")
    $candidateJobId = [string](Get-JsonPropertyValue -Object $audit -Name "candidate_job_id")

    if ($format -ne "bodyrig-recovery-throughput-sampling-audit" -or $version -ne 1) {
        throw "Canonical recovery A/B scratch report format/version mismatch."
    }
    if ($auditPerson -ne $PersonId) {
        throw "Canonical recovery A/B scratch report person_id mismatch."
    }
    if ($machinePass -ne $true -or $decision -ne "eligible-for-human-ab-review") {
        throw "Canonical recovery A/B scratch report is not eligible for human review."
    }
    if ($promotion -ne $false -or $production -ne $false) {
        throw "Canonical recovery A/B scratch report crossed the promotion/production authority boundary."
    }
    if ($baselineJobId -notmatch '^job-[0-9a-f]{32}$' -or $candidateJobId -notmatch '^job-[0-9a-f]{32}$') {
        throw "Canonical recovery A/B scratch report contains invalid selected job ids."
    }

    Write-Host "Selected baseline:  $baselineJobId"
    Write-Host "Selected candidate: $candidateJobId"
    Write-Host "Step 2/2: rebuild full machine gate and create immutable human-review bundle"

    $bundleArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $bundleBuilder,
        "-BaselineJobId", $baselineJobId,
        "-CandidateJobId", $candidateJobId,
        "-RepoRoot", $RepoRoot
    )
    if (-not [string]::IsNullOrWhiteSpace($Out)) {
        $bundleArgs += @("-Out", [System.IO.Path]::GetFullPath($Out))
    }

    & $pwsh @bundleArgs
    $bundleExit = $LASTEXITCODE
    if ($bundleExit -ne 0) {
        throw "Recovery A/B review-bundle build failed (exit $bundleExit)."
    }

    if (-not [string]::IsNullOrWhiteSpace($Out)) {
        $bundleRoot = [System.IO.Path]::GetFullPath($Out)
    } else {
        if (-not [string]::IsNullOrWhiteSpace($env:BODYRIG_DATA_DIR)) {
            $dataRoot = [System.IO.Path]::GetFullPath($env:BODYRIG_DATA_DIR)
        } elseif (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            $dataRoot = Join-Path $env:LOCALAPPDATA "BodyRig"
        } else {
            throw "BodyRig data root cannot be resolved after the bundle build."
        }
        $bundleRoot = Join-Path (Join-Path $dataRoot "recovery-throughput-reviews") "$baselineJobId--$candidateJobId"
    }

    $index = Join-Path $bundleRoot "index.html"
    $receipt = Join-Path $bundleRoot "review-bundle.json"
    if (-not (Test-Path -LiteralPath $index -PathType Leaf) -or -not (Test-Path -LiteralPath $receipt -PathType Leaf)) {
        throw "Review bundle build reported success but canonical bundle files are missing."
    }

    if (-not $NoBrowser) {
        Start-Process -FilePath $index
    }

    Write-Host "BodyRig recovery throughput review preparation: READY"
    Write-Host "Bundle: $bundleRoot"
    Write-Host "Human review page: $index"
    Write-Host "No human PASS, promotion, production activation, checkout switch or restore was performed."
    Write-Host "After visual review, record the explicit receipt with record-recovery-throughput-human-review.ps1, then restore canonical Person Studio authority."
    exit 0
} finally {
    if (Test-Path -LiteralPath $scratchAudit -PathType Leaf) {
        Remove-Item -LiteralPath $scratchAudit -Force -ErrorAction SilentlyContinue
    }
}
