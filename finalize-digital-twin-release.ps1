param(
    [Parameter(Mandatory = $true)][string]$CompositionAuthorityDir,
    [Parameter(Mandatory = $true)][string]$AcceptanceDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig M6 final-release path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for canonical BodyRig M6 final release."
}
if ($null -eq (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    throw "PowerShell 7 executable (pwsh) was not found."
}

function Need-Revision([string]$Value, [string]$Label) {
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical 40-character Git SHA." }
    return $normalized
}
function Resolve-BodyRigPython {
    $venv = Join-Path $script:RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    return (Get-Command python -ErrorAction Stop).Source
}

$script:RepoRoot = (Resolve-Path $PSScriptRoot).Path
$CompositionAuthorityDir = [System.IO.Path]::GetFullPath($CompositionAuthorityDir)
$AcceptanceDir = [System.IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $CompositionAuthorityDir -PathType Container)) { throw "M4 composition authority directory not found: $CompositionAuthorityDir" }
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Canonical physical acceptance directory not found: $AcceptanceDir" }

$authorityPath = Join-Path $CompositionAuthorityDir "authority.json"
$gateAPath = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
$bodyReleasePath = Join-Path $AcceptanceDir "bodyrig-release-acceptance.json"
$windowsRealization = Join-Path (Join-Path $AcceptanceDir "digital-twin-windows-evidence") "realization.json"
$questRealization = Join-Path (Join-Path $AcceptanceDir "digital-twin-quest-evidence") "realization.json"
foreach ($required in @($authorityPath, $gateAPath, $bodyReleasePath, $windowsRealization, $questRealization)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required M6 authority input missing: $required" }
}

$currentHeadLines = @(& git -C $script:RepoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $currentHeadLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
$currentHead = Need-Revision ([string]$currentHeadLines[0]) "current BodyRig HEAD"
$dirty = @(& git -C $script:RepoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; M6 final release requires the exact clean authority revision." }

try { $composition = Get-Content -LiteralPath $authorityPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "M4 composition authority is not valid JSON: $authorityPath" }
try { $gateA = Get-Content -LiteralPath $gateAPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Gate A acceptance authority is not valid JSON: $gateAPath" }
try { $bodyRelease = Get-Content -LiteralPath $bodyReleasePath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Canonical body final release is not valid JSON: $bodyReleasePath" }

$compositionRevision = Need-Revision ([string]$composition.bodyrig_revision) "M4 composition revision"
$gateRevision = Need-Revision ([string]$gateA.bodyrig_revision) "Gate A revision"
$releaseRevision = Need-Revision ([string]$bodyRelease.bodyrig_revision) "body final-release revision"
if ($compositionRevision -ne $currentHead -or $gateRevision -ne $currentHead -or $releaseRevision -ne $currentHead) {
    throw "M6 requires current HEAD, M4 composition, Gate A and canonical body final release to share the exact same BodyRig revision."
}
if ($bodyRelease.production_activation -ne $true -or $bodyRelease.release_gate_pass -ne $true) {
    throw "Canonical body final release is not an activating PASS."
}

$python = Resolve-BodyRigPython
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "M6 final release requires Python 3.11+." }
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $script:RepoRoot
    $imported = (& $python -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not import BodyRig from the operator checkout." }
    $expectedRoot = [System.IO.Path]::GetFullPath($script:RepoRoot).TrimEnd('\') + '\'
    if (-not ([System.IO.Path]::GetFullPath($imported)).StartsWith($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Python imported BodyRig outside the current checkout: $imported"
    }

    & $python -m bodyrig.digital_twin_release_cli `
        --composition-authority-dir $CompositionAuthorityDir `
        --acceptance-dir $AcceptanceDir `
        --bodyrig-revision $currentHead
    if ($LASTEXITCODE -ne 0) { throw "Canonical M6 digital-twin finalization failed." }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig M6 canonical full digital-twin release: PASS"
Write-Host "The exact Person Revision is now eligible for digital_twin_ready=true and production_activation=true."
exit 0
