param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$SelectionInput,
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
    throw "P2 HELD-OUT animated review planning requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 HELD-OUT animated review planning requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$SelectionInput = Need-File -Path $SelectionInput -Label "P2 HELD-OUT animated review selection input"
if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"

$selection = Get-Content -LiteralPath $SelectionInput -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$refs = @(
    @($selection.selections) |
        ForEach-Object { ([string]$_.held_out_source_ref).Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique
)
if ($refs.Count -lt 1) {
    throw "P2 HELD-OUT animated review selection contains no source refs."
}

$evaluationWorkspaces = @()
foreach ($sourceRef in $refs) {
    if ($sourceRef -notmatch '^[A-Za-z0-9._-]+$') {
        throw "Held-out source ref contains characters unsafe for the canonical evaluation path: $sourceRef"
    }
    $workspace = Join-Path (Join-Path $P2Root "animation-evaluation\heldout-execution") $sourceRef
    $evaluationWorkspaces += Need-Directory -Path $workspace -Label "HELD-OUT evaluation workspace $sourceRef"
}

$reviewRoot = Join-Path $P2Root "animated-review"
New-Item -ItemType Directory -Path $reviewRoot -Force | Out-Null
$outputPath = Join-Path $reviewRoot "p2-heldout-animated-review-plan.json"
if ((Test-Path -LiteralPath $outputPath -PathType Leaf) -and -not $ReuseExisting) {
    throw "P2 HELD-OUT animated review plan already exists: $outputPath"
}
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - HELD-OUT ANIMATED REVIEW PLAN"
Write-Host "Selection input:       $SelectionInput"
Write-Host "Evidence sources:      $($refs.Count)"
foreach ($sourceRef in $refs) { Write-Host ("  HELD-OUT: {0}" -f $sourceRef) }
Write-Host "Output plan:           $outputPath"
Write-Host "Evidence bytes:        REVERIFY NOW"
Write-Host "Human review complete: FALSE"
Write-Host "Animated acceptance:   FALSE"
Write-Host "Quest distillation:    FALSE"
Write-Host "Production:            FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p2_heldout_animated_review_plan",
    "--selection-input", $SelectionInput,
    "--out", $outputPath
)
foreach ($workspace in $evaluationWorkspaces) {
    $argsList += @("--evaluation-workspace", $workspace)
}
if ($ReuseExisting) { $argsList += "--reuse-existing" }

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 HELD-OUT animated review planning failed with code $code."
}

$plan = Get-Content -LiteralPath (Need-File -Path $outputPath -Label "P2 HELD-OUT animated review plan") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
foreach ($field in @(
    "held_out_evaluation_only",
    "evaluation_artifact_bytes_reverified",
    "human_animated_visual_acceptance_required"
)) {
    if ($plan.$field -isnot [bool] -or $plan.$field -ne $true) {
        throw "P2 HELD-OUT animated review plan authority missing: $field"
    }
}
foreach ($field in @(
    "human_animated_review_complete",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($plan.$field -isnot [bool] -or $plan.$field -ne $false) {
        throw "P2 HELD-OUT animated review plan crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P2 HELD-OUT animated review plan: READY"
Write-Host "Review dimensions:                  $($plan.selection_count)"
Write-Host "Evidence sources:                   $($plan.evidence_source_count)"
Write-Host "Evidence bytes:                     REVERIFIED"
Write-Host "Human review complete:              FALSE"
Write-Host "Animated acceptance:                FALSE"
Write-Host "Quest distillation:                 FALSE"
Write-Host "Production:                         FALSE"
Write-Host "Plan: $outputPath"
exit 0
