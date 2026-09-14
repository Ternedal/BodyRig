from pathlib import Path

root = Path(__file__).resolve().parents[1]
review_path = root / "run-fidelity-evening-current-floor-review.ps1"
command_path = root / "run-fidelity-evening.ps1"
review = review_path.read_text(encoding="utf-8")
command = command_path.read_text(encoding="utf-8")

# Current-floor runner: add bool-safe persisted preview validation and exact reuse binding.
marker = "function Assert-SemanticallyEqualJson {\n"
if review.count(marker) != 1:
    raise SystemExit("current-floor semantic helper anchor drifted")
helpers = r'''function Test-V1Version($Value) {
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }
}
function Test-FaceSecondaryPreviewComplete {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [Parameter(Mandatory = $true)][string]$ExpectedSourcePackageSha,
        [Parameter(Mandatory = $true)][string]$ExpectedHairEyeReceiptSha,
        [Parameter(Mandatory = $true)][string]$ExpectedHairEyeVrmSha
    )
    try {
        $summaryPath = Join-Path $Path "face-secondary-hair-eye-preview.json"
        $runtimeReceipt = Join-Path $Path "runtime\face-secondary-hair-eye-review-runtime.json"
        $comparisonReceipt = Join-Path $Path "comparison\face-secondary-hair-eye-comparison.json"
        $comparisonPackage = Join-Path $Path "comparison\face-secondary-hair-eye-comparison.mrbody"
        $visibilityPath = Join-Path $Path "windows-preview\component-visibility-probe.json"
        $renderSetPath = Join-Path $Path "windows-preview\snapshots\fidelity-render-set.json"
        $gapPath = Join-Path $Path "component-gap-plan.json"
        foreach ($required in @($summaryPath,$runtimeReceipt,$comparisonReceipt,$comparisonPackage,$visibilityPath,$renderSetPath,$gapPath)) {
            if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { return $false }
        }
        $summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50
        if ([string]$summary.format -ne "bodyrig-face-secondary-hair-eye-windows-preview" -or
            -not (Test-V1Version $summary.version) -or [string]$summary.bodyrig_revision -ne $ExpectedHead -or
            [string]$summary.source_package_sha256 -ne $ExpectedSourcePackageSha -or
            [string]$summary.source_hair_eye_runtime_receipt_sha256 -ne $ExpectedHairEyeReceiptSha -or
            [string]$summary.source_hair_eye_review_vrm_sha256 -ne $ExpectedHairEyeVrmSha -or
            $summary.source_hair_preserved -ne $true -or $summary.source_eye_surface_preserved -ne $true -or
            $summary.face_secondary_drawable -ne $true -or $summary.comparison_only -ne $true -or
            $summary.physical_acceptance_authority -ne $false -or $summary.human_visual_authority_required -ne $true -or
            $summary.package_promotion_authority -ne $false -or $summary.production_activation -ne $false) { return $false }
        if ((Sha256 $runtimeReceipt) -ne [string]$summary.face_secondary_runtime_receipt_sha256 -or
            (Sha256 $comparisonReceipt) -ne [string]$summary.comparison_receipt_sha256 -or
            (Sha256 $comparisonPackage) -ne [string]$summary.comparison_package_sha256 -or
            (Sha256 $visibilityPath) -ne [string]$summary.component_visibility_probe_sha256 -or
            (Sha256 $renderSetPath) -ne [string]$summary.render_set_sha256 -or
            (Sha256 $gapPath) -ne [string]$summary.gap_plan_sha256) { return $false }
        return $true
    } catch { return $false }
}
'''
review = review.replace(marker, helpers + marker, 1)

runner_anchor = '$retainedPreview = Need-File -Path (Join-Path $repoRoot "run-retained-hair-eye-preview.ps1") -Label "Retained hair+eye preview runner"\n'
if review.count(runner_anchor) != 1:
    raise SystemExit("face-secondary runner insertion anchor drifted")
review = review.replace(
    runner_anchor,
    runner_anchor + '$faceSecondaryPreview = Need-File -Path (Join-Path $repoRoot "run-face-secondary-hair-eye-windows-preview.ps1") -Label "Face-secondary on hair+eye preview runner"\n',
    1,
)

start_token = '$visibilityPath = Need-File -Path (Join-Path $retainedOutput "windows-preview\\component-visibility-probe.json") -Label "Physical component visibility probe"\n'
end_token = 'Write-Host ""\nWrite-Host "=== 4/4 DIAGNOSTIC-ONLY V5 SCORE OF CURRENT-FLOOR HAIR + EYE PREVIEW ==="\n'
start = review.find(start_token)
end = review.find(end_token, start)
if start < 0 or end < 0:
    raise SystemExit("current-floor retained physical authority block drifted")
physical_block = r'''$retainedVisibilityPath = Need-File -Path (Join-Path $retainedOutput "windows-preview\component-visibility-probe.json") -Label "Retained component visibility probe"
$retainedRenderSet = Need-File -Path (Join-Path $retainedOutput "windows-preview\snapshots\fidelity-render-set.json") -Label "Current-floor retained preview render set"
$gapProbeCode = @'
import json,pathlib,sys
from bodyrig.fidelity_component_gap import build_gap_plan
visibility=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
render=json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
print(json.dumps(build_gap_plan(visibility,render_set=render),separators=(",",":"),allow_nan=False))
'@
$retainedGapRaw = @(& $BodyRigPython -c $gapProbeCode $retainedVisibilityPath $retainedRenderSet 2>&1)
if ($LASTEXITCODE -ne 0 -or $retainedGapRaw.Count -ne 1) { throw "Current-floor retained component evidence failed canonical gap validation: $($retainedGapRaw -join ' ')" }
try { $retainedGap = ([string]$retainedGapRaw[0]) | ConvertFrom-Json -Depth 30 } catch { throw "Canonical retained component-gap validation returned unreadable JSON." }
if ([string]$retainedGap.package_sha256 -ne $currentPackageSha -or [string]$retainedGap.bodyrig_revision -ne $head) { throw "Retained component gap authority targets different current-floor bytes/revision." }
$drawable = @($retainedGap.drawable_components | ForEach-Object { [string]$_ })
if (-not ($drawable -contains "hair") -or -not ($drawable -contains "eyes")) { throw "Current-floor retained preview lacks physically drawable hair/eyes authority." }
$retainedVisibility = Read-Json -Path $retainedVisibilityPath -Label "Retained component visibility probe"

$physicalAuthorityKind = "retained-hair-eye"
$physicalRoot = $retainedOutput
$physicalVisibilityPath = $retainedVisibilityPath
$physicalRenderSet = $retainedRenderSet
$physicalPackageSha = $currentPackageSha
$physicalComparisonPackageSha = ""
$faceSecondaryPreviewSummaryPath = ""
$physicalGap = $retainedGap
$physicalVisibility = $retainedVisibility
$physicalDrawable = @($drawable)

if (-not ($drawable -contains "face-secondary")) {
    $hairEyeRuntimeDir = Need-Directory -Path (Join-Path $retainedOutput "runtime") -Label "Retained hair+eye runtime"
    $hairEyeRuntimeReceipt = Need-File -Path (Join-Path $hairEyeRuntimeDir "source-hair-eye-review-runtime.json") -Label "Retained hair+eye runtime receipt"
    $hairEyeRuntimeVrm = Need-File -Path (Join-Path $hairEyeRuntimeDir "source-hair-eye-review.vrm") -Label "Retained hair+eye review VRM"
    $hairEyeRuntimeReceiptSha = Sha256 $hairEyeRuntimeReceipt
    $hairEyeRuntimeVrmSha = Sha256 $hairEyeRuntimeVrm
    $faceSecondaryOutput = Join-Path $eveningRoot "face-secondary-hair-eye-$selectedLabel"

    Write-Host ""
    Write-Host "=== 3B/4 FACE-SECONDARY ON RETAINED HAIR + EYES ==="
    if (Test-FaceSecondaryPreviewComplete -Path $faceSecondaryOutput -ExpectedHead $head -ExpectedSourcePackageSha $currentPackageSha -ExpectedHairEyeReceiptSha $hairEyeRuntimeReceiptSha -ExpectedHairEyeVrmSha $hairEyeRuntimeVrmSha) {
        Write-Host "Reusing exact face-secondary comparison preview: $faceSecondaryOutput"
    } else {
        if (Test-Path -LiteralPath $faceSecondaryOutput) { throw "Face-secondary comparison output exists but is incomplete/stale; refusing overwrite: $faceSecondaryOutput" }
        $faceArgs = @{
            PackagePath = $currentPackage
            HairEyeRuntimeDir = $hairEyeRuntimeDir
            OutputDir = $faceSecondaryOutput
            BodyRigPython = $BodyRigPython
        }
        if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $faceArgs.UnityExe = $UnityExe }
        if ($SkipBuild) { $faceArgs.SkipBuild = $true }
        & $faceSecondaryPreview @faceArgs
        if ($LASTEXITCODE -ne 0) { throw "Face-secondary hair+eye preview failed with exit code $LASTEXITCODE" }
        Assert-HeadPinned -RepoRoot $repoRoot -Expected $head
        if (-not (Test-FaceSecondaryPreviewComplete -Path $faceSecondaryOutput -ExpectedHead $head -ExpectedSourcePackageSha $currentPackageSha -ExpectedHairEyeReceiptSha $hairEyeRuntimeReceiptSha -ExpectedHairEyeVrmSha $hairEyeRuntimeVrmSha)) {
            throw "Face-secondary comparison preview returned without complete exact authority evidence."
        }
    }

    $faceSecondaryPreviewSummaryPath = Need-File -Path (Join-Path $faceSecondaryOutput "face-secondary-hair-eye-preview.json") -Label "Face-secondary comparison preview summary"
    $faceSecondarySummary = Read-Json -Path $faceSecondaryPreviewSummaryPath -Label "Face-secondary comparison preview summary"
    $physicalRoot = $faceSecondaryOutput
    $physicalAuthorityKind = "face-secondary-hair-eye-comparison"
    $physicalVisibilityPath = Need-File -Path (Join-Path $faceSecondaryOutput "windows-preview\component-visibility-probe.json") -Label "Face-secondary physical component visibility probe"
    $physicalRenderSet = Need-File -Path (Join-Path $faceSecondaryOutput "windows-preview\snapshots\fidelity-render-set.json") -Label "Face-secondary physical render set"
    $physicalComparisonPackage = Need-File -Path (Join-Path $faceSecondaryOutput "comparison\face-secondary-hair-eye-comparison.mrbody") -Label "Face-secondary physical comparison package"
    $physicalComparisonPackageSha = Sha256 $physicalComparisonPackage
    if ($physicalComparisonPackageSha -ne [string]$faceSecondarySummary.comparison_package_sha256) { throw "Face-secondary comparison package bytes differ from preview authority." }
    $physicalPackageSha = $physicalComparisonPackageSha
    $physicalGapRaw = @(& $BodyRigPython -c $gapProbeCode $physicalVisibilityPath $physicalRenderSet 2>&1)
    if ($LASTEXITCODE -ne 0 -or $physicalGapRaw.Count -ne 1) { throw "Face-secondary physical component evidence failed canonical gap validation: $($physicalGapRaw -join ' ')" }
    try { $physicalGap = ([string]$physicalGapRaw[0]) | ConvertFrom-Json -Depth 30 } catch { throw "Canonical face-secondary component-gap validation returned unreadable JSON." }
    if ([string]$physicalGap.package_sha256 -ne $physicalPackageSha -or [string]$physicalGap.bodyrig_revision -ne $head) { throw "Face-secondary component gap authority targets different comparison bytes/revision." }
    $physicalDrawable = @($physicalGap.drawable_components | ForEach-Object { [string]$_ })
    foreach ($required in @("hair","eyes","face-secondary")) {
        if (-not ($physicalDrawable -contains $required)) { throw "Face-secondary continuation lacks physically drawable $required authority." }
    }
    $physicalVisibility = Read-Json -Path $physicalVisibilityPath -Label "Face-secondary physical component visibility probe"
}

'''
review = review[:start] + physical_block + review[end:]

if review.count('        --render-set $renderSet `\n') != 1:
    raise SystemExit("diagnostic render-set anchor drifted")
review = review.replace('        --render-set $renderSet `\n', '        --render-set $retainedRenderSet `\n', 1)

summary_anchor = '    current_floor_package_sha256 = $currentPackageSha\n    selected_package_sha256 = $currentPackageSha\n'
if review.count(summary_anchor) != 1:
    raise SystemExit("current-floor summary package anchor drifted")
review = review.replace(
    summary_anchor,
    '    source_current_floor_package_sha256 = $currentPackageSha\n'
    '    current_floor_package_sha256 = $currentPackageSha\n'
    '    selected_package_sha256 = $currentPackageSha\n'
    '    physical_authority_kind = $physicalAuthorityKind\n'
    '    physical_component_package_sha256 = $physicalPackageSha\n'
    '    physical_comparison_package_sha256 = $physicalComparisonPackageSha\n',
    1,
)
probe_anchor = '    retained_preview_summary_sha256 = Sha256 (Need-File -Path (Join-Path $retainedOutput "retained-hair-eye-preview.json") -Label "Retained preview summary")\n    component_visibility_probe_sha256 = Sha256 $visibilityPath\n    diagnostic_evaluation_sha256 = Sha256 $diagnosticEvaluation\n'
if review.count(probe_anchor) != 1:
    raise SystemExit("current-floor summary probe anchor drifted")
review = review.replace(
    probe_anchor,
    '    retained_preview_summary_sha256 = Sha256 (Need-File -Path (Join-Path $retainedOutput "retained-hair-eye-preview.json") -Label "Retained preview summary")\n'
    '    retained_component_visibility_probe_sha256 = Sha256 $retainedVisibilityPath\n'
    '    retained_render_set_sha256 = Sha256 $retainedRenderSet\n'
    '    face_secondary_preview_summary_sha256 = $(if ([string]::IsNullOrWhiteSpace($faceSecondaryPreviewSummaryPath)) { "" } else { Sha256 $faceSecondaryPreviewSummaryPath })\n'
    '    component_visibility_probe_sha256 = Sha256 $physicalVisibilityPath\n'
    '    physical_component_visibility_probe_sha256 = Sha256 $physicalVisibilityPath\n'
    '    physical_render_set_sha256 = Sha256 $physicalRenderSet\n'
    '    diagnostic_evaluation_sha256 = Sha256 $diagnosticEvaluation\n',
    1,
)
visibility_anchor = '''    component_visibility = [ordered]@{
        hair = $drawable -contains "hair"
        eyes = $drawable -contains "eyes"
        face_secondary = $drawable -contains "face-secondary"
        fingernails = $drawable -contains "fingernails"
        toenails = $drawable -contains "toenails"
    }
    full_fidelity_component_complete = [bool]$visibility.all_required_present_and_visible
'''
if review.count(visibility_anchor) != 1:
    raise SystemExit("current-floor summary visibility anchor drifted")
review = review.replace(
    visibility_anchor,
    '''    component_visibility = [ordered]@{
        hair = $physicalDrawable -contains "hair"
        eyes = $physicalDrawable -contains "eyes"
        face_secondary = $physicalDrawable -contains "face-secondary"
        fingernails = $physicalDrawable -contains "fingernails"
        toenails = $physicalDrawable -contains "toenails"
    }
    full_fidelity_component_complete = [bool]$physicalVisibility.all_required_present_and_visible
''',
    1,
)
review = review.replace(
    '    semantics = "current-floor-retained-hair-eye-physical-preview-plus-diagnostic-score-not-full-fidelity-acceptance"\n',
    '    semantics = "current-floor-physical-component-continuation-plus-retained-diagnostic-score-not-full-fidelity-acceptance"\n',
    1,
)
review = review.replace('Write-Host "Current-floor SHA:$currentPackageSha"\n', 'Write-Host "Source package SHA:$currentPackageSha"\nWrite-Host "Physical package SHA:$physicalPackageSha"\nWrite-Host "Physical authority:$physicalAuthorityKind"\n', 1)
review = review.replace('Write-Host "Hair drawable:    $($drawable -contains \'hair\')"\nWrite-Host "Eyes drawable:    $($drawable -contains \'eyes\')"\nWrite-Host "All 5 drawable:   $([bool]$visibility.all_required_present_and_visible)"\n', 'Write-Host "Hair drawable:    $($physicalDrawable -contains \'hair\')"\nWrite-Host "Eyes drawable:    $($physicalDrawable -contains \'eyes\')"\nWrite-Host "Face drawable:    $($physicalDrawable -contains \'face-secondary\')"\nWrite-Host "All 5 drawable:   $([bool]$physicalVisibility.all_required_present_and_visible)"\n', 1)
review = review.replace('Write-Host "Snapshots:        $(Join-Path $retainedOutput \'windows-preview\\snapshots\')"\n', 'Write-Host "Snapshots:        $(Join-Path $physicalRoot \'windows-preview\\snapshots\')"\n', 1)
review = review.replace('if ($OpenSnapshots) { Start-Process explorer.exe -ArgumentList @((Join-Path $retainedOutput "windows-preview\\snapshots")) }\n', 'if ($OpenSnapshots) { Start-Process explorer.exe -ArgumentList @((Join-Path $physicalRoot "windows-preview\\snapshots")) }\n', 1)
review_path.write_text(review, encoding="utf-8", newline="\n")

# Top-level evening command: resolve and persist the same final physical authority.
command_marker = "function Read-Json {\n"
if command.count(command_marker) != 1:
    raise SystemExit("top-level Sha256 insertion anchor drifted")
command = command.replace(
    command_marker,
    '''function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath (Need-File -Path $Path -Label "Hash input") -Algorithm SHA256).Hash.ToLowerInvariant()
}
''' + command_marker,
    1,
)
selection_start = command.find('$retainedRoot = Need-Directory -Path (Join-Path $eveningRoot "retained-hair-eye-$selected") -Label "Current-floor retained preview"\n')
selection_end = command.find('$gapPath = Join-Path $eveningRoot "component-gap-plan.json"\n', selection_start)
if selection_start < 0 or selection_end < 0:
    raise SystemExit("top-level physical authority selection block drifted")
selection_block = r'''$retainedRoot = Need-Directory -Path (Join-Path $eveningRoot "retained-hair-eye-$selected") -Label "Current-floor retained preview"
$retainedVisibility = Need-File -Path (Join-Path $retainedRoot "windows-preview\component-visibility-probe.json") -Label "Retained Unity component visibility probe"
$retainedRenderSet = Need-File -Path (Join-Path $retainedRoot "windows-preview\snapshots\fidelity-render-set.json") -Label "Retained current-floor fidelity render set"
$sourcePackageSha = ([string]$summary.source_current_floor_package_sha256).Trim().ToLowerInvariant()
if ($sourcePackageSha -notmatch '^[0-9a-f]{64}$' -or $sourcePackageSha -ne ([string]$summary.current_floor_package_sha256).Trim().ToLowerInvariant()) {
    throw "Current-floor evening summary source package authority is invalid."
}
$physicalKind = ([string]$summary.physical_authority_kind).Trim()
$physicalPackageSha = ([string]$summary.physical_component_package_sha256).Trim().ToLowerInvariant()
if ($physicalPackageSha -notmatch '^[0-9a-f]{64}$') { throw "Current-floor evening summary physical package SHA is invalid." }
$physicalRoot = $retainedRoot
$visibility = $retainedVisibility
$renderSet = $retainedRenderSet
switch ($physicalKind) {
    "retained-hair-eye" {
        if ($physicalPackageSha -ne $sourcePackageSha -or -not [string]::IsNullOrWhiteSpace([string]$summary.physical_comparison_package_sha256)) {
            throw "Retained physical authority disagrees with current-floor source package authority."
        }
    }
    "face-secondary-hair-eye-comparison" {
        $physicalRoot = Need-Directory -Path (Join-Path $eveningRoot "face-secondary-hair-eye-$selected") -Label "Face-secondary physical comparison preview"
        $visibility = Need-File -Path (Join-Path $physicalRoot "windows-preview\component-visibility-probe.json") -Label "Face-secondary Unity component visibility probe"
        $renderSet = Need-File -Path (Join-Path $physicalRoot "windows-preview\snapshots\fidelity-render-set.json") -Label "Face-secondary fidelity render set"
        $comparisonPackage = Need-File -Path (Join-Path $physicalRoot "comparison\face-secondary-hair-eye-comparison.mrbody") -Label "Face-secondary physical comparison package"
        $comparisonSha = Sha256 $comparisonPackage
        if ($comparisonSha -ne $physicalPackageSha -or $comparisonSha -ne ([string]$summary.physical_comparison_package_sha256).Trim().ToLowerInvariant()) {
            throw "Face-secondary physical comparison package differs from evening summary authority."
        }
        $faceSummary = Need-File -Path (Join-Path $physicalRoot "face-secondary-hair-eye-preview.json") -Label "Face-secondary preview summary"
        if ((Sha256 $faceSummary) -ne ([string]$summary.face_secondary_preview_summary_sha256).Trim().ToLowerInvariant()) {
            throw "Face-secondary preview summary bytes differ from evening summary authority."
        }
    }
    default { throw "Current-floor evening summary physical_authority_kind is invalid: $physicalKind" }
}
if ((Sha256 $visibility) -ne ([string]$summary.physical_component_visibility_probe_sha256).Trim().ToLowerInvariant() -or
    (Sha256 $visibility) -ne ([string]$summary.component_visibility_probe_sha256).Trim().ToLowerInvariant() -or
    (Sha256 $renderSet) -ne ([string]$summary.physical_render_set_sha256).Trim().ToLowerInvariant()) {
    throw "Final physical probe/render bytes differ from evening summary authority."
}
'''
command = command[:selection_start] + selection_block + command[selection_end:]

old_reuse = '''    if (Test-Path -LiteralPath $gapPath -PathType Leaf) {
        $existingGap = Read-Json -Path $gapPath -Label "Existing current-floor component gap plan"
        Assert-SemanticallyEqualJson -Expected $freshGap -Actual $existingGap -Label "Existing current-floor component gap plan"
        Write-Host "Revalidated existing component gap plan: $gapPath"
    } else {
        Move-Item -LiteralPath $gapAttempt -Destination $gapPath
        $gapAttempt = ""
    }
'''
if command.count(old_reuse) != 1:
    raise SystemExit("top-level gap reuse block drifted")
new_reuse = r'''    if (Test-Path -LiteralPath $gapPath -PathType Leaf) {
        $existingGap = Read-Json -Path $gapPath -Label "Existing current-floor component gap plan"
        $samePhysicalGap = $false
        try {
            Assert-SemanticallyEqualJson -Expected $freshGap -Actual $existingGap -Label "Existing current-floor component gap plan"
            $samePhysicalGap = $true
        } catch {
            if ($physicalKind -ne "face-secondary-hair-eye-comparison") { throw }
        }
        if ($samePhysicalGap) {
            Write-Host "Revalidated existing component gap plan: $gapPath"
        } else {
            $retainedGapAttempt = Join-Path $eveningRoot (".component-gap-plan.retained-verify-" + [Guid]::NewGuid().ToString("N") + ".json")
            try {
                & $BodyRigPython -m bodyrig.fidelity_component_gap `
                    --visibility-probe $retainedVisibility `
                    --render-set $retainedRenderSet `
                    --out $retainedGapAttempt | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "Retained predecessor gap recomputation failed with exit code $LASTEXITCODE" }
                $freshRetainedGap = Read-Json -Path $retainedGapAttempt -Label "Fresh retained predecessor component gap plan"
                Assert-SemanticallyEqualJson -Expected $freshRetainedGap -Actual $existingGap -Label "Existing retained predecessor component gap plan"
            } finally {
                if (Test-Path -LiteralPath $retainedGapAttempt -PathType Leaf) { Remove-Item -LiteralPath $retainedGapAttempt -Force -ErrorAction SilentlyContinue }
            }
            $predecessorPath = Join-Path $eveningRoot "component-gap-plan.retained-hair-eye.json"
            if (Test-Path -LiteralPath $predecessorPath -PathType Leaf) {
                $archivedPredecessor = Read-Json -Path $predecessorPath -Label "Archived retained predecessor component gap plan"
                Assert-SemanticallyEqualJson -Expected $existingGap -Actual $archivedPredecessor -Label "Archived retained predecessor component gap plan"
                Remove-Item -LiteralPath $gapPath -Force
            } else {
                Move-Item -LiteralPath $gapPath -Destination $predecessorPath
            }
            Move-Item -LiteralPath $gapAttempt -Destination $gapPath
            $gapAttempt = ""
            Write-Host "Advanced persisted component gap from exact retained predecessor to face-secondary physical authority: $gapPath"
        }
    } else {
        Move-Item -LiteralPath $gapAttempt -Destination $gapPath
        $gapAttempt = ""
    }
'''
command = command.replace(old_reuse, new_reuse, 1)

old_guard = '[string]$gap.bodyrig_revision -ne $head -or [string]$gap.package_sha256 -ne [string]$summary.current_floor_package_sha256 -or\n'
if command.count(old_guard) != 1:
    raise SystemExit("top-level physical gap package guard drifted")
command = command.replace(old_guard, '[string]$gap.bodyrig_revision -ne $head -or [string]$gap.package_sha256 -ne $physicalPackageSha -or\n', 1)
command = command.replace('$snapshotDir = Need-Directory -Path (Join-Path $retainedRoot "windows-preview\\snapshots") -Label "Current-floor snapshot directory"\n', '$snapshotDir = Need-Directory -Path (Join-Path $physicalRoot "windows-preview\\snapshots") -Label "Final physical snapshot directory"\n', 1)
command = command.replace('Write-Host "Candidate:       $selected"\n', 'Write-Host "Candidate:       $selected"\nWrite-Host "Source package:  $sourcePackageSha"\nWrite-Host "Physical kind:   $physicalKind"\nWrite-Host "Physical package:$physicalPackageSha"\n', 1)
command_path.write_text(command, encoding="utf-8", newline="\n")

# Existing command regression now binds the gap to final physical bytes.
test_command_path = root / "tests" / "test_fidelity_evening_command.py"
test_command = test_command_path.read_text(encoding="utf-8")
old_test = "    assert '[string]$gap.package_sha256 -ne [string]$summary.current_floor_package_sha256' in text\n"
if test_command.count(old_test) != 1:
    raise SystemExit("existing evening command regression anchor drifted")
test_command = test_command.replace(old_test, "    assert '[string]$gap.package_sha256 -ne $physicalPackageSha' in text\n", 1)
test_command_path.write_text(test_command, encoding="utf-8", newline="\n")

new_test = root / "tests" / "test_fidelity_evening_face_secondary_continuation.py"
if new_test.exists():
    raise SystemExit("face-secondary evening continuation regression already exists")
new_test.write_text('''from pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\nCURRENT = (ROOT / "run-fidelity-evening-current-floor-review.ps1").read_text(encoding="utf-8")\nTOP = (ROOT / "run-fidelity-evening.ps1").read_text(encoding="utf-8")\n\n\ndef test_current_floor_automatically_advances_missing_face_secondary() -> None:\n    assert "run-face-secondary-hair-eye-windows-preview.ps1" in CURRENT\n    assert 'if (-not ($drawable -contains "face-secondary"))' in CURRENT\n    assert "PackagePath = $currentPackage" in CURRENT\n    assert "HairEyeRuntimeDir = $hairEyeRuntimeDir" in CURRENT\n    assert "Face-secondary hair+eye preview failed" in CURRENT\n    assert "Face-secondary continuation lacks physically drawable $required authority." in CURRENT\n\n\ndef test_face_secondary_reuse_is_exact_hash_bound_and_review_only() -> None:\n    for token in (\n        "ExpectedSourcePackageSha",\n        "ExpectedHairEyeReceiptSha",\n        "ExpectedHairEyeVrmSha",\n        "face_secondary_runtime_receipt_sha256",\n        "comparison_receipt_sha256",\n        "comparison_package_sha256",\n        "component_visibility_probe_sha256",\n        "render_set_sha256",\n        "gap_plan_sha256",\n        "$summary.physical_acceptance_authority -ne $false",\n        "$summary.human_visual_authority_required -ne $true",\n        "$summary.package_promotion_authority -ne $false",\n        "$summary.production_activation -ne $false",\n    ):\n        assert token in CURRENT\n\n\ndef test_diagnostic_score_stays_on_source_package_and_retained_render_set() -> None:\n    diagnostic = CURRENT.index("=== 4/4 DIAGNOSTIC-ONLY V5 SCORE")\n    render = CURRENT.index("--render-set $retainedRenderSet", diagnostic)\n    package_check = CURRENT.index("Diagnostic evaluation targets different current-floor package bytes.", render)\n    assert render < package_check\n    assert "--render-set $physicalRenderSet" not in CURRENT\n    assert "physical_comparison_package_sha256 = $physicalComparisonPackageSha" in CURRENT\n    assert "source_current_floor_package_sha256 = $currentPackageSha" in CURRENT\n\n\ndef test_summary_component_state_uses_final_physical_authority() -> None:\n    assert "physical_authority_kind = $physicalAuthorityKind" in CURRENT\n    assert "physical_component_package_sha256 = $physicalPackageSha" in CURRENT\n    assert "physical_component_visibility_probe_sha256 = Sha256 $physicalVisibilityPath" in CURRENT\n    assert "physical_render_set_sha256 = Sha256 $physicalRenderSet" in CURRENT\n    assert 'hair = $physicalDrawable -contains "hair"' in CURRENT\n    assert 'face_secondary = $physicalDrawable -contains "face-secondary"' in CURRENT\n    assert "full_fidelity_component_complete = [bool]$physicalVisibility.all_required_present_and_visible" in CURRENT\n\n\ndef test_top_level_recomputes_gap_from_final_physical_authority() -> None:\n    assert '"face-secondary-hair-eye-comparison"' in TOP\n    assert "face-secondary-hair-eye-$selected" in TOP\n    assert "physical_component_package_sha256" in TOP\n    assert "physical_component_visibility_probe_sha256" in TOP\n    assert "physical_render_set_sha256" in TOP\n    assert "--visibility-probe $visibility" in TOP\n    assert "--render-set $renderSet" in TOP\n    assert '[string]$gap.package_sha256 -ne $physicalPackageSha' in TOP\n    assert "Join-Path $physicalRoot \"windows-preview\\\\snapshots\"" in TOP\n\n\ndef test_top_level_only_advances_a_proven_exact_retained_predecessor_gap() -> None:\n    assert "Fresh retained predecessor component gap plan" in TOP\n    assert "Existing retained predecessor component gap plan" in TOP\n    assert "component-gap-plan.retained-hair-eye.json" in TOP\n    assert "Advanced persisted component gap from exact retained predecessor" in TOP\n\n\ndef test_evening_continuation_keeps_hfn_human_and_release_boundaries() -> None:\n    assert "physical_acceptance_authority = $false" in CURRENT\n    assert "human_visual_authority_required = $true" in CURRENT\n    assert "production_activation = $false" in CURRENT\n    for forbidden in (\n        "clone-body-from-stash",\n        "run-profiled-fidelity-convergence",\n        '"-m", "bodyrig.sith_reconstruct"',\n        "reconstruct_sith(",\n        "promote-high-fidelity-face-secondary",\n    ):\n        assert forbidden not in CURRENT\n''', encoding="utf-8", newline="\n")
