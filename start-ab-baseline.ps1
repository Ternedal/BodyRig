param(
    [ValidatePattern('^$|^person-[0-9a-f]{32}$')]
    [string]$PersonId = "",

    [string]$PerformerId = "",

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')]
    [string]$BaseUri = "http://127.0.0.1:8775",

    [string]$BodyRigPython = "",
    [string]$RigSetupReport = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [string]$Ffmpeg = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Invoke-CandidateAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [string]$ExpectedMainRevision = "",
        [string]$ExpectedPbrRevision = "",
        [string]$ExpectedThroughputRevision = ""
    )

    $oldPythonPath = [string]$env:PYTHONPATH
    $oldNoBytecode = [string]$env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" })
        $env:PYTHONDONTWRITEBYTECODE = "1"

        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.ab_baseline_candidates as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) {
            throw "Could not prove checkout-bound dual-candidate A/B validator: $($moduleRaw -join ' ')"
        }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\ab_baseline_candidates.py"))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Dual-candidate A/B validator imported from wrong checkout: $actualModule"
        }

        $pythonArgs = @("-m", "bodyrig.ab_baseline_candidates", "--repo-root", $RepoRoot)
        if (-not [string]::IsNullOrWhiteSpace($ExpectedMainRevision)) {
            $pythonArgs += @("--expected-main-revision", $ExpectedMainRevision)
        }
        if (-not [string]::IsNullOrWhiteSpace($ExpectedPbrRevision)) {
            $pythonArgs += @("--expected-pbr-revision", $ExpectedPbrRevision)
        }
        if (-not [string]::IsNullOrWhiteSpace($ExpectedThroughputRevision)) {
            $pythonArgs += @("--expected-throughput-revision", $ExpectedThroughputRevision)
        }
        $raw = @(& $Python @pythonArgs 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) {
            throw "Dual-candidate A/B authority validation failed: $($raw -join ' ')"
        }
        try { $result = ([string]$raw[0]) | ConvertFrom-Json }
        catch { throw "Dual-candidate A/B validator returned unreadable JSON." }
        if (
            [string]$result.format -ne "bodyrig-ab-baseline-candidate-authority" -or
            [int]$result.version -ne 1 -or
            $result.comparison_only -ne $true -or
            $result.human_visual_authority_required -ne $true -or
            $result.physical_acceptance_authority -ne $false -or
            $result.promotion_authority -ne $false -or
            $result.production_activation -ne $false
        ) {
            throw "Dual-candidate A/B validator returned unexpected authority semantics."
        }
        return $result
    }
    finally {
        if ([string]::IsNullOrEmpty($oldPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
        if ([string]::IsNullOrEmpty($oldNoBytecode)) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode }
    }
}

function Try-CancelBaselineJob {
    param(
        [Parameter(Mandatory = $true)][string]$JobId,
        [Parameter(Mandatory = $true)][string]$UriBase
    )
    try {
        $result = Invoke-RestMethod -Method Post -Uri "$UriBase/api/v1/jobs/$JobId/cancel" -TimeoutSec 10
        $status = [string]$result.status
        if ([string]$result.job_id -ne $JobId -or $status -notin @("canceled", "cancelling")) {
            return "cancel endpoint returned unexpected state '$status'"
        }
        return "cancel requested successfully ($status)"
    }
    catch {
        return "cancel request failed: $($_.Exception.Message)"
    }
}

function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite A/B baseline plan: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temp -Encoding utf8
        Move-Item -LiteralPath $temp -Destination $Path
    }
    finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig dual-candidate A/B baseline launcher is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for revision-bound A/B baselines."
}
if ([string]::IsNullOrWhiteSpace($PersonId) -eq [string]::IsNullOrWhiteSpace($PerformerId)) {
    throw "Pass exactly one of -PersonId or -PerformerId."
}

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

$physicalPreflightScript = Need-File -Path (Join-Path $repoRoot "preflight-ab-baseline.ps1") -Label "A/B baseline physical preflight"
$pwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwshCommand) { throw "PowerShell 7 executable (pwsh) was not found." }
$physicalPreflightArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $physicalPreflightScript,
    "-BaseUri", $BaseUri,
    "-BodyRigPython", $BodyRigPython,
    "-ApiKeyEnv", $ApiKeyEnv,
    "-WslExe", $WslExe
)
if (-not [string]::IsNullOrWhiteSpace($PersonId)) { $physicalPreflightArgs += @("-PersonId", $PersonId) }
else { $physicalPreflightArgs += @("-PerformerId", $PerformerId) }
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $physicalPreflightArgs += @("-RigSetupReport", $RigSetupReport) }
if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $physicalPreflightArgs += @("-StashUrl", $StashUrl) }
if (-not [string]::IsNullOrWhiteSpace($Ffmpeg)) { $physicalPreflightArgs += @("-Ffmpeg", $Ffmpeg) }

Write-Host "Running read-only fail-fast rig/source preflight before A/B baseline enqueue..."
$physicalPreflightRaw = @(& $pwshCommand.Source @physicalPreflightArgs 2>&1)
$physicalPreflightExit = $LASTEXITCODE
$physicalPreflightRaw | ForEach-Object { Write-Host $_ }
if ($physicalPreflightExit -ne 0) {
    throw "BodyRig A/B baseline physical preflight failed with exit code $physicalPreflightExit. No baseline job was enqueued."
}

Write-Host "Revalidating current main and both active A/B candidate byte contracts immediately before enqueue..."
$preflight = Invoke-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython
$mainRevision = [string]$preflight.main_revision
$pbrRevision = [string]$preflight.candidates.pbr_v2.revision
$throughputRevision = [string]$preflight.candidates.recovery_throughput_v3.revision
$contractSha256 = [string]$preflight.contract_sha256

$startScript = Need-File -Path (Join-Path $repoRoot "start-revision-bound-body-build.ps1") -Label "revision-bound body-build launcher"
$startArgs = @("-RetainPrivateWorkspaceForAb", "-BaseUri", $BaseUri)
if (-not [string]::IsNullOrWhiteSpace($PersonId)) { $startArgs += @("-PersonId", $PersonId) }
else { $startArgs += @("-PerformerId", $PerformerId) }

$startedRaw = @(& $startScript @startArgs)
if ($startedRaw.Count -ne 1) {
    throw "Revision-bound retained baseline launcher did not return exactly one machine-readable job result."
}
try { $started = ([string]$startedRaw[0]) | ConvertFrom-Json }
catch { throw "Revision-bound retained baseline launcher returned unreadable JSON." }

$jobId = [string]$started.job_id
$resolvedPersonId = [string]$started.person_id
if ($jobId -notmatch '^job-[0-9a-f]{32}$' -or $resolvedPersonId -notmatch '^person-[0-9a-f]{32}$') {
    throw "Retained baseline launcher returned non-canonical job/Person identity."
}
if ([string]$started.bodyrig_revision -ne $mainRevision) {
    $cancelState = Try-CancelBaselineJob -JobId $jobId -UriBase $BaseUri
    throw "Baseline job revision does not match preflight main; $cancelState. Job $jobId is NOT dual-candidate baseline authority."
}
$retention = $started.ab_baseline_retention
if (
    $null -eq $retention -or
    [string]$retention.format -ne "bodyrig-ab-baseline-retention" -or
    [int]$retention.version -ne 1 -or
    $retention.retain_private_workspace -ne $true -or
    [string]$retention.expected_bodyrig_revision -ne $mainRevision -or
    [string]$retention.job_id -ne $jobId
) {
    $cancelState = Try-CancelBaselineJob -JobId $jobId -UriBase $BaseUri
    throw "Baseline job lacks exact revision-bound A/B retention; $cancelState. Job $jobId is NOT dual-candidate baseline authority."
}

try {
    $postflight = Invoke-CandidateAuthority `
        -RepoRoot $repoRoot `
        -Python $BodyRigPython `
        -ExpectedMainRevision $mainRevision `
        -ExpectedPbrRevision $pbrRevision `
        -ExpectedThroughputRevision $throughputRevision
    if ([string]$postflight.contract_sha256 -ne $contractSha256) {
        throw "A/B candidate contract hash changed after baseline enqueue."
    }
}
catch {
    $cancelState = Try-CancelBaselineJob -JobId $jobId -UriBase $BaseUri
    throw "A/B candidate authority moved after baseline enqueue: $($_.Exception.Message). $cancelState. Job $jobId is NOT dual-candidate baseline authority."
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $cancelState = Try-CancelBaselineJob -JobId $jobId -UriBase $BaseUri
    throw "LOCALAPPDATA is required for create-only A/B baseline plan storage. $cancelState. Job $jobId is NOT dual-candidate baseline authority."
}
$planDir = Join-Path $env:LOCALAPPDATA "BodyRig\ab-baseline-plans"
$planPath = Join-Path $planDir "$jobId.json"
$plan = [ordered]@{
    format = "bodyrig-dual-candidate-ab-baseline-plan"
    version = 1
    baseline_job_id = $jobId
    person_id = $resolvedPersonId
    baseline_bodyrig_revision = $mainRevision
    candidate_contract_sha256 = $contractSha256
    pbr_candidate = [ordered]@{
        ref = [string]$postflight.candidates.pbr_v2.ref
        revision = $pbrRevision
        retained_reconstruction_reuse = $true
    }
    throughput_candidate = [ordered]@{
        ref = [string]$postflight.candidates.recovery_throughput_v3.ref
        revision = $throughputRevision
        separate_candidate_body_build_required = $true
    }
    ab_baseline_retention = $retention
    comparison_only = $true
    human_visual_authority_required = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
}
try {
    Write-CreateOnlyJson -Path $planPath -Value $plan
}
catch {
    $cancelState = Try-CancelBaselineJob -JobId $jobId -UriBase $BaseUri
    throw "Could not publish create-only dual-candidate A/B baseline plan: $($_.Exception.Message). $cancelState. Job $jobId is NOT dual-candidate baseline authority."
}

Write-Host "BodyRig dual-candidate A/B baseline: STARTED"
Write-Host "Baseline main:       $mainRevision"
Write-Host "PBR candidate:       $pbrRevision"
Write-Host "Throughput candidate:$throughputRevision"
Write-Host "Person:              $resolvedPersonId"
Write-Host "Baseline job:        $jobId"
Write-Host "Plan:                $planPath"
Write-Host "Monitor:             .\watch-body-build.ps1 -JobId '$jobId'"
Write-Host "After baseline succeeds, canonical plan-bound PBR A/B:"
Write-Host "  .\run-pbr-ab-from-body-job-plan-bound.ps1 -BaselineJobId '$jobId'"
Write-Host "Throughput A/B still requires a separate succeeded body-build from exact candidate revision $throughputRevision using the same Person/source authority."
Write-Host "Authority: comparison-only; human review required; no physical acceptance, promotion or production activation."

$plan | ConvertTo-Json -Depth 20 -Compress
