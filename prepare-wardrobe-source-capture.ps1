param(
    [Parameter(Mandatory = $true)][string]$PersonId,
    [Parameter(Mandatory = $true)][string]$BodyRevision,
    [Parameter(Mandatory = $true)][string]$SelectionJson,
    [string]$Ffmpeg = "ffmpeg"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

function Resolve-BodyRigPython {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    return (Get-Command python -ErrorAction Stop).Source
}

$selectionPath = (Resolve-Path -LiteralPath $SelectionJson -ErrorAction Stop).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -ne 0) { throw "Wardrobe source capture requires a clean BodyRig checkout." }
$revision = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve canonical BodyRig checkout revision." }

$python = Resolve-BodyRigPython
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Wardrobe source capture requires Python 3.11+." }

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
    & $python -m bodyrig.wardrobe_source_capture_cli `
        --person-id $PersonId `
        --body-revision $BodyRevision `
        --bodyrig-revision $revision `
        --selection-json $selectionPath `
        --ffmpeg $Ffmpeg
    if ($LASTEXITCODE -ne 0) { throw "Wardrobe source capture failed." }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
