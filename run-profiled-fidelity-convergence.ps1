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
    [ValidateRange(2, 50)][int]$MaxIterations = 10,
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
            if ($item.Name.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                $result[$item.FullName] = $true
            }
        }
    }
    return $result
}
function New-DirectoriesSince {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$Prefix,[Parameter(Mandatory = $true)][hashtable]$Before)
    $result = @()
    if (Test-Path -LiteralPath $Root -PathType Container) {
        foreach ($item in Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue) {
            if ($item.Name.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase) -and -not $Before.ContainsKey($item.FullName)) {
                $result += $item.FullName
            }
        }
    }
    return @($result)
}
function Next-Seed {
    param([int]$Iteration,[bool]$Retuned)
    if ($Iteration -eq 1) { return [int64]$BaseSithSeed }
    $modulus = [int64]2147483647
    $stride = $(if ($Retuned) { [int64]15485863 } else { [int64]104729 })
    return [int64](([int64]$BaseSithSeed + ([int64]($Iteration - 1) * $stride)) % $modulus)
}
function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Output already exists: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig fidelity convergence is Windows-only."
}
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

if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    $RigSetupReport = [string]$env:BODYRIG_RIG_SETUP_REPORT
}
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

$referenceDir = Join-Path $WorkRoot "references"
$referenceManifest = Join-Path $referenceDir "reference-set.json"
$profileLauncher = Resolve-InputFile -Path (Join-Path $repoRoot "clone-body-from-stash-profiled-ready.ps1") -Label "Profiled physical clone launcher"
$gateA = Resolve-InputFile -Path (Join-Path $repoRoot "accept-physical-clone.ps1") -Label "Gate A launcher"
$fidelityRenderer = Resolve-InputFile -Path (Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1") -Label "Fidelity Windows renderer"

Write-Host "BodyRig visual fidelity convergence"
Write-Host "Revision:   $head"
Write-Host "Performer:  $PerformerId"
Write-Host "Body alias: $BodyId"
Write-Host "Work root:  $WorkRoot"
Write-Host "Rule: low likeness ITERATES; only invalid evidence/process errors are hard failures."
Write-Host ""

$referenceArgs = @(
    "-m", "bodyrig.stash_fidelity_reference_cli",
    "--performer-id", $PerformerId,
    "--url", $StashUrl,
    "--api-key-env", $ApiKeyEnv,
    "--limit", [string]$ReferenceLimit,
    "--out", $referenceDir
)
Invoke-Checked -Executable $BodyRigPython -Arguments $referenceArgs -Step "Stash performer fidelity reference freeze"
if (-not (Test-Path -LiteralPath $referenceManifest -PathType Leaf)) { throw "Reference-set manifest was not written." }

$identityRoot = Join-Path $artifactBase "BodyRig\identity-workspaces"
$observationRoot = Join-Path $artifactBase "BodyRig\observation-workspaces"
$evaluationPaths = @()
$currentAdjustmentRequest = ""
$retunedSearch = $false
$firstRendererBuild = $true
$terminalDecision = $null
$originalAdjustmentEnv = [string][Environment]::GetEnvironmentVariable("BODYRIG_BODYPRINT_ADJUSTMENT_REQUEST")

try {
    for ($iteration = 1; $iteration -le $MaxIterations; $iteration++) {
        $iterationDir = Join-Path $WorkRoot ("iteration-{0:D2}" -f $iteration)
        if (Test-Path -LiteralPath $iterationDir) { throw "Iteration directory already exists: $iterationDir" }
        New-Item -ItemType Directory -Path $iterationDir | Out-Null
        $cloneOutput = Join-Path $iterationDir "clone-run"
        $sessionReport = Join-Path $iterationDir "physical-session.json"
        $acceptanceDir = Join-Path $iterationDir "acceptance"
        $renderDir = Join-Path $iterationDir "comparison-render"
        $evaluationPath = Join-Path $iterationDir "fidelity-evaluation.json"
        $decisionPath = Join-Path $iterationDir "convergence-decision.json"
        $adjustmentPlanPath = Join-Path $iterationDir "next-adjustment-plan.json"
        $nextRequestPath = Join-Path $iterationDir "next-bodyprint-adjustment-request.json"
        $seed = Next-Seed -Iteration $iteration -Retuned $retunedSearch

        if ([string]::IsNullOrWhiteSpace($currentAdjustmentRequest)) {
            Remove-Item Env:BODYRIG_BODYPRINT_ADJUSTMENT_REQUEST -ErrorAction SilentlyContinue
        } else {
            $env:BODYRIG_BODYPRINT_ADJUSTMENT_REQUEST = $currentAdjustmentRequest
        }

        $beforeIdentity = Snapshot-Directories -Root $identityRoot -Prefix "$BodyId-"
        $beforeObservation = Snapshot-Directories -Root $observationRoot -Prefix "$BodyId-"
        $newIdentity = @()
        $newObservation = @()
        try {
            Write-Host "=== Iteration $iteration/$MaxIterations | SiTH seed=$seed | strategy=$(if ($retunedSearch) {'retuned'} else {'normal'}) ==="
            $cloneArgs = @(
                "-PerformerId", $PerformerId,
                "-BodyId", $BodyId,
                "-RigSetupReport", $RigSetupReport,
                "-BodyRigPython", $BodyRigPython,
                "-StashUrl", $StashUrl,
                "-ApiKeyEnv", $ApiKeyEnv,
                "-SithSeed", [string]$seed,
                "-OutputDir", $cloneOutput,
                "-SessionReport", $sessionReport,
                "-KeepPrivateWorkspace"
            )
            if (-not [string]::IsNullOrWhiteSpace($Name)) { $cloneArgs += @("-Name", $Name) }
            & $profileLauncher @cloneArgs
            if ($LASTEXITCODE -ne 0) { throw "Profiled clone iteration $iteration failed with exit code $LASTEXITCODE" }

            $newIdentity = New-DirectoriesSince -Root $identityRoot -Prefix "$BodyId-" -Before $beforeIdentity
            $newObservation = New-DirectoriesSince -Root $observationRoot -Prefix "$BodyId-" -Before $beforeObservation
            if ($newIdentity.Count -ne 1) {
                throw "Fidelity iteration expected exactly one new private identity workspace, found $($newIdentity.Count)."
            }
            $bodyReference = Join-Path $newIdentity[0] "identity-capture\primary-rgba.png"
            if (-not (Test-Path -LiteralPath $bodyReference -PathType Leaf)) {
                throw "Private full-body RGBA reference was not produced: $bodyReference"
            }

            & $gateA -SessionReport $sessionReport -BodyRigPython $BodyRigPython -OutputDir $acceptanceDir
            if ($LASTEXITCODE -ne 0) { throw "Gate A failed operationally in fidelity iteration $iteration" }

            $rendererArgs = @{
                AcceptanceDir = $acceptanceDir
                OutputDir = $renderDir
            }
            if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $rendererArgs.UnityExe = $UnityExe }
            if (-not $firstRendererBuild) { $rendererArgs.SkipBuild = $true }
            & $fidelityRenderer @rendererArgs
            if ($LASTEXITCODE -ne 0) { throw "Canonical comparison render failed in fidelity iteration $iteration" }
            $firstRendererBuild = $false

            $renderManifest = Join-Path $renderDir "snapshots\fidelity-render-set.json"
            $evaluateArgs = @(
                "-m", "bodyrig.fidelity_evaluator_cli",
                "--rig-setup", $RigSetupReport,
                "--reference-set", $referenceManifest,
                "--render-set", $renderManifest,
                "--body-reference-rgba", $bodyReference,
                "--iteration", [string]$iteration,
                "--out", $evaluationPath
            )
            Invoke-Checked -Executable $BodyRigPython -Arguments $evaluateArgs -Step "Visual fidelity evaluation iteration $iteration"
            $evaluationPaths += $evaluationPath

            $decisionArgs = @("-m", "bodyrig.fidelity_convergence_cli")
            $decisionArgs += $evaluationPaths
            $decisionArgs += @(
                "--out", $decisionPath,
                "--max-iterations", [string]$MaxIterations
            )
            Invoke-Checked -Executable $BodyRigPython -Arguments $decisionArgs -Step "Visual fidelity convergence decision iteration $iteration"
            $decision = Get-Content -LiteralPath $decisionPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $terminalDecision = $decision

            Write-Host ("Scores: face={0:N3} body={1:N3} hair={2:N3} skin={3:N3} overall={4:N3}" -f `
                [double]$decision.scores.face_appearance,
                [double]$decision.scores.body_silhouette,
                [double]$decision.scores.hair_appearance,
                [double]$decision.scores.skin_material,
                [double]$decision.scores.overall)
            Write-Host "Decision: $([string]$decision.state) | focus=$([string]$decision.next_focus) | best=iteration-$([int]$decision.best_iteration)"

            if ([string]$decision.state -eq "converged") {
                Write-Host "Visual thresholds reached. Automatic generation stops before human visual authority."
                break
            }
            if ([string]$decision.state -eq "manual-review") {
                Write-Host "Automatic batch budget exhausted. Keeping best-so-far for human strategy review; this is NOT a likeness FAIL."
                break
            }

            Invoke-Checked -Executable $BodyRigPython -Arguments @(
                "-m", "bodyrig.fidelity_adjustment",
                $evaluationPath,
                "--out", $adjustmentPlanPath
            ) -Step "Bounded silhouette adjustment planning iteration $iteration"
            $plan = Get-Content -LiteralPath $adjustmentPlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($plan.applicable -eq $true) {
                Write-CreateOnlyJson -Path $nextRequestPath -Value $plan.adjustment_request
                $currentAdjustmentRequest = $nextRequestPath
                Write-Host "Next candidate carries a bounded shoulder/hip correction: $([string]$plan.feedback)"
            }
            $retunedSearch = ([string]$decision.state -eq "plateau")
            if ($retunedSearch) {
                Write-Host "Plateau detected: automatically switching to wide-stride deterministic seed search."
            }
        } finally {
            $newIdentity = New-DirectoriesSince -Root $identityRoot -Prefix "$BodyId-" -Before $beforeIdentity
            $newObservation = New-DirectoriesSince -Root $observationRoot -Prefix "$BodyId-" -Before $beforeObservation
            if (-not $KeepPrivateWorkspaces) {
                foreach ($path in @($newIdentity + $newObservation)) {
                    if (Test-Path -LiteralPath $path -PathType Container) {
                        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
                    }
                }
            }
        }
    }
} finally {
    if ([string]::IsNullOrWhiteSpace($originalAdjustmentEnv)) {
        Remove-Item Env:BODYRIG_BODYPRINT_ADJUSTMENT_REQUEST -ErrorAction SilentlyContinue
    } else {
        $env:BODYRIG_BODYPRINT_ADJUSTMENT_REQUEST = $originalAdjustmentEnv
    }
}

if ($null -eq $terminalDecision) { throw "Fidelity convergence produced no decision." }
$bestIteration = [int]$terminalDecision.best_iteration
$bestDir = Join-Path $WorkRoot ("iteration-{0:D2}" -f $bestIteration)
$bestAcceptance = Join-Path $bestDir "acceptance"
$resultPath = Join-Path $WorkRoot "convergence-result.json"
$result = [ordered]@{
    format = "bodyrig-fidelity-convergence-run"
    version = 1
    bodyrig_revision = $head
    performer_id = $PerformerId
    body_alias = $BodyId
    state = [string]$terminalDecision.state
    iterations_completed = [int]$terminalDecision.iteration
    best_iteration = $bestIteration
    best_candidate_sha256 = [string]$terminalDecision.best_candidate_sha256
    best_overall = [double]$terminalDecision.best_overall
    best_acceptance_dir = ("iteration-{0:D2}/acceptance" -f $bestIteration)
    reference_set = "references/reference-set.json"
    human_visual_authority_required = $true
    production_activation = $false
    semantics = "visual-fidelity-not-identity-verification"
}
Write-CreateOnlyJson -Path $resultPath -Value $result

Write-Host ""
Write-Host "BodyRig fidelity convergence batch complete"
Write-Host "State:        $([string]$terminalDecision.state)"
Write-Host "Best:         iteration $bestIteration | overall=$([double]$terminalDecision.best_overall)"
Write-Host "Best Gate A:  $bestAcceptance"
Write-Host "Result:       $resultPath"
if ([string]$terminalDecision.state -eq "converged") {
    Write-Host "NEXT: run human Windows visual review on the BEST candidate. Do not auto-accept or proceed to Quest."
} else {
    Write-Host "NEXT: inspect best-so-far and retune/start another convergence batch. Low likeness was never recorded as FAIL."
}
exit 0
