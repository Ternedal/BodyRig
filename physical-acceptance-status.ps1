param(
    [string]$SessionReport = "",
    [string]$AcceptanceDir = "",
    [string]$BodyRigPython = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($SessionReport) -eq [string]::IsNullOrWhiteSpace($AcceptanceDir)) {
    throw "Pass exactly one of -SessionReport or -AcceptanceDir."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $BodyRigPython = $candidate
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found. Pass -BodyRigPython explicitly." }
        $BodyRigPython = $python.Source
    }
}
if (-not (Test-Path -LiteralPath $BodyRigPython -PathType Leaf)) { throw "BodyRig Python not found: $BodyRigPython" }
$BodyRigPython = (Resolve-Path -LiteralPath $BodyRigPython).Path

$expectedBodyRigModulePath = Join-Path $repoRoot "bodyrig\__init__.py"
if (-not (Test-Path -LiteralPath $expectedBodyRigModulePath -PathType Leaf)) {
    throw "BodyRig checkout module not found: $expectedBodyRigModulePath"
}
$expectedBodyRigModule = (Resolve-Path -LiteralPath $expectedBodyRigModulePath).Path
$bodyRigAuthorityRaw = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
if ($LASTEXITCODE -ne 0 -or $bodyRigAuthorityRaw.Count -ne 1) {
    throw "BodyRig Python could not prove a single checkout-bound bodyrig import for acceptance status."
}
$actualBodyRigModulePath = ([string]$bodyRigAuthorityRaw[0]).Trim()
if ([string]::IsNullOrWhiteSpace($actualBodyRigModulePath) -or -not (Test-Path -LiteralPath $actualBodyRigModulePath -PathType Leaf)) {
    throw "BodyRig Python returned an invalid bodyrig import path for acceptance status."
}
$actualBodyRigModule = (Resolve-Path -LiteralPath $actualBodyRigModulePath).Path
if (-not [string]::Equals($actualBodyRigModule, $expectedBodyRigModule, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from unexpected location: $actualBodyRigModule. Expected checkout authority: $expectedBodyRigModule"
}

$argsList = @("-m", "bodyrig.acceptance_status_cli", "--operator-root", $repoRoot)
if (-not [string]::IsNullOrWhiteSpace($SessionReport)) {
    if (-not (Test-Path -LiteralPath $SessionReport -PathType Leaf)) { throw "Physical clone session report not found: $SessionReport" }
    $argsList += @("--session-report", (Resolve-Path -LiteralPath $SessionReport).Path)
} else {
    if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }
    $argsList += @("--acceptance-dir", (Resolve-Path -LiteralPath $AcceptanceDir).Path)
}
if ($Json) { $argsList += "--json" }

& $BodyRigPython @argsList
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { exit $exitCode }
exit 0
