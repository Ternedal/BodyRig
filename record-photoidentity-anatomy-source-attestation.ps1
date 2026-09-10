param(
    [Parameter(Mandatory = $true)][string]$SweepRoot,
    [string[]]$RearRef = @(),
    [string[]]$TorsoRef = @(),
    [string[]]$WaistRef = @(),
    [Parameter(Mandatory = $true)][switch]$ConfirmRearView,
    [Parameter(Mandatory = $true)][switch]$ConfirmTorsoChestAnatomyVisible,
    [Parameter(Mandatory = $true)][switch]$ConfirmWaistHipsAnatomyVisible,
    [Parameter(Mandatory = $true)][string]$QualityNote,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Executable {
    param([string]$Value,[string]$Fallback,[string]$Label)
    $candidate = if ([string]::IsNullOrWhiteSpace($Value)) { $Fallback } else { $Value }
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "$Label executable not found: $candidate" }
    return $command.Source
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig source-only anatomy attestation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if (-not $ConfirmRearView -or -not $ConfirmTorsoChestAnatomyVisible -or -not $ConfirmWaistHipsAnatomyVisible) {
    throw "Atomic anatomy attestation requires all three explicit confirmation switches."
}
$note = $QualityNote.Trim()
if ($note.Length -lt 20 -or ($note.StartsWith("<") -and $note.EndsWith(">"))) {
    throw "Replace the quality-note placeholder with your actual source review."
}
if ($RearRef.Count -lt 1) { throw "At least one rear-body source reference is required." }
if ($TorsoRef.Count -lt 2) { throw "At least two torso/chest source references are required." }
if ($WaistRef.Count -lt 2) { throw "At least two waist/hips source references are required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not establish exact BodyRig Git authority." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig Git HEAD is not canonical." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Anatomy source attestation requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = Need-Executable -Value "" -Fallback "python" -Label "BodyRig Python" }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "BodyRig Python could not prove checkout-bound imports." }
$actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports from a different checkout: $actualModule"
}

$SweepRoot = Need-Directory -Path $SweepRoot -Label "Photoidentity sweep root"
$discovery = Need-File -Path (Join-Path $SweepRoot "anatomy-source-candidates.json") -Label "Anatomy source discovery manifest"
$revisionRaw = @(& $BodyRigPython -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8'))['bodyrig_revision'])" $discovery 2>&1)
if ($LASTEXITCODE -ne 0 -or $revisionRaw.Count -ne 1) { throw "Could not read anatomy discovery revision." }
$evidenceRevision = ([string]$revisionRaw[0]).Trim().ToLowerInvariant()
if ($evidenceRevision -ne $head) {
    throw "Anatomy source discovery belongs to BodyRig revision $evidenceRevision, current checkout is $head. Refusing cross-revision human authority."
}

$argsList = @(
    "-m", "bodyrig.photoidentity_anatomy_source_attestation",
    "--sweep-root", $SweepRoot,
    "--quality-note", $note,
    "--confirm-rear-view",
    "--confirm-torso-chest-anatomy-visible",
    "--confirm-waist-hips-anatomy-visible"
)
foreach ($reference in $RearRef) {
    if (-not [string]::IsNullOrWhiteSpace($reference)) { $argsList += @("--rear-ref", $reference.Trim()) }
}
foreach ($reference in $TorsoRef) {
    if (-not [string]::IsNullOrWhiteSpace($reference)) { $argsList += @("--torso-ref", $reference.Trim()) }
}
foreach ($reference in $WaistRef) {
    if (-not [string]::IsNullOrWhiteSpace($reference)) { $argsList += @("--waist-ref", $reference.Trim()) }
}

Write-Host "BodyRig source-only anatomy attestation"
Write-Host "Revision: $head"
Write-Host "Sweep:    $SweepRoot"
Write-Host "Policy:   explicit human source review; actual visible anatomy only; no avatar render; no generic guessing"
Write-Host ""

& $BodyRigPython @argsList
if ($LASTEXITCODE -ne 0) { throw "BodyRig source-only anatomy attestation failed with exit code $LASTEXITCODE." }
