param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$pythonCandidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $pythonCandidate -PathType Leaf) {
    $pythonExe = (Resolve-Path -LiteralPath $pythonCandidate).Path
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "BodyRig Python was not found. Activate the validated BodyRig environment or create .venv first."
    }
    $pythonExe = $pythonCommand.Source
}

$versionText = (& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') {
    throw "Could not verify the BodyRig Python runtime."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "BodyRig high-fidelity readiness requires Python 3.11+; detected $versionText."
}

$expectedModule = (Resolve-Path (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    $moduleLines = @(& $pythonExe -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleLines.Count -ne 1) {
        throw "BodyRig Python could not prove imported module authority."
    }
    $actualModule = [System.IO.Path]::GetFullPath(([string]$moduleLines[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from a different checkout/package: $actualModule"
    }

    $argsList = @(
        "-m", "bodyrig.high_fidelity_release_readiness_cli",
        "--preview-job-id", $PreviewJobId,
        "--operator-root", $repoRoot
    )
    if ($Json) { $argsList += "--json" }

    Push-Location $repoRoot
    try {
        & $pythonExe @argsList
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

exit $exitCode
