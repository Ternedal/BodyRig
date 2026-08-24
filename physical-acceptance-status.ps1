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

$argsList = @("-m", "bodyrig.acceptance_status_cli")
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
