param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9æøå_-]{1,160}$')][string]$BodyId,
    [string]$Name = "",
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$UnityExe = "",
    [string]$WorkRoot = "",
    [ValidateRange(1, 4)][int]$MaxFullRebuilds = 2,
    [ValidateRange(0, 8)][int]$MaxRefinementsPerRebuild = 3,
    [ValidateRange(1.0, 72.0)][double]$MaxWallClockHours = 8.0,
    [ValidateRange(0, 2147483647)][int]$BaseSithSeed = 1337,
    [ValidateRange(1, 24)][int]$ReferenceLimit = 24,
    [switch]$KeepPrivateWorkspaces
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$Executable,[Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Step)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}
function Snapshot-Directories {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$Prefix)
    $result = @{}
    if (Test-Path -LiteralPath $Root -PathType Container) {
        foreach ($item in Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue) {
            if ($item.Name.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) { $result[$item.FullName] = $true }
        }
    }
    return $result
}
function New-DirectoriesSince {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$Prefix,[Parameter(Mandatory = $true)][hashtable]$Before)
    $result = @()
    if (Test-Path -LiteralPath $Root -PathType Container) {
        foreach ($item in Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue) {
            if ($item.Name.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase) -and -not $Before.ContainsKey($item.FullName)) { $result += $item.FullName }
        }
    }
    return @($result)
}
function Next-Seed {
    param([int]$FullRebuildNumber)
    if ($FullRebuildNumber -le 1) { return [int64]$BaseSithSeed }
    $modulus = [int64]2147483647
    $stride = [int64]15485863
    return [int64](([int64]$BaseSithSeed + ([int64]($FullRebuildNumber - 1) * $stride)) % $modulus)
}
function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Output already exists: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}
function Write-LiveJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temp -Encoding UTF8
        [IO.File]::Move($temp, $Path, $true)
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}
function Average-Seconds {
    param([object[]]$Values)
    if ($null -eq $Values -or $Values.Count -eq 0) { return $null }
    $sum = 0.0
    foreach ($value in $Values) { $sum += [double]$value }
    return $sum / [double]$Values.Count
}
function Format-Duration {
    param([Nullable[double]]$Seconds)
    if ($null -eq $Seconds) { return "unknown" }
    $span = [TimeSpan]::FromSeconds([double]$Seconds)
    if ($span.TotalHours -ge 1) { return ("{0}h {1}m" -f [math]::Floor($span.TotalHours), $span.Minutes) }
    return ("{0}m {1}s" -f [math]::Floor($span.TotalMinutes), $span.Seconds)
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig fidelity convergence is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not bind fidelity convergence to BodyRig Git HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig Git HEAD is not canonical." }
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Fidelity convergence requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { $BodyRigPython = $venv }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"
if ([string]::IsNullOrWhiteSpace($RigSetupReport)) { $RigSetupReport = [string]$env:BODYRIG_RIG_SETUP_REPORT }
if ([string]::IsNullOrWhiteSpace($RigSetupReport) -and -not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $candidate = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $RigSetupReport = $candidate }
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport)) { throw "BodyRig rig setup report is required." }
$RigSetupReport = Resolve-InputFile -Path $RigSetupReport -Label "BodyRig rig setup report"
Invoke-Checked -Executable $BodyRigPython -Arguments @("-m", "bodyrig.rig_setup", $RigSetupReport) -Step "Rig setup authority validation"
if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) { throw "Stash URL is required via -StashUrl or STASH_URL." }
if ([string]::IsNullOrWhiteSpace($ApiKeyEnv)) { throw "ApiKeyEnv is required." }

$artifactBase = [string]$env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($artifactBase)) { $artifactBase = [System.IO.Path]::GetTempPath() }
if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $WorkRoot = Join-Path $artifactBase "BodyRig\fidelity-convergence\$BodyId-$stamp-$suffix"
}
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
if (Test-Path -LiteralPath $WorkRoot) { throw "Fidelity convergence work root already exists: $WorkRoot" }
New-Item -ItemType Directory -Path $WorkRoot | Out-Null

$progressPath = Join-Path $WorkRoot "progress.json"
$referenceDir = Join-Path $WorkRoot "references"
$referenceManifest = Join-Path $referenceDir "reference-set.json"
$frozenBodyReference = Join-Path $referenceDir "private-body-reference-rgba.png"
$bestPreviewDir = Join-Path $WorkRoot "best-preview"
$profileLauncher = Resolve-InputFile -Path (Join-Path $repoRoot "clone-body-from-stash-profiled-ready.ps1") -Label "Profiled physical clone launcher"
$gateA = Resolve-InputFile -Path (Join-Path $repoRoot "accept-physical-clone.ps1") -Label "Gate A launcher"
$fidelityRenderer = Resolve-InputFile -Path (Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1") -Label "Fidelity Windows renderer"
$refitScript = Resolve-InputFile -Path (Join-Path $repoRoot "refit-fidelity-candidate.ps1") -Label "Fidelity reconstruction-resume refit"

$runStart = [DateTime]::UtcNow
$stageStart = $runStart
$stage = "initializing"
$fullRebuildsCompleted = 0
$refinementsCompleted = 0
$currentRebuildRefinements = 0
$currentSeed = $null
$fullDurations = @()
$refinementDurations = @()
$phaseTimings = [ordered]@{
    "full-rebuild" = @()
    "resume-refinement" = @()
    "gate-a" = @()
    "render" = @()
    "evaluate" = @()
}
$latestScores = $null
$bestScores = $null
$bestCandidate = $null
$strategy = $null
$nextFocus = $null
$evaluationPaths = @()
$candidateRecords = @()
$usedAdjustmentHashes = @()
$frozenBodyReferenceSha = ""
$currentBaselineCloneOutput = ""
$currentIdentityWorkspace = ""
$currentObservationWorkspaces = @()
$effectiveName = $Name
$firstRendererBuild = $true
$terminalState = ""
$terminalReason = ""

function Update-Progress {
    param([string]$State = "running",[string]$NewStage = "")
    if (-not [string]::IsNullOrWhiteSpace($NewStage)) { $script:stage = $NewStage; $script:stageStart = [DateTime]::UtcNow }
    $now = [DateTime]::UtcNow
    $elapsed = ($now - $runStart).TotalSeconds
    $fullAverage = Average-Seconds -Values $fullDurations
    $refineAverage = Average-Seconds -Values $refinementDurations
    $remainingFull = [math]::Max(0, $MaxFullRebuilds - $fullRebuildsCompleted)
    $remainingRefinements = [math]::Max(0, ($MaxFullRebuilds * $MaxRefinementsPerRebuild) - $refinementsCompleted)
    $eta = $null
    if (($remainingFull -eq 0 -or $null -ne $fullAverage) -and ($remainingRefinements -eq 0 -or $null -ne $refineAverage)) {
        $eta = 0.0
        if ($remainingFull -gt 0) { $eta += [double]$fullAverage * $remainingFull }
        if ($remainingRefinements -gt 0) { $eta += [double]$refineAverage * $remainingRefinements }
    }
    $progress = [ordered]@{
        format = "bodyrig-fidelity-progress"
        version = 1
        state = $State
        stage = $stage
        bodyrig_revision = $head
        performer_id = $PerformerId
        body_alias = $BodyId
        started_at = $runStart.ToString("o")
        last_update = $now.ToString("o")
        stage_started_at = $stageStart.ToString("o")
        elapsed_seconds = [math]::Round($elapsed, 1)
        eta_seconds = $(if ($null -eq $eta) { $null } else { [math]::Round($eta, 0) })
        max_wall_clock_hours = $MaxWallClockHours
        full_rebuilds_completed = $fullRebuildsCompleted
        max_full_rebuilds = $MaxFullRebuilds
        refinements_completed = $refinementsCompleted
        current_rebuild_refinements = $currentRebuildRefinements
        max_refinements_per_rebuild = $MaxRefinementsPerRebuild
        current_seed = $currentSeed
        latest_scores = $latestScores
        best_scores = $bestScores
        best_candidate = $bestCandidate
        strategy = $strategy
        next_focus = $nextFocus
        observed_full_rebuild_seconds_average = $fullAverage
        observed_refinement_seconds_average = $refineAverage
        phase_timings = $phaseTimings
        progress_file = "progress.json"
        best_preview_dir = $(if (Test-Path -LiteralPath $bestPreviewDir -PathType Container) { "best-preview" } else { $null })
        comparison_only = $true
        production_activation = $false
    }
    Write-LiveJson -Path $progressPath -Value $progress
}
function Record-Duration {
    param([Parameter(Mandatory = $true)][string]$Kind,[Parameter(Mandatory = $true)][double]$Seconds)
    $phaseTimings[$Kind] = @($phaseTimings[$Kind]) + @([math]::Round($Seconds, 3))
}
function Update-BestPreview {
    param([Parameter(Mandatory = $true)][int]$BestIteration)
    if ($BestIteration -lt 1 -or $BestIteration -gt $candidateRecords.Count) { throw "Convergence best iteration does not map to a known candidate." }
    $record = $candidateRecords[$BestIteration - 1]
    $snapshotDir = Join-Path ([string]$record.render_dir) "snapshots"
    if (-not (Test-Path -LiteralPath $snapshotDir -PathType Container)) { throw "Best candidate snapshot directory is missing." }
    if (Test-Path -LiteralPath $bestPreviewDir -PathType Container) { Remove-Item -LiteralPath $bestPreviewDir -Recurse -Force }
    New-Item -ItemType Directory -Path $bestPreviewDir | Out-Null
    foreach ($name in @("front-full.png", "three-quarter-full.png", "side-full.png", "face-front.png", "fidelity-render-set.json")) {
        $source = Join-Path $snapshotDir $name
        if (Test-Path -LiteralPath $source -PathType Leaf) { Copy-Item -LiteralPath $source -Destination (Join-Path $bestPreviewDir $name) }
    }
    $script:bestCandidate = [string]$record.relative_name
}
function Evaluate-Candidate {
    param(
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$PackagePath,
        [string]$AcceptanceDir = "",
        [Parameter(Mandatory = $true)][string]$RelativeName,
        [Parameter(Mandatory = $true)][string]$Mode
    )
    $renderDir = Join-Path $CandidateDir "comparison-render"
    $evaluationPath = Join-Path $CandidateDir "fidelity-evaluation.json"
    $decisionPath = Join-Path $CandidateDir "convergence-decision.json"
    $adjustmentPlanPath = Join-Path $CandidateDir "next-adjustment-plan.json"
    $nextRequestPath = Join-Path $CandidateDir "next-bodyprint-adjustment-request.json"

    Update-Progress -NewStage "render-comparison"
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $rendererArgs = @{ OutputDir = $renderDir; BodyRigPython = $BodyRigPython }
    if (-not [string]::IsNullOrWhiteSpace($AcceptanceDir)) { $rendererArgs.AcceptanceDir = $AcceptanceDir }
    else { $rendererArgs.PackagePath = $PackagePath }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $rendererArgs.UnityExe = $UnityExe }
    if (-not $firstRendererBuild) { $rendererArgs.SkipBuild = $true }
    & $fidelityRenderer @rendererArgs
    if ($LASTEXITCODE -ne 0) { throw "Canonical comparison render failed for $RelativeName" }
    $timer.Stop(); Record-Duration -Kind "render" -Seconds $timer.Elapsed.TotalSeconds
    $script:firstRendererBuild = $false

    Update-Progress -NewStage "evaluate-fidelity"
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $renderManifest = Join-Path $renderDir "snapshots\fidelity-render-set.json"
    Invoke-Checked -Executable $BodyRigPython -Arguments @(
        "-m", "bodyrig.fidelity_evaluator_cli",
        "--rig-setup", $RigSetupReport,
        "--reference-set", $referenceManifest,
        "--render-set", $renderManifest,
        "--body-reference-rgba", $frozenBodyReference,
        "--iteration", [string]($evaluationPaths.Count + 1),
        "--out", $evaluationPath
    ) -Step "Visual fidelity evaluation for $RelativeName"
    $timer.Stop(); Record-Duration -Kind "evaluate" -Seconds $timer.Elapsed.TotalSeconds
    $script:evaluationPaths += $evaluationPath

    $maxCandidates = $MaxFullRebuilds * (1 + $MaxRefinementsPerRebuild)
    $decisionArgs = @("-m", "bodyrig.fidelity_convergence_cli") + $evaluationPaths + @("--out", $decisionPath, "--max-iterations", [string]$maxCandidates)
    Invoke-Checked -Executable $BodyRigPython -Arguments $decisionArgs -Step "Visual fidelity convergence decision for $RelativeName"
    $decision = Get-Content -LiteralPath $decisionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $evaluation = Get-Content -LiteralPath $evaluationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $script:latestScores = $decision.scores
    $script:bestScores = $decision.best_scores
    $script:strategy = [string]$decision.strategy
    $script:nextFocus = [string]$decision.next_focus
    $script:candidateRecords += [pscustomobject]@{
        relative_name = $RelativeName
        mode = $Mode
        package_path = $PackagePath
        render_dir = $renderDir
        evaluation_path = $evaluationPath
        acceptance_dir = $AcceptanceDir
    }
    Update-BestPreview -BestIteration ([int]$decision.best_iteration)

    Write-Host ("Scores: face={0:N3} body={1:N3} hair={2:N3} skin={3:N3} photo={4:N3} plausible={5:N3} overall={6:N3}" -f `
        [double]$decision.scores.face_appearance,[double]$decision.scores.body_silhouette,[double]$decision.scores.hair_appearance,
        [double]$decision.scores.skin_material,[double]$decision.scores.photorealism,[double]$decision.scores.human_plausibility,[double]$decision.scores.overall)
    Write-Host "Decision: $([string]$decision.state) | strategy=$([string]$decision.strategy) | focus=$([string]$decision.next_focus) | best=$bestCandidate"
    if ([string]$decision.strategy -eq "appearance-search") {
        Write-Host "Appearance-search: hair/skin/photorealism remains the bottleneck; preserve best-so-far and avoid blind geometry churn."
    }

    Invoke-Checked -Executable $BodyRigPython -Arguments @("-m", "bodyrig.fidelity_adjustment", $evaluationPath, "--out", $adjustmentPlanPath) -Step "Bounded silhouette adjustment planning"
    $plan = Get-Content -LiteralPath $adjustmentPlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $adjustmentHash = ""
    if ($plan.applicable -eq $true) {
        Write-CreateOnlyJson -Path $nextRequestPath -Value $plan.adjustment_request
        $adjustmentHash = (Get-FileHash -LiteralPath $nextRequestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    Update-Progress
    return [pscustomobject]@{
        decision = $decision
        evaluation = $evaluation
        adjustment_plan = $plan
        adjustment_request = $(if ($plan.applicable -eq $true) { $nextRequestPath } else { "" })
        adjustment_sha256 = $adjustmentHash
    }
}
function Get-NextAction {
    param([Parameter(Mandatory = $true)]$CandidateResult)
    $args = @(
        "-m", "bodyrig.fidelity_cost_plan_cli",
        "--state", [string]$CandidateResult.decision.state,
        "--full-rebuilds-completed", [string]$fullRebuildsCompleted,
        "--refinements-on-current-rebuild", [string]$currentRebuildRefinements,
        "--max-full-rebuilds", [string]$MaxFullRebuilds,
        "--max-refinements-per-rebuild", [string]$MaxRefinementsPerRebuild
    )
    if (-not [string]::IsNullOrWhiteSpace([string]$CandidateResult.adjustment_sha256)) { $args += @("--adjustment-request-sha256", [string]$CandidateResult.adjustment_sha256) }
    foreach ($hash in $usedAdjustmentHashes) { $args += @("--used-adjustment-sha256", [string]$hash) }
    $raw = @(& $BodyRigPython @args)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "Cost-aware fidelity scheduler failed." }
    try { return ([string]$raw[0]) | ConvertFrom-Json }
    catch { throw "Cost-aware fidelity scheduler returned unreadable JSON." }
}
function WallClockAllowsAnotherFullRebuild {
    $fullAverage = Average-Seconds -Values $fullDurations
    if ($null -eq $fullAverage) { return $true }
    $elapsed = ([DateTime]::UtcNow - $runStart).TotalSeconds
    return (($elapsed + [double]$fullAverage) -le ($MaxWallClockHours * 3600.0))
}
function Remove-PrivateWorkspaceIfNeeded {
    param([string]$Path)
    if (-not $KeepPrivateWorkspaces -and -not [string]::IsNullOrWhiteSpace($Path) -and (Test-Path -LiteralPath $Path -PathType Container)) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "BodyRig cost-aware visual fidelity convergence"
Write-Host "Revision:              $head"
Write-Host "Performer:             $PerformerId"
Write-Host "Body alias:            $BodyId"
Write-Host "Work root:             $WorkRoot"
Write-Host "Full rebuild budget:   $MaxFullRebuilds"
Write-Host "Cheap refinements:     up to $MaxRefinementsPerRebuild per reconstruction"
Write-Host "Wall-clock budget:     $MaxWallClockHours hours"
Write-Host "Progress:              $progressPath"
Write-Host "Target: likeness + photorealism + human plausibility; low scores iterate, invalid evidence fails."
Write-Host ""
Update-Progress -NewStage "freeze-references"

Invoke-Checked -Executable $BodyRigPython -Arguments @(
    "-m", "bodyrig.stash_fidelity_reference_cli",
    "--performer-id", $PerformerId,
    "--url", $StashUrl,
    "--api-key-env", $ApiKeyEnv,
    "--limit", [string]$ReferenceLimit,
    "--out", $referenceDir
) -Step "Stash performer fidelity reference freeze"
if (-not (Test-Path -LiteralPath $referenceManifest -PathType Leaf)) { throw "Reference-set manifest was not written." }

$identityRoot = Join-Path $artifactBase "BodyRig\identity-workspaces"
$observationRoot = Join-Path $artifactBase "BodyRig\observation-workspaces"

try {
    while ([string]::IsNullOrWhiteSpace($terminalState)) {
        if ($fullRebuildsCompleted -ge $MaxFullRebuilds) {
            $terminalState = "budget-exhausted"; $terminalReason = "full reconstruction count budget exhausted"; break
        }
        if ($fullRebuildsCompleted -gt 0 -and -not (WallClockAllowsAnotherFullRebuild)) {
            $terminalState = "wall-clock-budget"; $terminalReason = "observed reconstruction duration predicts another full build would exceed wall-clock budget"; break
        }

        $rebuildNumber = $fullRebuildsCompleted + 1
        $currentSeed = Next-Seed -FullRebuildNumber $rebuildNumber
        $currentRebuildRefinements = 0
        $usedAdjustmentHashes = @()
        $rebuildDir = Join-Path $WorkRoot ("rebuild-{0:D2}" -f $rebuildNumber)
        New-Item -ItemType Directory -Path $rebuildDir | Out-Null
        $cloneOutput = Join-Path $rebuildDir "clone-run"
        $sessionReport = Join-Path $rebuildDir "physical-session.json"
        $acceptanceDir = Join-Path $rebuildDir "full\acceptance"
        $fullCandidateDir = Join-Path $rebuildDir "full"
        New-Item -ItemType Directory -Path $fullCandidateDir | Out-Null

        $beforeIdentity = Snapshot-Directories -Root $identityRoot -Prefix "$BodyId-"
        $beforeObservation = Snapshot-Directories -Root $observationRoot -Prefix "$BodyId-"
        Update-Progress -NewStage "full-reconstruction"
        Write-Host "=== Full reconstruction $rebuildNumber/$MaxFullRebuilds | SiTH seed=$currentSeed ==="
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $cloneArgs = @(
            "-PerformerId", $PerformerId,
            "-BodyId", $BodyId,
            "-RigSetupReport", $RigSetupReport,
            "-BodyRigPython", $BodyRigPython,
            "-StashUrl", $StashUrl,
            "-ApiKeyEnv", $ApiKeyEnv,
            "-SithSeed", [string]$currentSeed,
            "-OutputDir", $cloneOutput,
            "-SessionReport", $sessionReport,
            "-KeepPrivateWorkspace"
        )
        if (-not [string]::IsNullOrWhiteSpace($Name)) { $cloneArgs += @("-Name", $Name) }
        & $profileLauncher @cloneArgs
        if ($LASTEXITCODE -ne 0) { throw "Profiled full reconstruction $rebuildNumber failed with exit code $LASTEXITCODE" }
        $timer.Stop(); $fullDurations += $timer.Elapsed.TotalSeconds; Record-Duration -Kind "full-rebuild" -Seconds $timer.Elapsed.TotalSeconds
        $fullRebuildsCompleted++

        $newIdentity = New-DirectoriesSince -Root $identityRoot -Prefix "$BodyId-" -Before $beforeIdentity
        $newObservation = New-DirectoriesSince -Root $observationRoot -Prefix "$BodyId-" -Before $beforeObservation
        if ($newIdentity.Count -ne 1) { throw "Full reconstruction expected exactly one new private identity workspace, found $($newIdentity.Count)." }
        $currentIdentityWorkspace = $newIdentity[0]
        $currentObservationWorkspaces = @($newObservation)
        $bodyReference = Join-Path $currentIdentityWorkspace "identity-capture\primary-rgba.png"
        if (-not (Test-Path -LiteralPath $bodyReference -PathType Leaf)) { throw "Private full-body RGBA reference was not produced." }
        if ([string]::IsNullOrWhiteSpace($frozenBodyReferenceSha)) {
            Copy-Item -LiteralPath $bodyReference -Destination $frozenBodyReference
            $frozenBodyReferenceSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $frozenBodyReference).Hash.ToLowerInvariant()
        } elseif ((Get-FileHash -Algorithm SHA256 -LiteralPath $frozenBodyReference).Hash.ToLowerInvariant() -ne $frozenBodyReferenceSha) {
            throw "Frozen body reference changed during convergence."
        }
        foreach ($path in $currentObservationWorkspaces) { Remove-PrivateWorkspaceIfNeeded -Path $path }

        $baselinePackage = Resolve-InputFile -Path (Join-Path $cloneOutput "clone\$BodyId.mrbody") -Label "Full reconstruction package"
        if ([string]::IsNullOrWhiteSpace($effectiveName)) {
            $nameRaw = @(& $BodyRigPython -c "import sys; from bodyrig.package import validate_package; print(validate_package(sys.argv[1]).manifest['name'])" $baselinePackage)
            if ($LASTEXITCODE -ne 0 -or $nameRaw.Count -ne 1) { throw "Could not resolve display name from baseline package." }
            $effectiveName = ([string]$nameRaw[0]).Trim()
        }
        $currentBaselineCloneOutput = $cloneOutput

        Update-Progress -NewStage "gate-a"
        $timer = [Diagnostics.Stopwatch]::StartNew()
        & $gateA -SessionReport $sessionReport -BodyRigPython $BodyRigPython -OutputDir $acceptanceDir
        if ($LASTEXITCODE -ne 0) { throw "Gate A failed operationally for full reconstruction $rebuildNumber" }
        $timer.Stop(); Record-Duration -Kind "gate-a" -Seconds $timer.Elapsed.TotalSeconds

        $candidate = Evaluate-Candidate -CandidateDir $fullCandidateDir -PackagePath $baselinePackage -AcceptanceDir $acceptanceDir -RelativeName ("rebuild-{0:D2}/full" -f $rebuildNumber) -Mode "full-reconstruction"
        $action = Get-NextAction -CandidateResult $candidate

        while ([string]$action.action -eq "resume-refinement") {
            $currentRebuildRefinements++
            $refinementsCompleted++
            $adjustmentHash = [string]$candidate.adjustment_sha256
            if ($usedAdjustmentHashes -contains $adjustmentHash) { throw "Scheduler attempted a duplicate cheap adjustment." }
            $usedAdjustmentHashes += $adjustmentHash
            $refinementDir = Join-Path $rebuildDir ("refinement-{0:D2}" -f $currentRebuildRefinements)
            New-Item -ItemType Directory -Path $refinementDir | Out-Null
            $refitOutput = Join-Path $refinementDir "refit"

            Update-Progress -NewStage "resume-refinement"
            Write-Host "--- Cheap refinement $currentRebuildRefinements/$MaxRefinementsPerRebuild on reconstruction $rebuildNumber ---"
            Write-Host "Reusing SiTH workspace; recovery/OpenPose/SMPL-X/diffusion reconstruction must not rerun."
            $timer = [Diagnostics.Stopwatch]::StartNew()
            & $refitScript `
                -BaselineCloneOutput $currentBaselineCloneOutput `
                -IdentityWorkspace $currentIdentityWorkspace `
                -AdjustmentRequest ([string]$candidate.adjustment_request) `
                -OutputDir $refitOutput `
                -BodyId $BodyId `
                -Name $effectiveName `
                -BodyRigPython $BodyRigPython
            if ($LASTEXITCODE -ne 0) { throw "Cheap fidelity refit failed." }
            $timer.Stop(); $refinementDurations += $timer.Elapsed.TotalSeconds; Record-Duration -Kind "resume-refinement" -Seconds $timer.Elapsed.TotalSeconds
            $refitPackage = Resolve-InputFile -Path (Join-Path $refitOutput "$BodyId.mrbody") -Label "Refit package"
            $candidate = Evaluate-Candidate -CandidateDir $refinementDir -PackagePath $refitPackage -RelativeName ("rebuild-{0:D2}/refinement-{1:D2}" -f $rebuildNumber, $currentRebuildRefinements) -Mode "resume-refinement"
            $action = Get-NextAction -CandidateResult $candidate
        }

        if ([string]$action.action -eq "stop-converged") {
            $terminalState = "converged"; $terminalReason = [string]$action.reason
        } elseif ([string]$action.action -eq "stop-budget") {
            $terminalState = "budget-exhausted"; $terminalReason = [string]$action.reason
        } elseif ([string]$action.action -eq "full-rebuild") {
            if (-not (WallClockAllowsAnotherFullRebuild)) {
                $terminalState = "wall-clock-budget"
                $terminalReason = "best observed full-rebuild duration predicts another reconstruction would exceed MaxWallClockHours"
            } else {
                Write-Host "No new cheap refinement remains; advancing to next deterministic full reconstruction."
            }
        } else {
            throw "Unsupported cost-aware scheduler action: $([string]$action.action)"
        }

        if (-not [string]::IsNullOrWhiteSpace($terminalState) -or [string]$action.action -eq "full-rebuild") {
            Remove-PrivateWorkspaceIfNeeded -Path $currentIdentityWorkspace
            $currentIdentityWorkspace = ""
        }
        Update-Progress
    }

    if ($candidateRecords.Count -eq 0) { throw "Fidelity convergence produced no candidate." }
    Update-Progress -State "completed" -NewStage "completed"
} catch {
    try { Update-Progress -State "error" -NewStage "error" } catch { }
    throw
} finally {
    if (-not [string]::IsNullOrWhiteSpace($currentIdentityWorkspace)) { Remove-PrivateWorkspaceIfNeeded -Path $currentIdentityWorkspace }
}

$bestRecord = $candidateRecords | Where-Object { [string]$_.relative_name -eq $bestCandidate } | Select-Object -First 1
if ($null -eq $bestRecord) { throw "Best-so-far candidate record is unavailable." }
$best_scores = $bestScores
$resultPath = Join-Path $WorkRoot "convergence-result.json"
$result = [ordered]@{
    format = "bodyrig-fidelity-convergence-run"
    version = 2
    bodyrig_revision = $head
    performer_id = $PerformerId
    body_alias = $BodyId
    target = "high-likeness-photorealistic-human-plausible-avatar"
    state = $terminalState
    reason = $terminalReason
    elapsed_seconds = [math]::Round(([DateTime]::UtcNow - $runStart).TotalSeconds, 1)
    max_wall_clock_hours = $MaxWallClockHours
    full_rebuilds_completed = $fullRebuildsCompleted
    max_full_rebuilds = $MaxFullRebuilds
    refinements_completed = $refinementsCompleted
    max_refinements_per_rebuild = $MaxRefinementsPerRebuild
    observed_full_rebuild_seconds_average = Average-Seconds -Values $fullDurations
    observed_refinement_seconds_average = Average-Seconds -Values $refinementDurations
    best_candidate = $bestCandidate
    best_package_sha256 = (Get-FileHash -LiteralPath ([string]$bestRecord.package_path) -Algorithm SHA256).Hash.ToLowerInvariant()
    best_scores = $best_scores
    best_photorealism = [double]$best_scores.photorealism
    best_human_plausibility = [double]$best_scores.human_plausibility
    best_overall = [double]$best_scores.overall
    best_comparison_render_dir = ([string]$bestRecord.relative_name + "/comparison-render")
    best_has_gate_a = (-not [string]::IsNullOrWhiteSpace([string]$bestRecord.acceptance_dir))
    reference_set = "references/reference-set.json"
    body_reference_sha256 = $frozenBodyReferenceSha
    progress = "progress.json"
    best_preview = "best-preview"
    cost_policy = [ordered]@{
        full_rebuilds_are_expensive = $true
        resumed_refinements_reuse_sith_reconstruction = $true
        full_rebuild_budget = $MaxFullRebuilds
        wall_clock_budget_hours = $MaxWallClockHours
    }
    human_visual_authority_required = $true
    comparison_only = $true
    production_activation = $false
    semantics = "visual-fidelity-not-identity-verification"
}
Write-CreateOnlyJson -Path $resultPath -Value $result

Write-Host ""
Write-Host "BodyRig cost-aware fidelity batch complete"
Write-Host "State:          $terminalState"
Write-Host "Reason:         $terminalReason"
Write-Host "Elapsed:        $(Format-Duration -Seconds ([DateTime]::UtcNow.Subtract($runStart).TotalSeconds))"
Write-Host "Full rebuilds:  $fullRebuildsCompleted/$MaxFullRebuilds | average=$(Format-Duration -Seconds (Average-Seconds -Values $fullDurations))"
Write-Host "Cheap refits:   $refinementsCompleted | average=$(Format-Duration -Seconds (Average-Seconds -Values $refinementDurations))"
Write-Host ("Best:           {0} | photo={1:N3} plausible={2:N3} overall={3:N3}" -f $bestCandidate, [double]$best_scores.photorealism, [double]$best_scores.human_plausibility, [double]$best_scores.overall)
Write-Host "Best preview:   $bestPreviewDir"
Write-Host "Progress:       $progressPath"
Write-Host "Result:         $resultPath"
if ($terminalState -eq "converged") {
    Write-Host "NEXT: human visual review of best-preview. No automatic Quest/release acceptance was written."
} else {
    Write-Host "NEXT: inspect best-preview. The batch stopped on compute/time budget, not because the avatar was declared visually failed."
}
exit 0
