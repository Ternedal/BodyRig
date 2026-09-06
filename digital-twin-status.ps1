param(
    [Parameter(Mandatory = $true)][string]$CompositionAuthorityDir,
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$LibraryRoot = "",
    [string]$BodyRigPython = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for BodyRig digital-twin operator status."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if (-not (Test-Path -LiteralPath $CompositionAuthorityDir -PathType Container)) {
    throw "M4 composition authority directory not found: $CompositionAuthorityDir"
}
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) {
    throw "Canonical physical acceptance directory not found: $AcceptanceDir"
}
$CompositionAuthorityDir = (Resolve-Path -LiteralPath $CompositionAuthorityDir).Path
$AcceptanceDir = (Resolve-Path -LiteralPath $AcceptanceDir).Path

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

$argsList = @(
    "-m", "bodyrig.digital_twin_operator_status_cli",
    "--composition-authority-dir", $CompositionAuthorityDir,
    "--acceptance-dir", $AcceptanceDir,
    "--operator-root", $repoRoot
)
if (-not [string]::IsNullOrWhiteSpace($LibraryRoot)) {
    $LibraryRoot = [System.IO.Path]::GetFullPath($LibraryRoot)
    $argsList += @("--library-root", $LibraryRoot)
}

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

    $statusLines = @(& $BodyRigPython @argsList)
    $exitCode = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

if ($exitCode -eq 1) {
    exit 1
}
if ($statusLines.Count -ne 1) {
    throw "BodyRig digital-twin status did not emit exactly one JSON document."
}
$statusJson = ([string]$statusLines[0]).Trim()
try { $status = $statusJson | ConvertFrom-Json }
catch { throw "BodyRig digital-twin status returned invalid JSON." }

if ($Json) {
    Write-Output $statusJson
    exit $exitCode
}

Write-Host "BodyRig full digital-twin status"
Write-Host "State:       $($status.state)"
Write-Host "Person:      $($status.person_id) / $($status.person_revision)"
Write-Host "Body:        $($status.body_id)"
Write-Host "Revision:    $($status.bodyrig_revision)"
Write-Host "M5 ready:    $($status.m5_ready)"
Write-Host "Twin ready:  $($status.digital_twin_ready)"
Write-Host "Next gate:   $($status.next_gate)"
Write-Host "Message:     $($status.message)"
if (-not [string]::IsNullOrWhiteSpace([string]$status.next_command)) {
    Write-Host ""
    Write-Host "Next command:"
    Write-Host ([string]$status.next_command)
}

exit $exitCode
