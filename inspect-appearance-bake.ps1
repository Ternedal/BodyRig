param(
    [Parameter(Mandatory = $true)][string]$Package,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $BodyRigPython = (Resolve-Path -LiteralPath $candidate).Path
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
if (-not (Test-Path -LiteralPath $BodyRigPython -PathType Leaf)) {
    throw "BodyRig Python not found: $BodyRigPython"
}
if (-not (Test-Path -LiteralPath $Package -PathType Leaf)) {
    throw "BodyRig package not found: $Package"
}

$expected = (Resolve-Path (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$actual = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
if ($LASTEXITCODE -ne 0 -or $actual.Count -ne 1 -or -not [string]::Equals(([string]$actual[0]).Trim(), $expected, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python does not import from this checkout."
}

& $BodyRigPython -m bodyrig.appearance_bake_diagnostics (Resolve-Path -LiteralPath $Package).Path
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 0 }
exit $code
