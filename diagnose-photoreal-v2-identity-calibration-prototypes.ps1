param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][string]$ReviewRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$python = Need-File (Join-Path $repoRoot ".venv\Scripts\python.exe") "BodyRig Windows Python"
$tool = Need-File (Join-Path $repoRoot "bodyrig\photoreal_identity_calibration_prototype_diagnostic.py") "Prototype calibration diagnostic"
$RunDirectory = Need-Directory $RunDirectory "Photoreal resumed run"
$ReviewRoot = Need-Directory $ReviewRoot "Identity group review root"

$dirty = @(git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -ne 0) { throw "Prototype calibration diagnostic requires a clean BodyRig checkout." }

$head = ([string](git -C $repoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git HEAD."
}

$bank = Need-File (Join-Path $RunDirectory "identity-bank.json") "Identity bank"
$plan = Need-File (Join-Path $RunDirectory "identity-calibration-plan.json") "Identity calibration plan"
$negatives = Need-File (Join-Path $RunDirectory "identity-calibration-extractor\output\negative-observations.json") "Negative identity observations"
$attestation = Need-File (Join-Path $ReviewRoot "identity-group-attestation.json") "Identity group attestation"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$output = Join-Path $RunDirectory ("identity-calibration-prototype-diagnostic-{0}.json" -f $stamp)
if (Test-Path -LiteralPath $output) {
    throw "Prototype calibration diagnostic output already exists: $output"
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - IDENTITY CALIBRATION PROTOTYPES"
Write-Host "Revision:    $head"
Write-Host "Run:         $RunDirectory"
Write-Host "Review:      $ReviewRoot"
Write-Host "Authority:   DIAGNOSTIC ONLY / FALSE"
Write-Host "Production:  FALSE"
Write-Host "============================================================"
Write-Host ""

$argsList = @(
    $tool,
    "--identity-bank", $bank,
    "--calibration-plan", $plan,
    "--negative-observations", $negatives,
    "--identity-attestation", $attestation,
    "--out", $output
)

$lines = @(& $python @argsList 2>&1)
$exit = $LASTEXITCODE
if ($exit -ne 0) {
    foreach ($line in $lines) { Write-Host ([string]$line) }
    throw "Prototype calibration diagnostic failed with exit code $exit."
}

$result = Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

Write-Host "Variant separation:"
foreach ($property in $result.variants.PSObject.Properties) {
    $value = $property.Value
    Write-Host ("  {0,-30} posFloor={1} negCeil={2} margin={3} pass={4}" -f $property.Name, $value.positive_floor, $value.negative_ceiling, $value.observed_separation_margin, $value.would_meet_margin)
}

Write-Host ""
Write-Host "Weakest group prototypes:"
foreach ($group in @($result.groups_weakest_first)) {
    Write-Host ("  {0,-12} refs={1,2} LGO={2} nearest={3} ({4})" -f $group.group_id, $group.reference_count, $group.group_balanced_leave_group_out_cosine, $group.nearest_other_group_id, $group.nearest_other_group_cosine)
}

Write-Host ""
Write-Host "Highest negative collisions:"
foreach ($row in @($result.negatives_highest_collision_first)) {
    Write-Host ("  performer={0,-8} current={1} balanced={2} nearestPrototype={3}" -f $row.subject_performer_id, $row.current_target_cosine, $row.group_balanced_target_cosine, $row.nearest_group_prototype_cosine)
}

Write-Host ""
Write-Host "Identity calibration prototype diagnostic: PASS"
Write-Host "Diagnostic JSON: $output"
Write-Host "Authority: diagnostic-only; no identity matching, training, photoreal or production authority."
