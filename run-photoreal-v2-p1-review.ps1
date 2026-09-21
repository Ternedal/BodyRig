param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$AppearanceReviewRoot,
    [string]$BodyRigPython = "",
    [string[]]$SemanticMap = @(),
    [string[]]$Pair = @(),
    [string[]]$Decision = @(),
    [string]$ReviewedBy = "",
    [string]$SemanticReviewNotes = "",
    [string]$PairingReviewNotes = "",
    [string]$LikenessReviewNotes = "",
    [switch]$ApproveSemanticReview,
    [switch]$ApprovePairingReview,
    [switch]$ConfirmLikenessReview
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

function Invoke-BodyRigPython {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label,
        [int[]]$AllowedExitCodes = @(0)
    )
    $output = @(& $Python @Arguments 2>&1)
    $code = $LASTEXITCODE
    foreach ($line in $output) { Write-Host ([string]$line) }
    if ($AllowedExitCodes -notcontains $code) {
        throw "$Label failed with code $code."
    }
    return [int]$code
}

function Need-Reviewer {
    if ([string]::IsNullOrWhiteSpace($ReviewedBy)) {
        throw "Human review action requires -ReviewedBy."
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1 -or ([string]$branch[0]).Trim() -ne "main") {
    throw "P1 static-teacher review operator requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P1 static-teacher review operator requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$AppearanceReviewRoot = Need-Directory -Path $AppearanceReviewRoot -Label "Appearance review root"
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

$teacherInput = Need-File -Path (Join-Path $TeacherWorkRoot "teacher-input.json") -Label "Strict teacher input"
$teacherConfig = Need-File -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-config.json") -Label "ExAvatar teacher config"
$teacherWorkspace = Need-Directory -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-output") -Label "ExAvatar teacher workspace"
$teacherResultRoot = Need-Directory -Path (Join-Path $teacherWorkspace "output") -Label "ExAvatar teacher result root"
Need-File -Path (Join-Path $teacherResultRoot "teacher-manifest.json") -Label "ExAvatar teacher manifest" | Out-Null

$appearanceManifest = Need-File -Path (Join-Path $AppearanceReviewRoot "appearance-epoch-visual-review-manifest.json") -Label "Appearance review manifest"
$appearanceHtml = Need-File -Path (Join-Path $AppearanceReviewRoot "review-index.html") -Label "Appearance review HTML"

$p1Root = Join-Path $TeacherWorkRoot "p1-static-teacher-review"
New-Item -ItemType Directory -Path $p1Root -Force | Out-Null

$semanticHandoff = Join-Path $p1Root "semantic-camera-alignment-handoff.json"
$semanticReceipt = Join-Path $p1Root "semantic-camera-alignment.json"
$pairingHandoff = Join-Path $p1Root "heldout-pairing-handoff.json"
$pairingReceipt = Join-Path $p1Root "heldout-pairing.json"
$likenessRoot = Join-Path $p1Root "likeness-review"
$likenessReceipt = Join-Path $p1Root "p1-likeness-review.json"

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P1 STATIC TEACHER REVIEW"
Write-Host "Teacher work root:  $TeacherWorkRoot"
Write-Host "Appearance review:  $AppearanceReviewRoot"
Write-Host "P1 work root:       $p1Root"
Write-Host "Human review:       REQUIRED"
Write-Host "Production:         FALSE"
Write-Host "============================================================"
Write-Host ""

if (-not (Test-Path -LiteralPath $semanticReceipt -PathType Leaf)) {
    Write-Host "=== 1/3 SEMANTIC CAMERA ALIGNMENT ==="
    $semanticHandoffArgs = @(
        "-m", "bodyrig.photoreal_teacher_semantic_alignment",
        "handoff",
        "--config", $teacherConfig,
        "--teacher-input", $teacherInput,
        "--teacher-workspace", $teacherWorkspace,
        "--out", $semanticHandoff
    )
    Invoke-BodyRigPython -Python $Python -Arguments $semanticHandoffArgs -Label "Semantic camera alignment handoff" -AllowedExitCodes @(0,2) | Out-Null

    if (-not $ApproveSemanticReview) {
        Write-Host ""
        Write-Host "HUMAN REVIEW REQUIRED: semantic camera alignment"
        Write-Host "Review the 50 neutral teacher renders under:"
        Write-Host "  $(Join-Path $teacherResultRoot 'review\neutral-pose')"
        Write-Host "Then rerun with:"
        Write-Host "  -ApproveSemanticReview -ReviewedBy <name>"
        Write-Host "  -SemanticMap 'front=<index>' ... for all required labels"
        Write-Host "No likeness/P1 authority has been granted."
        exit 2
    }

    Need-Reviewer
    if ($SemanticMap.Count -eq 0) { throw "-ApproveSemanticReview requires -SemanticMap entries." }
    if ([string]::IsNullOrWhiteSpace($SemanticReviewNotes)) {
        throw "-ApproveSemanticReview requires -SemanticReviewNotes."
    }
    $semanticRecordArgs = @(
        "-m", "bodyrig.photoreal_teacher_semantic_alignment",
        "record",
        "--config", $teacherConfig,
        "--teacher-input", $teacherInput,
        "--teacher-workspace", $teacherWorkspace,
        "--handoff", $semanticHandoff,
        "--reviewed-by", $ReviewedBy,
        "--review-notes", $SemanticReviewNotes,
        "--approve-human-review",
        "--out", $semanticReceipt
    )
    foreach ($mapping in $SemanticMap) {
        $semanticRecordArgs += @("--map", $mapping)
    }
    Invoke-BodyRigPython -Python $Python -Arguments $semanticRecordArgs -Label "Semantic camera alignment record" | Out-Null
}
$semanticReceipt = Need-File -Path $semanticReceipt -Label "Semantic camera alignment receipt"

if (-not (Test-Path -LiteralPath $pairingReceipt -PathType Leaf)) {
    Write-Host ""
    Write-Host "=== 2/3 HELD-OUT TEACHER / REFERENCE PAIRING ==="
    $pairingHandoffArgs = @(
        "-m", "bodyrig.photoreal_p1_heldout_pairing",
        "handoff",
        "--teacher-input", $teacherInput,
        "--semantic-alignment", $semanticReceipt,
        "--appearance-review-manifest", $appearanceManifest,
        "--appearance-review-root", $AppearanceReviewRoot,
        "--out", $pairingHandoff
    )
    Invoke-BodyRigPython -Python $Python -Arguments $pairingHandoffArgs -Label "P1 held-out pairing handoff" -AllowedExitCodes @(0,2) | Out-Null

    if (-not $ApprovePairingReview) {
        Write-Host ""
        Write-Host "HUMAN REVIEW REQUIRED: P1 held-out evidence pairing"
        Write-Host "Appearance evidence: $appearanceHtml"
        Write-Host "Pairing handoff:      $pairingHandoff"
        Write-Host "Then rerun with:"
        Write-Host "  -ApprovePairingReview -ReviewedBy <name>"
        Write-Host "  -Pair 'criterion=semantic-label=frame-id' ... for every required criterion"
        Write-Host "No likeness/P1 authority has been granted."
        exit 2
    }

    Need-Reviewer
    if ($Pair.Count -eq 0) { throw "-ApprovePairingReview requires -Pair entries." }
    if ([string]::IsNullOrWhiteSpace($PairingReviewNotes)) {
        throw "-ApprovePairingReview requires -PairingReviewNotes."
    }
    $pairingRecordArgs = @(
        "-m", "bodyrig.photoreal_p1_heldout_pairing",
        "record",
        "--handoff", $pairingHandoff,
        "--reviewed-by", $ReviewedBy,
        "--review-notes", $PairingReviewNotes,
        "--approve-human-review",
        "--out", $pairingReceipt
    )
    foreach ($selection in $Pair) {
        $pairingRecordArgs += @("--pair", $selection)
    }
    Invoke-BodyRigPython -Python $Python -Arguments $pairingRecordArgs -Label "P1 held-out pairing record" | Out-Null
}
$pairingReceipt = Need-File -Path $pairingReceipt -Label "P1 held-out pairing receipt"

if (-not (Test-Path -LiteralPath $likenessReceipt -PathType Leaf)) {
    Write-Host ""
    Write-Host "=== 3/3 P1 HUMAN LIKENESS REVIEW ==="
    $likenessPrepareArgs = @(
        "-m", "bodyrig.photoreal_p1_likeness_review",
        "prepare",
        "--pairing", $pairingReceipt,
        "--teacher-output-root", $teacherResultRoot,
        "--appearance-review-root", $AppearanceReviewRoot,
        "--out", $likenessRoot,
        "--reuse-existing"
    )
    Invoke-BodyRigPython -Python $Python -Arguments $likenessPrepareArgs -Label "P1 likeness review pack" -AllowedExitCodes @(0,2) | Out-Null
    $likenessHtml = Need-File -Path (Join-Path $likenessRoot "review-index.html") -Label "P1 likeness review HTML"

    if (-not $ConfirmLikenessReview) {
        Write-Host ""
        Write-Host "HUMAN REVIEW REQUIRED: final P1 static-teacher likeness"
        Write-Host "Review HTML:"
        Write-Host "  $likenessHtml"
        Write-Host "Open manually when ready:"
        Write-Host ('  Start-Process "' + $likenessHtml + '"')
        Write-Host "Then rerun with:"
        Write-Host "  -ConfirmLikenessReview -ReviewedBy <name>"
        Write-Host "  -Decision 'criterion=pass|fail' ... for EVERY criterion"
        Write-Host "Any FAIL keeps P2 blocked."
        exit 2
    }

    Need-Reviewer
    if ($Decision.Count -eq 0) { throw "-ConfirmLikenessReview requires -Decision entries." }
    if ([string]::IsNullOrWhiteSpace($LikenessReviewNotes)) {
        throw "-ConfirmLikenessReview requires -LikenessReviewNotes."
    }
    $likenessRecordArgs = @(
        "-m", "bodyrig.photoreal_p1_likeness_review",
        "record",
        "--review-root", $likenessRoot,
        "--reviewed-by", $ReviewedBy,
        "--review-notes", $LikenessReviewNotes,
        "--confirm-review-complete",
        "--out", $likenessReceipt
    )
    foreach ($decision in $Decision) {
        $likenessRecordArgs += @("--decision", $decision)
    }
    Invoke-BodyRigPython -Python $Python -Arguments $likenessRecordArgs -Label "P1 likeness review record" | Out-Null
}

$likenessReceipt = Need-File -Path $likenessReceipt -Label "P1 likeness review receipt"
$statusCode = @'
import json
import sys
from pathlib import Path
repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo))
from bodyrig.photoreal_p1_likeness_review import validate_likeness_review_receipt
receipt = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
manifest = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8-sig"))
value = validate_likeness_review_receipt(receipt, review_manifest=manifest)
print(json.dumps({
    "status": value["p1_static_teacher_status"],
    "p1_static_teacher_acceptance_authority": value["p1_static_teacher_acceptance_authority"],
    "human_visual_likeness_acceptance": value["human_visual_likeness_acceptance"],
    "p2_animation_authorized": value["p2_animation_authorized"],
    "photoreal_acceptance_authority": value["photoreal_acceptance_authority"],
    "production_activation": value["production_activation"],
}, sort_keys=True, separators=(",", ":")))
'@
$likenessManifest = Need-File -Path (Join-Path $likenessRoot "p1-likeness-review-manifest.json") -Label "P1 likeness review manifest"
$final = @(& $Python -c $statusCode $repoRoot $likenessReceipt $likenessManifest 2>&1)
if ($LASTEXITCODE -ne 0 -or $final.Count -ne 1) {
    throw "Final P1 likeness receipt validation failed: $($final -join ' ')"
}
$status = ([string]$final[0]) | ConvertFrom-Json

Write-Host ""
if ([string]$status.status -eq "pass") {
    Write-Host "BODYRIG PHOTOREAL V2 P1: PASS"
    Write-Host "P2 animation:       AUTHORIZED"
} else {
    Write-Host "BODYRIG PHOTOREAL V2 P1: FAIL"
    Write-Host "P2 animation:       BLOCKED"
}
Write-Host "P1 receipt:         $likenessReceipt"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:          FALSE"
