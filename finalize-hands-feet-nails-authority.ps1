param(
    [Parameter(Mandatory = $true)]
    [string]$AssemblyReceipt,

    [Parameter(Mandatory = $true)]
    [string]$BodyReleaseStatus,

    [Parameter(Mandatory = $true)]
    [string]$ReviewId,

    [Parameter(Mandatory = $true)]
    [string]$RenderAuthority
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

function Resolve-BodyRigPython {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $venv).Path
    }
    $command = Get-Command python -ErrorAction Stop
    return $command.Source
}

$assemblyPath = (Resolve-Path -LiteralPath $AssemblyReceipt -ErrorAction Stop).Path
$releasePath = (Resolve-Path -LiteralPath $BodyReleaseStatus -ErrorAction Stop).Path
$renderAuthorityPath = (Resolve-Path -LiteralPath $RenderAuthority -ErrorAction Stop).Path
if ([System.IO.Path]::GetFileName($renderAuthorityPath) -ne "hands-feet-nails-render-authority.json") {
    throw "M2 finalization requires the canonical hands-feet-nails-render-authority.json."
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -ne 0) { throw "Hands/feet/nails finalization requires a clean BodyRig checkout." }
$revision = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve canonical BodyRig checkout revision."
}

$renderValue = Get-Content -LiteralPath $renderAuthorityPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$renderValue.format -ne "bodyrig-hands-feet-nails-render-authority" -or [int]$renderValue.version -ne 1) {
    throw "M2 render authority format/version mismatch."
}
if ([string]$renderValue.bodyrig_revision -ne $revision) {
    throw "M2 finalization requires the exact BodyRig revision that produced the reviewed detail renders."
}
if ($renderValue.comparison_only -ne $true -or $renderValue.human_review_required -ne $true -or $renderValue.production_activation -ne $false) {
    throw "M2 render authority crossed the review-only boundary."
}

$python = Resolve-BodyRigPython
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Hands/feet/nails finalization requires Python 3.11+." }

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot
    $imported = (& $python -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not import BodyRig from the operator checkout." }
    $expectedRoot = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
    $actualModule = [System.IO.Path]::GetFullPath($imported)
    if (-not $actualModule.StartsWith($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Python imported BodyRig outside the current checkout: $actualModule"
    }

    & $python -m bodyrig.hands_feet_nails_release_authority_cli `
        --assembly-receipt $assemblyPath `
        --body-release-status $releasePath `
        --review-id $ReviewId `
        --render-authority $renderAuthorityPath
    if ($LASTEXITCODE -ne 0) { throw "Hands/feet/nails finalization failed." }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
