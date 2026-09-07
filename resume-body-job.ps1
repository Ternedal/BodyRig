param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$JobId,
    [string]$BodyRigPython = "",
    [switch]$AssessOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for BodyRig historical Gate A rescue."
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
if (-not (Test-Path -LiteralPath $BodyRigPython -PathType Leaf)) {
    throw "BodyRig Python not found: $BodyRigPython"
}
$BodyRigPython = (Resolve-Path -LiteralPath $BodyRigPython).Path

$expectedModulePath = Join-Path $repoRoot "bodyrig\__init__.py"
if (-not (Test-Path -LiteralPath $expectedModulePath -PathType Leaf)) {
    throw "BodyRig checkout module not found: $expectedModulePath"
}
$expectedModulePath = (Resolve-Path -LiteralPath $expectedModulePath).Path

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot
    $importLines = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
    if ($LASTEXITCODE -ne 0 -or $importLines.Count -ne 1) {
        throw "BodyRig Python could not prove a single checkout-bound bodyrig import."
    }
    $actualModulePath = ([string]$importLines[0]).Trim()
    if ([string]::IsNullOrWhiteSpace($actualModulePath) -or -not (Test-Path -LiteralPath $actualModulePath -PathType Leaf)) {
        throw "BodyRig Python returned an invalid bodyrig import path."
    }
    $actualModulePath = (Resolve-Path -LiteralPath $actualModulePath).Path
    if (-not [string]::Equals($actualModulePath, $expectedModulePath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from unexpected location: $actualModulePath. Expected checkout authority: $expectedModulePath"
    }

    if ($AssessOnly) {
        & $BodyRigPython -m bodyrig.resume_body_job $JobId --assess-only
    } else {
        & $BodyRigPython -m bodyrig.resume_body_job $JobId
    }
    $exitCode = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

if ($exitCode -ne 0) {
    $mode = if ($AssessOnly) { "assessment" } else { "rescue" }
    throw "BodyRig historical Gate A $mode failed with exit code $exitCode"
}
exit 0
