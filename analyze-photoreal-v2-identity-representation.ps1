param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [string]$Diagnostic = "",
    [ValidateRange(1,100)][int]$WorstCount = 12
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
$tool = Need-File (Join-Path $repoRoot "bodyrig\photoreal_identity_representation_outlier.py") "Identity representation outlier analyzer"
$RunDirectory = Need-Directory $RunDirectory "Photoreal resumed run"
$bank = Need-File (Join-Path $RunDirectory "identity-bank.json") "Identity bank"

$dirty = @(git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -ne 0) { throw "Identity representation outlier analysis requires a clean BodyRig checkout." }

$head = ([string](git -C $repoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git HEAD."
}

if ([string]::IsNullOrWhiteSpace($Diagnostic)) {
    $Diagnostic = Get-ChildItem -LiteralPath $RunDirectory -File -Filter "identity-representation-diagnostic-*.json" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    if ([string]::IsNullOrWhiteSpace($Diagnostic)) {
        throw "No identity representation diagnostic JSON found under run."
    }
}
$Diagnostic = Need-File $Diagnostic "Identity representation diagnostic"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$output = Join-Path $RunDirectory ("identity-representation-outlier-analysis-{0}.json" -f $stamp)
if (Test-Path -LiteralPath $output) {
    throw "Identity representation outlier output already exists: $output"
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - IDENTITY REPRESENTATION OUTLIERS"
Write-Host "Revision:    $head"
Write-Host "Run:         $RunDirectory"
Write-Host "Diagnostic:  $Diagnostic"
Write-Host "Worst refs:  $WorstCount"
Write-Host "Authority:   DIAGNOSTIC ONLY / FALSE"
Write-Host "Production:  FALSE"
Write-Host "============================================================"
Write-Host ""

$arguments = @(
    $tool,
    "--identity-bank", $bank,
    "--diagnostic", $Diagnostic,
    "--out", $output,
    "--worst-count", [string]$WorstCount
)
$lines = @(& $python @arguments 2>&1)
$exit = $LASTEXITCODE
if ($exit -ne 0) {
    foreach ($line in $lines) { Write-Host ([string]$line) }
    throw "Identity representation outlier analysis failed with exit code $exit."
}

$result = Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

Write-Host "Baseline leave-group-out:"
$baselineLine = "  min/median/max: {0} / {1} / {2}" -f $result.baseline_leave_group_out.min, $result.baseline_leave_group_out.median, $result.baseline_leave_group_out.max
Write-Host $baselineLine

Write-Host ""
Write-Host "Weakest groups:"
foreach ($group in @($result.groups_weakest_first | Select-Object -First 12)) {
    $line = "  {0,-12} refs={1,2}  LGO min/med={2}/{3}  profile med={4}  face px med={5}" -f $group.group_id, $group.reference_count, $group.leave_group_out_min, $group.leave_group_out_median, $group.profile_cosine_median, $group.face_min_dimension_pixels_median
    Write-Host $line
}

Write-Host ""
Write-Host "Worst references:"
foreach ($row in @($result.worst_references)) {
    $q = $row.quality
    $pose = $q.pose
    $yaw = if ($null -eq $pose) { "n/a" } else { [string]$pose.yaw_degrees }
    $pitch = if ($null -eq $pose) { "n/a" } else { [string]$pose.pitch_degrees }
    $line = "  {0,-12} t={1,8} eye={2,-5} LGO={3} profile={4} facepx={5} det={6} yaw={7} pitch={8}" -f $row.group_id, $row.timestamp_seconds, $row.eye, $row.baseline_leave_group_out_cosine, $row.profile_cosine, $q.bbox_min_dimension_pixels, $q.det_score, $yaw, $pitch
    Write-Host $line
}

Write-Host ""
Write-Host "Quality correlations vs LGO (Spearman):"
$correlationRows = @()
foreach ($property in $result.quality_correlations.PSObject.Properties) {
    $value = $property.Value.vs_leave_group_out.spearman
    if ($null -ne $value) {
        $correlationRows += [PSCustomObject]@{
            Name = $property.Name
            Value = [double]$value
            Magnitude = [math]::Abs([double]$value)
        }
    }
}
foreach ($item in @($correlationRows | Sort-Object Magnitude -Descending)) {
    Write-Host ("  {0,-30} {1,8:N3}" -f $item.Name, $item.Value)
}

Write-Host ""
Write-Host "Centered-FOV status counts:"
foreach ($property in $result.centered_status_counts.PSObject.Properties) {
    $parts = @()
    foreach ($status in $property.Value.PSObject.Properties) {
        $parts += ("{0}={1}" -f $status.Name, $status.Value)
    }
    Write-Host ("  {0,-20} {1}" -f $property.Name, ($parts -join ", "))
}

Write-Host ""
Write-Host "Stereo same-timestamp cosine:"
foreach ($property in $result.stereo_pair_cosine.PSObject.Properties) {
    $value = $property.Value
    Write-Host ("  {0,-20} n={1} min/med/max={2}/{3}/{4}" -f $property.Name, $value.count, $value.min, $value.median, $value.max)
}

Write-Host ""
Write-Host "Identity representation outlier analysis: PASS"
Write-Host "Analysis JSON: $output"
Write-Host "Authority: diagnostic-only; no identity matching, training, photoreal or production authority."
