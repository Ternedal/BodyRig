param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [string]$Rebuild1IdentityWorkspace = "",
    [string]$Rebuild2IdentityWorkspace = "",
    [string]$IdentityRoot = "",
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
    [string]$ExecutionContext = "",
    [string]$HfnPersonId = "",
    [string]$HfnBodyRevision = "",
    [switch]$ExecuteNextAction,
    [switch]$SkipBuild,
    [switch]$OpenSnapshots
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
    $resolved = Need-File -Path $Path -Label $Label
    try { return Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
    catch { throw "$Label is unreadable JSON: $resolved" }
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath (Need-File -Path $Path -Label "Hash input") -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
}
function Test-V1Version {
    param($Value)
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }
}
function Assert-SemanticallyEqualJson {
    param([Parameter(Mandatory = $true)]$Expected,[Parameter(Mandatory = $true)]$Actual,[Parameter(Mandatory = $true)][string]$Label)
    $expectedText = $Expected | ConvertTo-Json -Depth 50 -Compress
    $actualText = $Actual | ConvertTo-Json -Depth 50 -Compress
    if ($expectedText -ne $actualText) { throw "$Label differs from freshly recomputed authority; refusing stale/tampered reuse." }
}

function Resolve-CanonicalPersonLibrary {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $RepoRoot
        $probeCode = 'import json,pathlib,bodyrig; from bodyrig.storage import person_library; print(json.dumps({"module":str(pathlib.Path(bodyrig.__file__).resolve()),"root":str(person_library())},separators=(",",":")))'
        $raw = @(& $Python -c $probeCode 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) {
            throw "Could not resolve canonical BodyRig person library from the current checkout."
        }
        try { $probe = ([string]$raw[0]) | ConvertFrom-Json -Depth 10 }
        catch { throw "Canonical BodyRig person-library probe returned unreadable JSON." }
        $moduleText = ([string]$probe.module).Trim()
        $rootText = ([string]$probe.root).Trim()
        if ([string]::IsNullOrWhiteSpace($moduleText) -or [string]::IsNullOrWhiteSpace($rootText)) {
            throw "Canonical BodyRig person-library probe returned empty authority."
        }
        $modulePath = [IO.Path]::GetFullPath($moduleText)
        $expectedModulePath = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\__init__.py"))
        if (-not [string]::Equals($modulePath, $expectedModulePath, [StringComparison]::OrdinalIgnoreCase)) {
            throw "BodyRig Python did not import the exact current-checkout package: $modulePath"
        }
        return Need-Directory -Path $rootText -Label "Canonical BodyRig person library root"
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }
}

function Invoke-GapExecutor {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$PlanPath,
        [Parameter(Mandatory = $true)][string]$ContextPath,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$Execute
    )
    $arguments = @(
        "-m", "bodyrig.fidelity_component_gap_executor",
        "--plan", $PlanPath,
        "--context", $ContextPath,
        "--repo-root", $RepoRoot
    )
    if ($Execute) { $arguments += "--execute" }
    $raw = @(& $Python @arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Component-gap executor failed with exit code $LASTEXITCODE`: $($raw -join ' ')" }
    if ($raw.Count -ne 1) { throw "Component-gap executor returned unexpected non-JSON output." }
    try { return ([string]$raw[0]) | ConvertFrom-Json -Depth 50 }
    catch { throw "Component-gap executor returned unreadable JSON." }
}
function Assert-GapExecutorResult {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [Parameter(Mandatory = $true)][string]$ExpectedBodyId,
        [Parameter(Mandatory = $true)][string]$ExpectedPackageSha,
        [Parameter(Mandatory = $true)][string]$ExpectedActionId,
        [switch]$ExecutionRequested
    )
    if ([string]$Value.format -ne "bodyrig-fidelity-component-gap-execution" -or -not (Test-V1Version $Value.version) -or
        [string]$Value.bodyrig_revision -ne $ExpectedHead -or [string]$Value.body_id -ne $ExpectedBodyId -or
        [string]$Value.source_gap_package_sha256 -ne $ExpectedPackageSha -or [string]$Value.action_id -ne $ExpectedActionId -or
        $Value.human_visual_authority_required -ne $true -or $Value.production_activation -ne $false) {
        throw "Component-gap executor result targets different plan/package/revision authority or crossed its review-only boundary."
    }
    $mode = ([string]$Value.mode).Trim()
    $hasExecuted = $Value.PSObject.Properties.Name -contains "executed"
    $hasExitCode = $Value.PSObject.Properties.Name -contains "exit_code"
    if ($mode -eq "operator-stop") {
        if ($Value.operator_input_required -ne $true -or $Value.reprobe_required_after_execution -ne $false -or
            [string]::IsNullOrWhiteSpace([string]$Value.reason) -or $hasExecuted -or $hasExitCode) {
            throw "Component-gap executor operator-stop result crossed its authority boundary."
        }
        return $mode
    }
    if ($mode -ne "machine-executable" -or $Value.operator_input_required -ne $false -or
        $Value.reprobe_required_after_execution -ne $true) {
        throw "Component-gap executor returned an unsupported execution mode/boundary."
    }
    if ($ExecutionRequested) {
        if (-not $hasExecuted -or -not $hasExitCode -or $Value.executed -ne $true) {
            throw "Component-gap executor did not confirm the requested one-step execution."
        }
        if ($Value.exit_code -is [bool] -or $Value.exit_code -isnot [ValueType]) {
            throw "Component-gap executor exit_code is not exact numeric zero."
        }
        try { $exitCode = [decimal]$Value.exit_code } catch { throw "Component-gap executor exit_code is not numeric." }
        if ($exitCode -ne [decimal]0) { throw "Component-gap executor reported non-zero execution status." }
    } elseif ($hasExecuted -or $hasExitCode) {
        throw "Dry-run component-gap routing unexpectedly executed work."
    }
    return $mode
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig evening command is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "BodyRig evening command must run from canonical main."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "BodyRig evening command requires a clean checkout." }

$WorkRoot = Need-Directory -Path $WorkRoot -Label "Fidelity convergence work root"
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$currentFloorRunner = Need-File -Path (Join-Path $repoRoot "run-fidelity-evening-current-floor-review.ps1") -Label "Current-floor evening review runner"

$runnerArgs = @{
    WorkRoot = $WorkRoot
    BodyRigPython = $BodyRigPython
}
if (-not [string]::IsNullOrWhiteSpace($Rebuild1IdentityWorkspace)) { $runnerArgs.Rebuild1IdentityWorkspace = $Rebuild1IdentityWorkspace }
if (-not [string]::IsNullOrWhiteSpace($Rebuild2IdentityWorkspace)) { $runnerArgs.Rebuild2IdentityWorkspace = $Rebuild2IdentityWorkspace }
if (-not [string]::IsNullOrWhiteSpace($IdentityRoot)) { $runnerArgs.IdentityRoot = $IdentityRoot }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $runnerArgs.UnityExe = $UnityExe }
if ($SkipBuild) { $runnerArgs.SkipBuild = $true }

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG QUALIFIED EVENING COMMAND"
Write-Host "Revision: $head"
Write-Host "============================================================"

& $currentFloorRunner @runnerArgs
if ($LASTEXITCODE -ne 0) { throw "Current-floor evening review failed with exit code $LASTEXITCODE" }

$headAfterRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
$dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $headAfterRaw.Count -ne 1 -or ([string]$headAfterRaw[0]).Trim().ToLowerInvariant() -ne $head -or $dirtyAfter.Count -gt 0) {
    throw "BodyRig checkout changed during qualified evening command."
}

$tag = $head.Substring(0, 8)
$eveningRoot = Need-Directory -Path (Join-Path $WorkRoot "evening-current-floor-$tag") -Label "Current-floor evening output"
$summaryPath = Need-File -Path (Join-Path $eveningRoot "evening-review-summary.json") -Label "Current-floor evening summary"
$summary = Read-Json -Path $summaryPath -Label "Current-floor evening summary"
if ([string]$summary.format -ne "bodyrig-fidelity-current-floor-evening-review" -or -not (Test-V1Version $summary.version) -or
    [string]$summary.bodyrig_revision -ne $head -or $summary.current_floor_refit_repackage -ne $true -or
    $summary.expensive_reconstruction_rerun -ne $false -or $summary.diagnostic_only -ne $true -or
    $summary.physical_acceptance_authority -ne $false -or $summary.human_visual_authority_required -ne $true -or
    $summary.production_activation -ne $false) {
    throw "Current-floor evening summary crossed its diagnostic/human-review authority boundary."
}
$selected = ([string]$summary.selected_candidate).Trim()
if ($selected -notin @("baseline","refit1","reconstruction2")) { throw "Current-floor evening summary selected_candidate is invalid." }

$retainedRoot = Need-Directory -Path (Join-Path $eveningRoot "retained-hair-eye-$selected") -Label "Current-floor retained preview"
$retainedVisibility = Need-File -Path (Join-Path $retainedRoot "windows-preview\component-visibility-probe.json") -Label "Retained Unity component visibility probe"
$retainedRenderSet = Need-File -Path (Join-Path $retainedRoot "windows-preview\snapshots\fidelity-render-set.json") -Label "Retained current-floor fidelity render set"
$currentFloorPackageSha = Need-Sha256 -Value ([string]$summary.current_floor_package_sha256) -Label "Current-floor package SHA-256"
$sourceCurrentFloorPackageSha = Need-Sha256 -Value ([string]$summary.source_current_floor_package_sha256) -Label "Source current-floor package SHA-256"
if ($sourceCurrentFloorPackageSha -ne $currentFloorPackageSha) { throw "Current-floor source package summary authority disagrees with current-floor package bytes." }
$physicalPackageSha = Need-Sha256 -Value ([string]$summary.physical_component_authority_package_sha256) -Label "Physical component authority package SHA-256"
$explicitPhysicalPackageSha = Need-Sha256 -Value ([string]$summary.physical_component_package_sha256) -Label "Explicit physical component package SHA-256"
if ($physicalPackageSha -ne $explicitPhysicalPackageSha) { throw "Physical component package summary authorities disagree." }
$physicalKind = ([string]$summary.physical_authority_kind).Trim()
$physicalRoot = $retainedRoot
$faceSummarySha = ([string]$summary.face_secondary_preview_summary_sha256).Trim().ToLowerInvariant()
if ($physicalKind -eq "face-secondary-hair-eye-comparison") {
    if ([string]::IsNullOrWhiteSpace($faceSummarySha)) { throw "Face-secondary physical authority lacks its bound preview summary." }
    $faceSummarySha = Need-Sha256 -Value $faceSummarySha -Label "Face-secondary preview summary SHA-256"
    $faceRoot = Need-Directory -Path (Join-Path $eveningRoot "face-secondary-hair-eye-$selected") -Label "Current-floor face-secondary physical comparison"
    $faceSummaryPath = Need-File -Path (Join-Path $faceRoot "face-secondary-hair-eye-preview.json") -Label "Face-secondary physical comparison summary"
    if ((Sha256 $faceSummaryPath) -ne $faceSummarySha) { throw "Face-secondary preview summary bytes differ from current-floor summary authority." }
    $faceSummary = Read-Json -Path $faceSummaryPath -Label "Face-secondary physical comparison summary"
    if ([string]$faceSummary.format -ne "bodyrig-face-secondary-hair-eye-windows-preview" -or -not (Test-V1Version $faceSummary.version) -or
        [string]$faceSummary.bodyrig_revision -ne $head -or [string]$faceSummary.source_package_sha256 -ne $currentFloorPackageSha -or
        $faceSummary.face_secondary_drawable -ne $true -or $faceSummary.comparison_only -ne $true -or
        $faceSummary.physical_acceptance_authority -ne $false -or $faceSummary.human_visual_authority_required -ne $true -or
        $faceSummary.package_promotion_authority -ne $false -or $faceSummary.production_activation -ne $false) {
        throw "Face-secondary physical comparison crossed its review-only authority boundary."
    }
    $facePackageSha = Need-Sha256 -Value ([string]$faceSummary.comparison_package_sha256) -Label "Face-secondary comparison package SHA-256"
    $physicalComparisonPackageSha = Need-Sha256 -Value ([string]$summary.physical_comparison_package_sha256) -Label "Physical comparison package SHA-256"
    if ($facePackageSha -ne $physicalPackageSha -or $facePackageSha -ne $physicalComparisonPackageSha) { throw "Current-floor summary points at a different physical comparison package." }
    $physicalRoot = $faceRoot
} elseif ($physicalKind -eq "retained-hair-eye") {
    if (-not [string]::IsNullOrWhiteSpace($faceSummarySha) -or -not [string]::IsNullOrWhiteSpace([string]$summary.physical_comparison_package_sha256)) { throw "Retained physical authority unexpectedly carries face-secondary comparison authority." }
    if ($physicalPackageSha -ne $currentFloorPackageSha) { throw "Retained physical authority points at different source package bytes." }
} else {
    throw "Current-floor summary physical_authority_kind is invalid: $physicalKind"
}
$visibility = Need-File -Path (Join-Path $physicalRoot "windows-preview\component-visibility-probe.json") -Label "Unity component visibility probe"
$renderSet = Need-File -Path (Join-Path $physicalRoot "windows-preview\snapshots\fidelity-render-set.json") -Label "Current-floor physical fidelity render set"
$expectedVisibilitySha = Need-Sha256 -Value ([string]$summary.physical_component_visibility_probe_sha256) -Label "Physical component visibility probe SHA-256"
$expectedRenderSetSha = Need-Sha256 -Value ([string]$summary.physical_render_set_sha256) -Label "Physical render-set SHA-256"
if ((Sha256 $visibility) -ne $expectedVisibilitySha -or (Sha256 $visibility) -ne (Need-Sha256 -Value ([string]$summary.component_visibility_probe_sha256) -Label "Component visibility probe SHA-256")) { throw "Final physical visibility-probe bytes differ from current-floor summary authority." }
if ((Sha256 $renderSet) -ne $expectedRenderSetSha -or (Sha256 $renderSet) -ne (Need-Sha256 -Value ([string]$summary.component_gap_render_set_sha256) -Label "Component gap render-set SHA-256")) { throw "Final physical render-set bytes differ from current-floor summary authority." }
$gapPath = Join-Path $eveningRoot "component-gap-plan.json"
$gapAttempt = Join-Path $eveningRoot (".component-gap-plan.verify-" + [Guid]::NewGuid().ToString("N") + ".json")
try {
    & $BodyRigPython -m bodyrig.fidelity_component_gap `
        --visibility-probe $visibility `
        --render-set $renderSet `
        --out $gapAttempt | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Component-gap planning failed with exit code $LASTEXITCODE" }
    $freshGap = Read-Json -Path $gapAttempt -Label "Fresh current-floor component gap plan"
    if (Test-Path -LiteralPath $gapPath -PathType Leaf) {
        $existingGap = Read-Json -Path $gapPath -Label "Existing current-floor component gap plan"
        $matchesFinal = $false
        try {
            Assert-SemanticallyEqualJson -Expected $freshGap -Actual $existingGap -Label "Existing current-floor component gap plan"
            $matchesFinal = $true
        } catch {
            if ($physicalKind -ne "face-secondary-hair-eye-comparison") { throw }
        }
        if ($matchesFinal) {
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
                $archived = Read-Json -Path $predecessorPath -Label "Archived retained predecessor component gap plan"
                Assert-SemanticallyEqualJson -Expected $existingGap -Actual $archived -Label "Archived retained predecessor component gap plan"
                Remove-Item -LiteralPath $gapPath -Force
            } else {
                Move-Item -LiteralPath $gapPath -Destination $predecessorPath
            }
            Move-Item -LiteralPath $gapAttempt -Destination $gapPath
            $gapAttempt = ""
            Write-Host "Advanced persisted component gap from exact retained predecessor to final face-secondary authority: $gapPath"
        }
    } else {
        Move-Item -LiteralPath $gapAttempt -Destination $gapPath
        $gapAttempt = ""
    }
} finally {
    if (-not [string]::IsNullOrWhiteSpace($gapAttempt) -and (Test-Path -LiteralPath $gapAttempt -PathType Leaf)) {
        Remove-Item -LiteralPath $gapAttempt -Force -ErrorAction SilentlyContinue
    }
}

$gap = Read-Json -Path $gapPath -Label "Current-floor component gap plan"
if ([string]$gap.bodyrig_revision -ne $head -or [string]$gap.package_sha256 -ne $physicalPackageSha -or
    $gap.human_visual_authority_required -ne $true -or $gap.production_activation -ne $false) {
    throw "Current-floor component gap plan targets different package/revision or crossed authority."
}
$drawable = @($gap.drawable_components | ForEach-Object { [string]$_ })
$missing = @($gap.missing_components | ForEach-Object { [string]$_ })
$actions = @($gap.next_actions)
if ($actions.Count -lt 1) { throw "Current-floor component gap plan has no qualified next action." }
$expectedActionId = ([string]$actions[0].id).Trim()
if ([string]::IsNullOrWhiteSpace($expectedActionId)) { throw "Current-floor component gap plan first action id is empty." }
$snapshotDir = Need-Directory -Path (Join-Path $physicalRoot "windows-preview\snapshots") -Label "Current-floor snapshot directory"

$temporaryExecutionContext = ""
$hfnExplicitValues = @($HfnPersonId, $HfnBodyRevision)
$hfnExplicitCount = @($hfnExplicitValues | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }).Count
if (-not [string]::IsNullOrWhiteSpace($ExecutionContext) -and $hfnExplicitCount -gt 0) {
    throw "ExecutionContext cannot be combined with HfnPersonId/HfnBodyRevision; choose one explicit context authority."
}
if ($hfnExplicitCount -ne 0 -and $hfnExplicitCount -ne 2) {
    throw "Derived HFN context requires HfnPersonId and HfnBodyRevision together; partial identity authority is refused."
}
if ($hfnExplicitCount -eq 2 -and $expectedActionId -ne "source-bound-hfn-continuation") {
    throw "Explicit HFN identity context is only valid when source-bound-hfn-continuation is the qualified next action."
}
try {
    if ([string]::IsNullOrWhiteSpace($ExecutionContext)) {
    $temporaryExecutionContext = Join-Path $eveningRoot (".component-gap-execution-context-" + [Guid]::NewGuid().ToString("N") + ".json")
    if ($hfnExplicitCount -eq 2) {
        if ($physicalKind -ne "face-secondary-hair-eye-comparison") {
            throw "Derived HFN context requires the exact final face-secondary comparison package authority."
        }
        $hfnPackagePath = Need-File -Path (Join-Path $physicalRoot "comparison\face-secondary-hair-eye-comparison.mrbody") -Label "Final face-secondary package for HFN continuation"
        if ((Sha256 $hfnPackagePath) -ne $physicalPackageSha) {
            throw "Derived HFN context package bytes differ from the final component-gap package authority."
        }
        $hfnRootPath = Resolve-CanonicalPersonLibrary -Python $BodyRigPython -RepoRoot $repoRoot
        $hfnTag = $physicalPackageSha.Substring(0, 12)
        $derivedContext = [ordered]@{
            package_path = $hfnPackagePath
            hfn_root = $hfnRootPath
            person_id = $HfnPersonId.Trim()
            body_revision = $HfnBodyRevision.Trim()
            hfn_render_dir = (Join-Path $eveningRoot "hfn-render-$selected-$hfnTag")
            hfn_human_review_dir = (Join-Path $eveningRoot "hfn-human-review-$selected-$hfnTag")
        }
        $derivedContextJson = $derivedContext | ConvertTo-Json -Depth 10 -Compress
        [IO.File]::WriteAllText($temporaryExecutionContext, $derivedContextJson, [Text.UTF8Encoding]::new($false))
        Write-Host "Derived exact HFN executor context from final physical package plus explicit HFN identity authority."
    } else {
        [IO.File]::WriteAllText($temporaryExecutionContext, "{}", [Text.UTF8Encoding]::new($false))
    }
    $contextPath = $temporaryExecutionContext
    } else {
        $contextPath = Need-File -Path $ExecutionContext -Label "Component-gap execution context"
    }
    $execution = Invoke-GapExecutor -Python $BodyRigPython -PlanPath $gapPath -ContextPath $contextPath -RepoRoot $repoRoot -Execute:$ExecuteNextAction
    $executionMode = Assert-GapExecutorResult `
        -Value $execution `
        -ExpectedHead $head `
        -ExpectedBodyId ([string]$gap.body_id) `
        -ExpectedPackageSha $physicalPackageSha `
        -ExpectedActionId $expectedActionId `
        -ExecutionRequested:$ExecuteNextAction
} finally {
    if (-not [string]::IsNullOrWhiteSpace($temporaryExecutionContext) -and (Test-Path -LiteralPath $temporaryExecutionContext -PathType Leaf)) {
        Remove-Item -LiteralPath $temporaryExecutionContext -Force -ErrorAction SilentlyContinue
    }
}

if ($executionMode -eq "machine-executable" -and $ExecuteNextAction) {
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "BODYRIG ONE QUALIFIED COMPONENT-GAP STEP EXECUTED"
    Write-Host "Action:           $expectedActionId"
    Write-Host "Reprobe required: TRUE"
    Write-Host "Human visual QA: REQUIRED"
    Write-Host "Production:      FALSE"
    Write-Host "Rerun this evening command to recompute physical evidence before any further action."
    Write-Host "============================================================"
    exit 0
}

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG EVENING RESULT"
Write-Host "Candidate:       $selected"
Write-Host "Gap state:       $([string]$gap.state)"
Write-Host "Drawable:        $(if ($drawable.Count) { $drawable -join ', ' } else { '<none>' })"
Write-Host "Missing:         $(if ($missing.Count) { $missing -join ', ' } else { '<none>' })"
Write-Host "Strict scoring:  $([bool]$gap.strict_machine_scoring_ready)"
Write-Host "Overall diag:    $($summary.diagnostic_scores.overall)"
Write-Host "Hair diag:       $($summary.diagnostic_scores.hair_appearance)"
Write-Host "Face diag:       $($summary.diagnostic_scores.face_appearance)"
Write-Host ""
Write-Host "Qualified next actions:"
foreach ($action in $actions) {
    $components = @($action.components | ForEach-Object { [string]$_ }) -join ", "
    Write-Host "- $([string]$action.id) [$components]: $([string]$action.reason)"
}
Write-Host ""
Write-Host "Executor route:  $executionMode"
if ($executionMode -eq "operator-stop") {
    Write-Host "Executor stop:   $([string]$execution.reason)"
    if ($execution.PSObject.Properties.Name -contains "operator_command" -and -not [string]::IsNullOrWhiteSpace([string]$execution.operator_command)) {
        Write-Host "Operator command:$([string]$execution.operator_command)"
    }
} elseif (-not $ExecuteNextAction) {
    Write-Host "Executor:        DRY RUN ONLY (use -ExecuteNextAction to run at most one qualified machine-safe action)"
}
Write-Host ""
Write-Host "Human visual QA: REQUIRED"
Write-Host "Production:      FALSE"
Write-Host "Gap plan:        $gapPath"
Write-Host "Summary:         $summaryPath"
Write-Host "Snapshots:       $snapshotDir"
Write-Host "============================================================"

if ($OpenSnapshots) { Start-Process explorer.exe -ArgumentList @($snapshotDir) }
exit 0
