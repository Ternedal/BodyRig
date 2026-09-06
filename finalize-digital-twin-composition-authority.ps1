param(
    [Parameter(Mandatory = $true)]
    [string]$AssemblyReceipt,

    [Parameter(Mandatory = $true)]
    [string]$BodyReleaseStatus,

    [Parameter(Mandatory = $true)]
    [string]$HandsNailsAuthority,

    [Parameter(Mandatory = $true)]
    [string]$WardrobeAuthority,

    [Parameter(Mandatory = $true)]
    [string]$BodyPackage
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

$assemblyPath = (Resolve-Path -LiteralPath $AssemblyReceipt -ErrorAction Stop).Path
$releasePath = (Resolve-Path -LiteralPath $BodyReleaseStatus -ErrorAction Stop).Path
$handsPath = (Resolve-Path -LiteralPath $HandsNailsAuthority -ErrorAction Stop).Path
$wardrobePath = (Resolve-Path -LiteralPath $WardrobeAuthority -ErrorAction Stop).Path
$packagePath = (Resolve-Path -LiteralPath $BodyPackage -ErrorAction Stop).Path

$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -ne 0) { throw "M4 composition finalization requires a clean BodyRig checkout." }
$revision = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve canonical BodyRig checkout revision." }

$python = Resolve-BodyRigPython
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "M4 composition finalization requires Python 3.11+." }

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

    & $python -m bodyrig.digital_twin_composition_authority_cli `
        --assembly-receipt $assemblyPath `
        --body-release-status $releasePath `
        --hands-nails-authority $handsPath `
        --wardrobe-authority $wardrobePath `
        --body-package $packagePath `
        --bodyrig-revision $revision
    if ($LASTEXITCODE -ne 0) { throw "M4 digital-twin composition finalization failed." }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
