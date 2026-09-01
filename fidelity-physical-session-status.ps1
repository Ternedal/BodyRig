param(
    [string]$MainCheckout = 'C:\Users\admin\Desktop\BodyRig-git',
    [string]$WorkRoot = '',
    [string]$BodyRigPython = '',
    [string]$RigSetup = '',
    [string]$BaselineSnapshots = '',
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'The fidelity physical-session status wrapper is Windows-only.'
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ is required.' }

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$helper = (Resolve-Path $PSScriptRoot).Path
$helperDirty = @(& git -C $helper status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect helper checkout status.' }
if ($helperDirty.Count -gt 0) { throw 'Fidelity status requires a clean helper checkout.' }

$main = [IO.Path]::GetFullPath($MainCheckout)
if (-not (Test-Path -LiteralPath $main -PathType Container)) { throw "Main BodyRig checkout not found: $main" }
if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA unavailable; pass -WorkRoot.' }
    $WorkRoot = Join-Path $env:LOCALAPPDATA 'BodyRig\fidelity-convergence\lauren-phillips-pr40-physical01'
}
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
if ([string]::IsNullOrWhiteSpace($RigSetup)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA unavailable; pass -RigSetup.' }
    $RigSetup = Join-Path $env:LOCALAPPDATA 'BodyRig\bodyrig-rig-setup.json'
}
$RigSetup = Resolve-InputFile -Path $RigSetup -Label 'BodyRig rig setup report'
if ([string]::IsNullOrWhiteSpace($BaselineSnapshots)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA unavailable; pass -BaselineSnapshots.' }
    $BaselineSnapshots = Join-Path $env:LOCALAPPDATA 'BodyRig\fidelity-baselines\integration-64aa-8a891565\snapshots'
}
$BaselineSnapshots = [IO.Path]::GetFullPath($BaselineSnapshots)

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $main '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { throw 'BodyRig Python not found in the main checkout; pass -BodyRigPython.' }
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label 'BodyRig Python'

$previousPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
try {
    $env:PYTHONPATH = $helper
    $moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig.fidelity_physical_status as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw 'Could not prove fidelity status helper module authority.' }
    $modulePath = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
    if (-not $modulePath.StartsWith($helper, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Fidelity status module resolved from a different checkout: $modulePath"
    }

    $raw = @(& $BodyRigPython -m bodyrig.fidelity_physical_status_cli `
        --work-root $WorkRoot `
        --baseline-snapshots $BaselineSnapshots `
        --rig-setup $RigSetup)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw 'Fidelity physical status is BLOCKED; inspect the preceding validation error.' }
    $status = ([string]$raw[0]) | ConvertFrom-Json
} finally {
    if ($null -eq $previousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}

if ($Json) {
    $status | ConvertTo-Json -Depth 12
    exit 0
}

Write-Host "BodyRig fidelity physical session"
Write-Host "Phase:       $([string]$status.phase)"
Write-Host "Next action: $([string]$status.next_action)"
Write-Host "State:       $([string]$status.summary)"
Write-Host ''

switch ([string]$status.next_action) {
    'render-historical-baseline' {
        Write-Host 'NEXT COMMANDS:'
        Write-Host "git -C `"$main`" switch --detach 64aa10bf5b1ad45a1e5ffdd63328b751b33359b9"
        Write-Host "& `"$helper\render-known-bad-fidelity-baseline.ps1`" -IntegrationCheckout `"$main`" -BodyRigPython `"$BodyRigPython`""
    }
    'run-pr40-reconstruction' {
        Write-Host 'NEXT: switch the main checkout to exact #40 and run the frozen one-rebuild/zero-refinement command from docs/FIDELITY_PHYSICAL_AB.md.'
        Write-Host 'Exact #40: c9dc066ef40f95a6004499a895b22a9cb3ff26c7'
    }
    'watch-pr40' {
        Write-Host 'NEXT COMMAND:'
        Write-Host "& `"$main\watch-fidelity-progress.ps1`" -WorkRoot `"$WorkRoot`" -RefreshSeconds 5"
        Write-Host 'Do not start another reconstruction while this work root exists.'
    }
    'continue-pr40-gate-render-evaluation' {
        Write-Host 'The expensive reconstruction is safe in a verified checkpoint. If the original convergence process is still running, only watch it.'
        Write-Host 'If the process has stopped, resume from exact #40 using the same work root and policy; do not start a new full reconstruction.'
    }
    'review-and-seal-pr40-geometry' {
        Write-Host "#40 snapshots: $([string]$status.paths.pr40_snapshots)"
        Write-Host 'Review closed armholes, membrane/bridge artifacts, silhouette and topology.'
        Write-Host 'ONLY if geometry is acceptable:'
        Write-Host "& `"$helper\invoke-pr40-physical-handoff.ps1`" -WorkRoot `"$WorkRoot`" -Mode Seal -ApproveGeometry -BodyRigPython `"$BodyRigPython`""
    }
    'run-pr41-fit-only' {
        Write-Host 'The #40 handoff is sealed and verified. Run the exact frozen #41 fit-only command from PR #41 comment 5490834056.'
        Write-Host 'Exact #41: b75fe3097702875e81378389d8b93138240ae4fd'
        Write-Host 'Do not run a second SiTH reconstruction and do not add a BodyPrint adjustment.'
    }
    'finalize-pr40-pr41-review' {
        Write-Host 'NEXT COMMAND:'
        Write-Host "& `"$helper\finalize-pr40-pr41-review.ps1`" -WorkRoot `"$WorkRoot`" -BodyRigPython `"$BodyRigPython`""
    }
    'review-pr40-pr41-appearance' {
        Write-Host "Review page: $([string]$status.paths.review_page)"
        Write-Host 'NEXT: open the page and human-review face, skin, hair and overall identity/appearance. Machine A/B cannot approve visual quality.'
    }
    default { throw "Unsupported next action returned by fidelity status: $([string]$status.next_action)" }
}

Write-Host ''
Write-Host 'Human visual authority required: TRUE'
Write-Host 'Production activation: FALSE'
exit 0
