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

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40 }
    catch { throw "$Label is unreadable JSON: $Path" }
    if ($null -eq $value) { throw "$Label is empty: $Path" }
    return $value
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
}

function Escape-SingleQuotedPowerShell {
    param([Parameter(Mandatory = $true)][string]$Value)
    return $Value.Replace("'", "''")
}

function Write-AtomicUtf8Text {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Text)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw "Review-next parent directory does not exist: $parent" }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        Set-Content -LiteralPath $temp -Value $Text -Encoding UTF8 -NoNewline
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
    $roundTrip = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ($roundTrip -ne $Text) { throw "Plan-bound REVIEW-NEXT.txt did not round-trip byte-for-text as expected." }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig canonical plan-bound PBR A/B launcher is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required for plan-bound PBR A/B output."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0,8)
    $OutputDir = Join-Path $env:LOCALAPPDATA "BodyRig\pbr-ab-body-job\$BaselineJobId-$stamp-$suffix"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "PBR A/B output already exists: $OutputDir" }

$runner = Need-File -Path (Join-Path $repoRoot "run-pbr-ab-from-body-job.ps1") -Label "plan-bound PBR body-job runner"
$recorder = Need-File -Path (Join-Path $repoRoot "record-pbr-ab-human-review-from-plan.ps1") -Label "plan-bound PBR human-review recorder"
$runnerParams = @{
    BaselineJobId = $BaselineJobId
    CandidateRef = $CandidateRef
    OutputDir = $OutputDir
}
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $runnerParams.RigSetupReport = $RigSetupReport }
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $runnerParams.BodyRigPython = $BodyRigPython }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $runnerParams.UnityExe = $UnityExe }

& $runner @runnerParams
if ($LASTEXITCODE -ne 0) { throw "Plan-bound PBR body-job runner failed with exit code $LASTEXITCODE" }

$OutputDir = Need-Directory -Path $OutputDir -Label "completed plan-bound PBR A/B run"
$runAuthorityPath = Need-File -Path (Join-Path $OutputDir "run-authority.json") -Label "PBR run authority"
$sourceAuthorityPath = Need-File -Path (Join-Path $OutputDir "body-job-source-authority.json") -Label "PBR source authority"
$planAuthorityPath = Need-File -Path (Join-Path $OutputDir "body-job-plan-authority.json") -Label "PBR plan authority"
[void](Need-File -Path (Join-Path $OutputDir "machine-ab.json") -Label "PBR machine A/B evidence")
[void](Need-Directory -Path (Join-Path $OutputDir "baseline-render") -Label "baseline render set")
[void](Need-Directory -Path (Join-Path $OutputDir "candidate-render") -Label "candidate render set")
[void](Need-File -Path (Join-Path $OutputDir "review.html") -Label "PBR review page")

$planAuthority = Read-Json -Path $planAuthorityPath -Label "PBR plan authority"
if (
    [string]$planAuthority.format -ne "bodyrig-pbr-ab-body-job-plan-authority" -or
    [int]$planAuthority.version -ne 1 -or
    [string]$planAuthority.baseline_job_id -ne $BaselineJobId -or
    $planAuthority.comparison_only -ne $true -or
    $planAuthority.human_visual_authority_required -ne $true -or
    $planAuthority.physical_acceptance_authority -ne $false -or
    $planAuthority.promotion_authority -ne $false -or
    $planAuthority.production_activation -ne $false
) {
    throw "PBR plan authority is not eligible for canonical plan-bound human review."
}
$runSha = (Get-FileHash -LiteralPath $runAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sourceSha = (Get-FileHash -LiteralPath $sourceAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
if (
    (Need-Sha256 -Value ([string]$planAuthority.run_authority_sha256) -Label "plan-bound run-authority SHA") -ne $runSha -or
    (Need-Sha256 -Value ([string]$planAuthority.source_authority_sha256) -Label "plan-bound source-authority SHA") -ne $sourceSha
) {
    throw "PBR plan authority no longer binds the exact run/source authority bytes."
}

$humanReviewPath = Join-Path $OutputDir "human-review.json"
$humanAuthorityPath = Join-Path $OutputDir "plan-bound-human-review-authority.json"
if (Test-Path -LiteralPath $humanReviewPath) { throw "Human review already exists; refusing to rewrite review routing: $humanReviewPath" }
if (Test-Path -LiteralPath $humanAuthorityPath) { throw "Plan-bound human-review authority already exists; refusing to rewrite review routing: $humanAuthorityPath" }

$reviewNextPath = Join-Path $OutputDir "REVIEW-NEXT.txt"
$escapedJob = Escape-SingleQuotedPowerShell -Value $BaselineJobId
$escapedRun = Escape-SingleQuotedPowerShell -Value $OutputDir
$reviewText = @"
# BodyRig canonical plan-bound PBR A/B human review
# Open review.html and compare all four canonical LEFT/RIGHT views first.
# Replace both <...> placeholders. The recorder rejects placeholder values.
# Baseline-plan authority SHA-256: $((Get-FileHash -LiteralPath $planAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant())
# Run authority SHA-256: $runSha

.\record-pbr-ab-human-review-from-plan.ps1 ``
  -BaselineJobId '$escapedJob' ``
  -RunDir '$escapedRun' ``
  -Decision '<left|right|tie|reject-both>' ``
  -QualityNote '<actual visual assessment>' ``
  -ConfirmVisualReview
"@
Write-AtomicUtf8Text -Path $reviewNextPath -Text $reviewText

Write-Host "BodyRig canonical plan-bound PBR A/B: READY FOR EXPLICIT HUMAN REVIEW"
Write-Host "Baseline job:   $BaselineJobId"
Write-Host "Run output:     $OutputDir"
Write-Host "Review page:    $(Join-Path $OutputDir 'review.html')"
Write-Host "Review command: $reviewNextPath"
Write-Host "Recorder:       $recorder"
Write-Host "Authority: comparison-only; no physical acceptance, promotion or production activation."
exit 0