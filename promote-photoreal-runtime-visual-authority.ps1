param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [Parameter(Mandatory = $true)][string]$P3Receipt,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Runtime visual authority promotion requires an exact clean BodyRig checkout."
}
$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headLines[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }

$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }
if (-not (Test-Path -LiteralPath $P3Receipt -PathType Leaf)) { throw "P3 physical runtime review receipt not found: $P3Receipt" }
$P3Receipt = (Resolve-Path -LiteralPath $P3Receipt).Path

$acceptance = Get-Content -LiteralPath (Join-Path $AcceptanceDir "bodyrig-acceptance.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if (([string]$acceptance.bodyrig_revision).ToLowerInvariant() -ne $head) {
    throw "Acceptance revision does not match current clean BodyRig HEAD."
}

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
$BodyRigPython = (Resolve-Path -LiteralPath $BodyRigPython).Path
$expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$moduleLines = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleLines.Count -ne 1) {
    throw "BodyRig Python could not prove checkout-bound import for visual authority promotion."
}
$actualModule = (Resolve-Path -LiteralPath ([string]$moduleLines[0]).Trim()).Path
if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports a different checkout/package: $actualModule"
}

$output = @(& $BodyRigPython -m bodyrig.runtime_visual_authority promote --acceptance-dir $AcceptanceDir --p3-receipt $P3Receipt 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) { throw "Photoreal runtime visual authority promotion failed with code $code." }

Write-Host "BodyRig runtime visualization authority: PASS"
Write-Host "The exact runtime/avatar.vrm bytes are bound to a human-reviewed Photoreal P3 PASS."
Write-Host "Production activation: FALSE"
