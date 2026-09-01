param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [ValidateSet('Seal','Verify')][string]$Mode = 'Verify',
    [string]$BodyRigPython = '',
    [string]$RigSetup = '',
    [switch]$ApproveGeometry
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'The #40 physical handoff wrapper is Windows-only.'
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ is required.' }

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect helper checkout status.' }
if ($dirty.Count -gt 0) { throw 'Physical handoff helper requires a clean checkout.' }

$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
if (-not (Test-Path -LiteralPath $WorkRoot -PathType Container)) { throw "#40 work root not found: $WorkRoot" }
if ([string]::IsNullOrWhiteSpace($RigSetup)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is unavailable; pass -RigSetup.' }
    $RigSetup = Join-Path $env:LOCALAPPDATA 'BodyRig\bodyrig-rig-setup.json'
}
$RigSetup = Resolve-InputFile -Path $RigSetup -Label 'BodyRig rig setup report'

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localVenv = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localVenv -PathType Leaf) { $BodyRigPython = $localVenv }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw 'BodyRig Python not found; pass -BodyRigPython from the installed rig checkout.' }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label 'BodyRig Python'

$expectedRevision = 'c9dc066ef40f95a6004499a895b22a9cb3ff26c7'
$expectedPerformer = '42'
$expectedAlias = 'lauren-phillips-pr40-physical01'
$policyJson = '{"max_full_rebuilds":1,"max_refinements_per_rebuild":0,"max_wall_clock_hours":8.0,"base_sith_seed":1337,"reference_limit":24}'
$handoffDir = Join-Path $WorkRoot 'handoff'
$receipt = Join-Path $handoffDir 'pr40-physical-handoff.json'

$previousPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
try {
    $env:PYTHONPATH = $repoRoot
    $moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig.fidelity_physical_handoff as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw 'Could not prove physical-handoff helper module authority.' }
    $modulePath = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
    if (-not $modulePath.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Physical-handoff module resolved from a different checkout: $modulePath"
    }

    if ($Mode -eq 'Seal') {
        if (-not $ApproveGeometry) {
            throw 'Seal requires -ApproveGeometry after human review confirms closed armholes/no membranes/stable silhouette and topology.'
        }
        if (Test-Path -LiteralPath $receipt) { throw "Physical handoff receipt already exists: $receipt" }
        New-Item -ItemType Directory -Path $handoffDir -Force | Out-Null
        & $BodyRigPython -m bodyrig.fidelity_physical_handoff_cli seal `
            --work-root $WorkRoot `
            --rig-setup $RigSetup `
            --revision $expectedRevision `
            --performer-id $expectedPerformer `
            --body-alias $expectedAlias `
            --policy-json $policyJson `
            --human-geometry-approved `
            --out $receipt
        if ($LASTEXITCODE -ne 0) { throw "#40 physical handoff seal failed with exit code $LASTEXITCODE" }
    } else {
        if (-not (Test-Path -LiteralPath $receipt -PathType Leaf)) { throw "Physical handoff receipt not found: $receipt" }
    }

    & $BodyRigPython -m bodyrig.fidelity_physical_handoff_cli verify `
        --work-root $WorkRoot `
        --rig-setup $RigSetup `
        --revision $expectedRevision `
        --performer-id $expectedPerformer `
        --body-alias $expectedAlias `
        --receipt $receipt
    if ($LASTEXITCODE -ne 0) { throw "#40 physical handoff verification failed with exit code $LASTEXITCODE" }

    Write-Host "#40 physical handoff: PASS | mode=$Mode"
    Write-Host "Receipt: $receipt"
    Write-Host 'Authority: machine-bound Gate A + retained reconstruction + explicit human geometry approval.'
    Write-Host 'Face/appearance remain separate human review dimensions; production activation remains false.'
} finally {
    if ($null -eq $previousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}
