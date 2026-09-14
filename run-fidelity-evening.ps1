param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [string]$Rebuild1IdentityWorkspace = "",
    [string]$Rebuild2IdentityWorkspace = "",
    [string]$IdentityRoot = "",
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
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
function Assert-SemanticallyEqualJson {
    param([Parameter(Mandatory = $true)]$Expected,[Parameter(Mandatory = $true)]$Actual,[Parameter(Mandatory = $true)][string]$Label)
    $expectedText = $Expected | ConvertTo-Json -Depth 50 -Compress
    $actualText = $Actual | ConvertTo-Json -Depth 50 -Compress
    if ($expectedText -ne $actualText) { throw "$Label differs from freshly recomputed authority; refusing stale/tampered reuse." }
}
function Test-V1Version($Value) {
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }
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
$visibility = Need-File -Path (Join-Path $retainedRoot "windows-preview\component-visibility-probe.json") -Label "Unity component visibility probe"
$renderSet = Need-File -Path (Join-Path $retainedRoot "windows-preview\snapshots\fidelity-render-set.json") -Label "Current-floor fidelity render set"
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
        Assert-SemanticallyEqualJson -Expected $freshGap -Actual $existingGap -Label "Existing current-floor component gap plan"
        Write-Host "Revalidated existing component gap plan: $gapPath"
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
if ([string]$gap.bodyrig_revision -ne $head -or [string]$gap.package_sha256 -ne [string]$summary.current_floor_package_sha256 -or
    $gap.human_visual_authority_required -ne $true -or $gap.production_activation -ne $false) {
    throw "Current-floor component gap plan targets different package/revision or crossed authority."
}
$drawable = @($gap.drawable_components | ForEach-Object { [string]$_ })
$missing = @($gap.missing_components | ForEach-Object { [string]$_ })
$actions = @($gap.next_actions)
$snapshotDir = Need-Directory -Path (Join-Path $retainedRoot "windows-preview\snapshots") -Label "Current-floor snapshot directory"

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
Write-Host "Human visual QA: REQUIRED"
Write-Host "Production:      FALSE"
Write-Host "Gap plan:        $gapPath"
Write-Host "Summary:         $summaryPath"
Write-Host "Snapshots:       $snapshotDir"
Write-Host "============================================================"

if ($OpenSnapshots) { Start-Process explorer.exe -ArgumentList @($snapshotDir) }
exit 0
