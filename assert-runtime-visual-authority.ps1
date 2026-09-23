param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) {
    throw "Acceptance directory not found: $AcceptanceDir"
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $BodyRigPython = (Resolve-Path -LiteralPath $candidate).Path
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found for runtime visual authority." }
        $BodyRigPython = $python.Source
    }
}
if (-not (Test-Path -LiteralPath $BodyRigPython -PathType Leaf)) {
    throw "BodyRig Python not found: $BodyRigPython"
}
$BodyRigPython = (Resolve-Path -LiteralPath $BodyRigPython).Path

$expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$actualLines = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualLines.Count -ne 1) {
    throw "BodyRig Python could not prove checkout-bound import for runtime visual authority."
}
$actualModule = (Resolve-Path -LiteralPath ([string]$actualLines[0]).Trim()).Path
if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports a different checkout/package: $actualModule"
}

$output = @(& $BodyRigPython -m bodyrig.runtime_visual_authority validate --acceptance-dir $AcceptanceDir 2>&1)
$code = $LASTEXITCODE
if ($code -ne 0) {
    $detail = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    throw "Renderer visualization QUARANTINED. Exact runtime avatar has no valid Photoreal P3 visual authority.$([Environment]::NewLine)$detail"
}
