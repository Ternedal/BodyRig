param(
    [Parameter(Mandatory = $true)]
    [string]$PersonId,

    [Parameter(Mandatory = $true)]
    [string]$PersonRevision,

    [Parameter(Mandatory = $true)]
    [string]$BodyReleaseStatus,

    [Parameter(Mandatory = $true)]
    [string]$HandsReleaseId,

    [Parameter(Mandatory = $true)]
    [string]$WardrobeReleaseId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-BodyRigPython {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    $command = Get-Command python -ErrorAction Stop
    return $command.Source
}

$statusPath = (Resolve-Path -LiteralPath $BodyReleaseStatus -ErrorAction Stop).Path
if ($PersonId -notmatch '^person-[0-9a-f]{32}$') { throw "PersonId is not canonical." }
if ($PersonRevision -notmatch '^person-r[0-9]{4}$') { throw "PersonRevision is not canonical." }
if ($HandsReleaseId -notmatch '^hfnrelease-[0-9a-f]{32}$') { throw "HandsReleaseId is not a canonical finalized M2 release id." }
if ($WardrobeReleaseId -notmatch '^wardrelease-[0-9a-f]{32}$') { throw "WardrobeReleaseId is not a canonical finalized M3 release id." }

$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -ne 0) { throw "Digital-twin M4 composition requires a clean BodyRig checkout." }
$revision = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve canonical BodyRig checkout revision." }

$python = Resolve-BodyRigPython
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Digital-twin M4 composition requires Python 3.11+." }
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

    & $python -m bodyrig.digital_twin_composition_cli `
        --person-id $PersonId `
        --person-revision $PersonRevision `
        --body-release-status $statusPath `
        --hands-release-id $HandsReleaseId `
        --wardrobe-release-id $WardrobeReleaseId `
        --bodyrig-revision $revision
    if ($LASTEXITCODE -ne 0) { throw "Digital-twin M4 composition failed." }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
