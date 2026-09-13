param(
    [Parameter(Mandatory = $true)]
    [string]$PersonId,

    [Parameter(Mandatory = $true)]
    [string]$BodyRevision,

    [Parameter(Mandatory = $true)]
    [string]$CaptureId,

    [Parameter(Mandatory = $true)]
    [string]$Distribution,

    [Parameter(Mandatory = $true)]
    [string]$OpenPose,

    [string]$FfmpegExe = "ffmpeg",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Hands/feet/nails landmark evidence is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for hands/feet/nails landmark evidence."
}

function Resolve-BodyRigPython {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $venv).Path
    }
    $command = Get-Command python -ErrorAction Stop
    return $command.Source
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -ne 0) { throw "Hands/feet/nails landmark evidence requires a clean BodyRig checkout." }
$revision = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve canonical BodyRig checkout revision."
}

if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
if ([string]::IsNullOrWhiteSpace($OpenPose) -or -not $OpenPose.StartsWith('/')) {
    throw "OpenPose must be an absolute Linux path inside the selected WSL distribution."
}

$python = Resolve-BodyRigPython
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Hands/feet/nails landmark evidence requires Python 3.11+." }

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

    & $python -m bodyrig.hands_feet_nails_landmark_evidence_cli `
        --person-id $PersonId `
        --body-revision $BodyRevision `
        --capture-id $CaptureId `
        --bodyrig-revision $revision `
        --ffmpeg-exe $FfmpegExe `
        --distribution $Distribution `
        --openpose $OpenPose `
        --wsl-exe $WslExe
    if ($LASTEXITCODE -ne 0) { throw "Hands/feet/nails landmark evidence failed." }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
