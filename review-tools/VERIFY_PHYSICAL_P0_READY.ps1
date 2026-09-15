param(
    [Parameter(Mandatory = $true)]
    [string]$SummaryPath,
    [string]$ExpectedPerformerId = "42"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$expectedSha = "c98442a06eee32fb9ca0b8e386856bef58c8350c"

function Read-Json {
    param([string]$Path, [string]$Label)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 }
    catch { throw "$Label is unreadable JSON: $Path" }
}

function Require-StrictBool {
    param([AllowNull()]$Value, [bool]$Expected, [string]$Label)
    if ($Value -isnot [bool] -or [bool]$Value -ne $Expected) {
        throw "$Label must be $Expected."
    }
}

$SummaryPath = (Resolve-Path -LiteralPath $SummaryPath).Path
$summary = Read-Json -Path $SummaryPath -Label "Photoreal overnight summary"

if ([string]$summary.format -ne "bodyrig-photoreal-v2-overnight-summary" -or [int]$summary.version -ne 1) {
    throw "Overnight summary format/version mismatch."
}
if ([string]$summary.performer_id -ne $ExpectedPerformerId) {
    throw "Overnight summary performer mismatch."
}
if ([string]$summary.status -ne "completed" -or [int]$summary.exit_code -ne 0) {
    throw "Overnight P0 is not a completed success."
}
if ([string]$summary.bodyrig_revision -ne $expectedSha) {
    throw "Overnight P0 was not produced by exact BodyRig #853 head $expectedSha."
}
Require-StrictBool -Value $summary.teacher_training_authorized -Expected $true -Label "summary.teacher_training_authorized"
Require-StrictBool -Value $summary.human_visual_acceptance_required -Expected $true -Label "summary.human_visual_acceptance_required"
Require-StrictBool -Value $summary.photoreal_acceptance_authority -Expected $false -Label "summary.photoreal_acceptance_authority"
Require-StrictBool -Value $summary.production_activation -Expected $false -Label "summary.production_activation"

$outputRoot = [IO.Path]::GetFullPath([string]$summary.output_root)
$p0StatusPath = [IO.Path]::GetFullPath([string]$summary.p0_status)
$expectedStatusPath = [IO.Path]::GetFullPath((Join-Path $outputRoot "p0-status.json"))
if (-not [string]::Equals($p0StatusPath, $expectedStatusPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Overnight summary p0_status is not the canonical file inside output_root."
}
if (-not (Test-Path -LiteralPath $p0StatusPath -PathType Leaf)) {
    throw "Canonical p0-status.json is missing: $p0StatusPath"
}

$expectedStatusHash = ([string]$summary.p0_status_sha256).ToLowerInvariant()
if ($expectedStatusHash -notmatch '^[0-9a-f]{64}$') {
    throw "Overnight summary has an invalid p0_status_sha256."
}
$actualStatusHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $p0StatusPath).Hash.ToLowerInvariant()
if ($actualStatusHash -ne $expectedStatusHash) {
    throw "p0-status.json SHA-256 no longer matches the overnight summary."
}

$status = Read-Json -Path $p0StatusPath -Label "Photoreal P0 status"
if ([string]$status.format -ne "bodyrig-photoreal-p0-status" -or [int]$status.version -ne 1) {
    throw "P0 status format/version mismatch."
}
if ([string]$status.performer_id -ne $ExpectedPerformerId) {
    throw "P0 status performer mismatch."
}
if ([string]$status.bodyrig_revision -ne $expectedSha) {
    throw "P0 status was not produced by exact BodyRig #853 head."
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

$runs = [ordered]@{
    ci = 35007157763
    windows_log_handle_regression = 35007157682
    loc_metrics = 35007157723
    codeql = 35007157699
}
$headers = @{
    Accept = "application/vnd.github+json"
    "User-Agent" = "BodyRig-p0-readiness-verifier"
    "X-GitHub-Api-Version" = "2022-11-28"
}
if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
    $headers.Authorization = "Bearer $($env:GITHUB_TOKEN)"
}

$verifiedRuns = [ordered]@{}
foreach ($name in $runs.Keys) {
    $runId = [long]$runs[$name]
    try {
        $run = Invoke-RestMethod -Method Get -Uri "https://api.github.com/repos/Ternedal/BodyRig/actions/runs/$runId" -Headers $headers
    } catch {
        throw "Could not verify GitHub Actions run $name ($runId): $($_.Exception.Message)"
    }
    if ([string]$run.head_sha -ne $expectedSha) {
        throw "Run $name ($runId) belongs to another head: $($run.head_sha)"
    }
    if ([string]$run.status -ne "completed" -or [string]$run.conclusion -ne "success") {
        throw "Run $name ($runId) is not successful: status=$($run.status) conclusion=$($run.conclusion)"
    }
    $verifiedRuns[$name] = [ordered]@{
        run_id = $runId
        status = [string]$run.status
        conclusion = [string]$run.conclusion
        head_sha = [string]$run.head_sha
    }
}

$readiness = [ordered]@{
    format = "bodyrig-photoreal-p0-downstream-readiness"
    version = 1
    verified_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    performer_id = $ExpectedPerformerId
    exact_bodyrig_revision = $expectedSha
    overnight_summary = $SummaryPath
    overnight_summary_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $SummaryPath).Hash.ToLowerInvariant()
    p0_status = $p0StatusPath
    p0_status_sha256 = $actualStatusHash
    software_qualification_complete = $true
    physical_p0_verified = $true
    teacher_training_authorized = $true
    downstream_teacher_flow_ready = $true
    human_visual_acceptance_required = $true
    photoreal_acceptance_authority = $false
    production_activation = $false
    verified_runs = $verifiedRuns
}

$out = Join-Path (Split-Path -Parent $SummaryPath) "P0_DOWNSTREAM_READINESS.json"
if (Test-Path -LiteralPath $out) {
    throw "Readiness receipt already exists: $out"
}
$readiness | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Host "P0 downstream readiness: $out"
Write-Host "SHA-256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $out).Hash.ToLowerInvariant())"
Write-Host "downstream_teacher_flow_ready=true"
Write-Host "human_visual_acceptance_required=true"
Write-Host "photoreal_acceptance_authority=false"
Write-Host "production_activation=false"
