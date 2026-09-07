param(
    [ValidatePattern('^$|^job-[0-9a-f]{32}$')]
    [string]$PreferredJobId = "",
    [ValidatePattern('^$|^person-[0-9a-f]{32}$')]
    [string]$PersonId = "",
    [string]$PerformerId = "",
    [ValidatePattern('^$|^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the BodyRig rig-window planner."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "BodyRig repo virtualenv is required before rig-window planning: $python"
}
$python = (Resolve-Path -LiteralPath $python).Path

$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not resolve exact BodyRig checkout revision."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Could not verify BodyRig checkout cleanliness."
}
if ($dirty.Count -gt 0) {
    throw "BodyRig checkout is dirty. Rig-window planning refuses to authorize a physical next command."
}

$expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot
    $moduleRaw = @(& $python -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) {
        throw "BodyRig Python could not prove checkout-bound import authority."
    }
    $actualModule = (Resolve-Path -LiteralPath ([string]$moduleRaw[0]).Trim()).Path
    if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from unexpected location: $actualModule. Expected checkout authority: $expectedModule"
    }

    $argsList = @("-m", "bodyrig.rig_window_policy", "--repo-root", $repoRoot)
    if (-not [string]::IsNullOrWhiteSpace($PreferredJobId)) {
        $argsList += @("--preferred-job-id", $PreferredJobId)
    }
    if (-not [string]::IsNullOrWhiteSpace($PersonId)) {
        $argsList += @("--person-id", $PersonId)
    }
    if (-not [string]::IsNullOrWhiteSpace($PerformerId)) {
        $argsList += @("--performer-id", $PerformerId)
    }
    if (-not [string]::IsNullOrWhiteSpace($BodyId)) {
        $argsList += @("--body-id", $BodyId)
    }
    if ($Json) {
        $argsList += "--json"
    }

    & $python @argsList
    exit $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
