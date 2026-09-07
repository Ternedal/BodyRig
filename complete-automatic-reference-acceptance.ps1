param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$Output = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $BodyRigPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $BodyRigPython -PathType Leaf)) {
    throw "BodyRig Python not found: $BodyRigPython"
}
$BodyRigPython = (Resolve-Path -LiteralPath $BodyRigPython).Path

$expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$actualModuleRaw = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualModuleRaw.Count -ne 1) {
    throw "BodyRig Python could not prove a single checkout-bound bodyrig import for automatic release."
}
$actualModulePath = ([string]$actualModuleRaw[0]).Trim()
if (-not (Test-Path -LiteralPath $actualModulePath -PathType Leaf)) {
    throw "BodyRig Python returned an invalid bodyrig import path for automatic release."
}
$actualModule = (Resolve-Path -LiteralPath $actualModulePath).Path
if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from unexpected location: $actualModule. Expected checkout authority: $expectedModule"
}

$args = @("-m", "bodyrig.automatic_release_gate", "--acceptance-dir", $AcceptanceDir, "--repo-root", $repoRoot)
if (-not [string]::IsNullOrWhiteSpace($Output)) {
    $args += @("--output", [IO.Path]::GetFullPath($Output))
}
& $BodyRigPython @args
if ($LASTEXITCODE -ne 0) { throw "BodyRig automatic production gate failed with exit code $LASTEXITCODE." }
exit 0
