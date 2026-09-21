param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [string]$P2Root = "",
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
    throw "P2 animation planning requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 animation planning requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$teacherInput = Need-File -Path (Join-Path $TeacherWorkRoot "teacher-input.json") -Label "Strict teacher input"
$teacherConfig = Need-File -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-config.json") -Label "ExAvatar teacher config"
$teacherWorkspace = Need-Directory -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-output") -Label "ExAvatar teacher workspace"
$teacherResultRoot = Need-Directory -Path (Join-Path $teacherWorkspace "output") -Label "ExAvatar teacher result root"
Need-File -Path (Join-Path $teacherResultRoot "teacher-manifest.json") -Label "ExAvatar teacher manifest" | Out-Null

$p1Root = Need-Directory -Path (Join-Path $TeacherWorkRoot "p1-static-teacher-review") -Label "P1 review root"
$p1ReviewRoot = Need-Directory -Path (Join-Path $p1Root "likeness-review") -Label "P1 likeness review root"
$p1Receipt = Need-File -Path (Join-Path $p1Root "p1-likeness-review.json") -Label "P1 likeness review receipt"
Need-File -Path (Join-Path $p1ReviewRoot "p1-likeness-review-manifest.json") -Label "P1 likeness review manifest" | Out-Null

if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = [IO.Path]::GetFullPath($P2Root)
New-Item -ItemType Directory -Path $P2Root -Force | Out-Null
$plan = Join-Path $P2Root "p2-animation-plan.json"
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P2 ANIMATION PLAN"
Write-Host "Teacher work root: $TeacherWorkRoot"
Write-Host "P1 receipt:        $p1Receipt"
Write-Host "P2 root:           $P2Root"
Write-Host "Source rehash:      NO"
Write-Host "Animation run:      NOT STARTED"
Write-Host "P2 acceptance:      FALSE"
Write-Host "Quest distillation: FALSE"
Write-Host "Production:         FALSE"
Write-Host "============================================================"
Write-Host ""

$argsList = @(
    "-m", "bodyrig.photoreal_p2_animation_plan",
    "--config", $teacherConfig,
    "--teacher-input", $teacherInput,
    "--teacher-workspace", $teacherWorkspace,
    "--p1-review-root", $p1ReviewRoot,
    "--p1-receipt", $p1Receipt,
    "--out", $plan,
    "--reuse-existing"
)
$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 animation plan failed with code $code."
}

$plan = Need-File -Path $plan -Label "P2 animation plan"
$value = Get-Content -LiteralPath $plan -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ($value.p2_animation_build_authorized -isnot [bool] -or $value.p2_animation_build_authorized -ne $true) {
    throw "P2 plan did not authorize animation build."
}
if ($value.p2_animated_teacher_acceptance_authority -isnot [bool] -or $value.p2_animated_teacher_acceptance_authority -ne $false) {
    throw "P2 plan crossed animated-teacher acceptance authority."
}
if ($value.quest_distillation_authorized -isnot [bool] -or $value.quest_distillation_authorized -ne $false) {
    throw "P2 plan crossed Quest-distillation authority."
}
if ($value.photoreal_acceptance_authority -isnot [bool] -or $value.photoreal_acceptance_authority -ne $false) {
    throw "P2 plan crossed photoreal acceptance authority."
}
if ($value.production_activation -isnot [bool] -or $value.production_activation -ne $false) {
    throw "P2 plan crossed production authority."
}

Write-Host ""
Write-Host "P2 animation build contract: AUTHORIZED"
Write-Host "Plan:                $plan"
Write-Host "Upstream animation:  $($value.animation_contract.upstream_script)"
Write-Host "Motion layout:"
Write-Host "  $($value.animation_contract.motion_path_layout.reference_frames)"
Write-Host "  $($value.animation_contract.motion_path_layout.camera_parameters)"
Write-Host "  $($value.animation_contract.motion_path_layout.smplx_parameters)"
Write-Host ""
Write-Host "Animation execution remains NOT STARTED."
Write-Host "Next authority boundary: provide hash-bound motion evidence, render the accepted teacher, then complete held-out human motion validation."
