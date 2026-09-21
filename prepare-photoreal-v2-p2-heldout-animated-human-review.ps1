param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [string]$P2Root = "",
    [switch]$ReuseExisting,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-BodyRigPython {
    param([string]$Requested,[Parameter(Mandatory = $true)][string]$RepoRoot)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Need-File -Path $Requested -Label "BodyRig Python"
    }
    $venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "Python not found. Pass -BodyRigPython explicitly." }
    return $command.Source
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1 -or ([string]$branch[0]).Trim() -ne "main") {
    throw "P2 HELD-OUT animated human review preparation requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 HELD-OUT animated human review preparation requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"
$reviewPlan = Need-File -Path (Join-Path $P2Root "animated-review\p2-heldout-animated-review-plan.json") -Label "P2 HELD-OUT animated review plan"
$plan = Get-Content -LiteralPath $reviewPlan -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

$refs = @(
    @($plan.selections) |
        ForEach-Object { ([string]$_.held_out_source_ref).Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique
)
if ($refs.Count -lt 1) { throw "P2 HELD-OUT animated review plan contains no evidence source refs." }

$evaluationWorkspaces = @()
foreach ($sourceRef in $refs) {
    if ($sourceRef -notmatch '^[A-Za-z0-9._-]+$') {
        throw "Held-out source ref contains characters unsafe for the canonical evaluation path: $sourceRef"
    }
    $workspace = Join-Path (Join-Path $P2Root "animation-evaluation\heldout-execution") $sourceRef
    $evaluationWorkspaces += Need-Directory -Path $workspace -Label "HELD-OUT evaluation workspace $sourceRef"
}

$reviewRoot = Join-Path $P2Root "animated-review\human-review"
if ((Test-Path -LiteralPath $reviewRoot) -and -not $ReuseExisting) {
    throw "P2 HELD-OUT animated human review pack already exists: $reviewRoot"
}

$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - PREPARE HUMAN ANIMATED REVIEW"
Write-Host "Review plan:           $reviewPlan"
Write-Host "Evidence sources:      $($refs.Count)"
Write-Host "Review root:           $reviewRoot"
Write-Host "Human decisions:       NOT RECORDED"
Write-Host "Animated acceptance:   FALSE"
Write-Host "P3 / Quest:            FALSE"
Write-Host "Production:            FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p2_heldout_animated_human_review",
    "prepare",
    "--review-plan", $reviewPlan,
    "--out", $reviewRoot
)
foreach ($workspace in $evaluationWorkspaces) {
    $argsList += @("--evaluation-workspace", $workspace)
}
if ($ReuseExisting) { $argsList += "--reuse-existing" }

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 2) {
    throw "P2 HELD-OUT animated human review preparation returned unexpected code $code."
}

$manifest = Get-Content -LiteralPath (Need-File -Path (Join-Path $reviewRoot "p2-heldout-animated-human-review-manifest.json") -Label "P2 animated human review manifest") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
foreach ($field in @(
    "human_animated_visual_acceptance_required"
)) {
    if ($manifest.$field -isnot [bool] -or $manifest.$field -ne $true) {
        throw "P2 animated human review preparation authority missing: $field"
    }
}
foreach ($field in @(
    "human_animated_review_complete",
    "p2_animated_teacher_acceptance_authority",
    "p3_device_distillation_authorized",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($manifest.$field -isnot [bool] -or $manifest.$field -ne $false) {
        throw "P2 animated human review preparation crossed authority boundary: $field"
    }
}

$reviewIndex = Need-File -Path (Join-Path $reviewRoot "review-index.html") -Label "P2 animated human review index"
Write-Host ""
Write-Host "Human P2 animated review pack: READY"
Write-Host "Review dimensions:             $($manifest.dimension_evidence_count)"
Write-Host "Quality checks:                $($manifest.quality_checks.Count)"
Write-Host "Human decisions:               REQUIRED"
Write-Host "Animated acceptance:           FALSE"
Write-Host "P3 / Quest:                    FALSE"
Write-Host "Production:                    FALSE"
Write-Host "Review: $reviewIndex"
Start-Process $reviewIndex
exit 0
