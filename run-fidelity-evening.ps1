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
function Get-Head {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $raw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$raw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
    return $head
}
function Resolve-BodyRigPython {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$Requested)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { return Need-File -Path $Requested -Label "BodyRig Python" }
    $local = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $local -PathType Leaf) { return (Resolve-Path -LiteralPath $local).Path }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "BodyRig Python was not found." }
    return $command.Source
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig evening review is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$WorkRoot = Need-Directory -Path $WorkRoot -Label "Fidelity convergence work root"
$BodyRigPython = Resolve-BodyRigPython -RepoRoot $repoRoot -Requested $BodyRigPython
$review = Need-File -Path (Join-Path $repoRoot "run-fidelity-evening-review.ps1") -Label "Evening retained fidelity review runner"
$head = Get-Head -RepoRoot $repoRoot
$tag = $head.Substring(0, 8)

$reviewArgs = @{
    WorkRoot = $WorkRoot
    BodyRigPython = $BodyRigPython
}
if (-not [string]::IsNullOrWhiteSpace($Rebuild1IdentityWorkspace)) { $reviewArgs.Rebuild1IdentityWorkspace = $Rebuild1IdentityWorkspace }
if (-not [string]::IsNullOrWhiteSpace($Rebuild2IdentityWorkspace)) { $reviewArgs.Rebuild2IdentityWorkspace = $Rebuild2IdentityWorkspace }
if (-not [string]::IsNullOrWhiteSpace($IdentityRoot)) { $reviewArgs.IdentityRoot = $IdentityRoot }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $reviewArgs.UnityExe = $UnityExe }
if ($SkipBuild) { $reviewArgs.SkipBuild = $true }

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG ONE-COMMAND EVENING REVIEW"
Write-Host "Revision: $head"
Write-Host "============================================================"

& $review @reviewArgs
if ($LASTEXITCODE -ne 0) { throw "Evening retained fidelity review failed with exit code $LASTEXITCODE" }

$actualHead = Get-Head -RepoRoot $repoRoot
if ($actualHead -ne $head) { throw "BodyRig checkout changed during top-level evening review." }

$eveningRoot = Need-Directory -Path (Join-Path $WorkRoot "evening-review-$tag") -Label "Evening review output"
$summaryPath = Need-File -Path (Join-Path $eveningRoot "evening-review-summary.json") -Label "Evening review summary"
$summary = Read-Json -Path $summaryPath -Label "Evening review summary"
if ([string]$summary.bodyrig_revision -ne $head) { throw "Evening review summary belongs to a different BodyRig revision." }
$selected = ([string]$summary.selected_candidate).Trim()
if ($selected -notin @("baseline","refit1","reconstruction2")) { throw "Evening review summary selected_candidate is invalid." }

$retainedRoot = Need-Directory -Path (Join-Path $eveningRoot "retained-hair-eye-$selected") -Label "Retained hair+eye preview"
$visibility = Need-File -Path (Join-Path $retainedRoot "windows-preview\component-visibility-probe.json") -Label "Physical component visibility probe"
$renderSet = Need-File -Path (Join-Path $retainedRoot "windows-preview\snapshots\fidelity-render-set.json") -Label "Retained preview fidelity render set"
$gapPath = Join-Path $eveningRoot "component-gap-plan.json"

if (Test-Path -LiteralPath $gapPath -PathType Leaf) {
    Write-Host "Reusing component gap plan: $gapPath"
} else {
    & $BodyRigPython -m bodyrig.fidelity_component_gap `
        --visibility-probe $visibility `
        --render-set $renderSet `
        --out $gapPath
    if ($LASTEXITCODE -ne 0) { throw "Physical fidelity component gap planning failed with exit code $LASTEXITCODE" }
}

$gap = Read-Json -Path $gapPath -Label "Physical fidelity component gap plan"
if ([string]$gap.bodyrig_revision -ne $head -or [string]$gap.package_sha256 -ne [string]$summary.selected_package_sha256) {
    throw "Component gap plan targets different revision/package authority than the evening review."
}
if ($gap.production_activation -ne $false -or $gap.human_visual_authority_required -ne $true) {
    throw "Component gap plan crossed the comparison-only authority boundary."
}

$drawable = @($gap.drawable_components | ForEach-Object { [string]$_ })
$missing = @($gap.missing_components | ForEach-Object { [string]$_ })
$actions = @($gap.next_actions)

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG EVENING REVIEW - QUALIFIED NEXT STEP"
Write-Host "Selected candidate: $selected"
Write-Host "Gap state:          $([string]$gap.state)"
Write-Host "Drawable:           $(if ($drawable.Count) { $drawable -join ', ' } else { '<none>' })"
Write-Host "Missing:            $(if ($missing.Count) { $missing -join ', ' } else { '<none>' })"
Write-Host "Strict scoring:     $([bool]$gap.strict_machine_scoring_ready)"
Write-Host ""
Write-Host "Next actions:"
foreach ($action in $actions) {
    Write-Host "- $([string]$action.id): $([string]$action.reason)"
}
Write-Host ""
Write-Host "Human visual QA:    REQUIRED"
Write-Host "Production:         FALSE"
Write-Host "Summary:            $summaryPath"
Write-Host "Gap plan:           $gapPath"
$snapshotDir = Join-Path $retainedRoot "windows-preview\snapshots"
Write-Host "Snapshots:          $snapshotDir"
Write-Host "============================================================"

if ($OpenSnapshots) { Start-Process explorer.exe -ArgumentList @($snapshotDir) }
exit 0
