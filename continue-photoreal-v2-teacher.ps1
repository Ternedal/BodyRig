param(
    [Parameter(Mandatory = $true)][string]$P0Root,
    [string]$SummaryPath = "",
    [string]$PerformerId = "42",
    [string]$WorkRoot = "",
    [string]$BodyRigPython = "",
    [string]$SelectedEpochId = "",
    [string[]]$SourceGroup = @(),
    [string]$ReviewedBy = "",
    [string]$ReviewNotes = "",
    [switch]$ApproveHumanReview
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is unreadable JSON: $Path" }
}

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Test-NumericV1 {
    param([AllowNull()]$Value)
    if ($null -eq $Value -or $Value -is [bool]) { return $false }
    try { $typeCode = [Type]::GetTypeCode($Value.GetType()) } catch { return $false }
    $numericTypes = @(
        [TypeCode]::Byte,[TypeCode]::Decimal,[TypeCode]::Double,[TypeCode]::Int16,
        [TypeCode]::Int32,[TypeCode]::Int64,[TypeCode]::SByte,[TypeCode]::Single,
        [TypeCode]::UInt16,[TypeCode]::UInt32,[TypeCode]::UInt64
    )
    if ($numericTypes -notcontains $typeCode) { return $false }
    $number = [double]$Value
    return (-not [double]::IsNaN($number)) -and (-not [double]::IsInfinity($number)) -and $number -eq 1.0
}

function Test-StrictBoolean {
    param([AllowNull()]$Value,[Parameter(Mandatory = $true)][bool]$Expected)
    return ($Value -is [bool]) -and ([bool]$Value -eq $Expected)
}

function Same-Path {
    param([Parameter(Mandatory = $true)][string]$Left,[Parameter(Mandatory = $true)][string]$Right)
    $leftPath = [IO.Path]::GetFullPath($Left)
    $rightPath = [IO.Path]::GetFullPath($Right)
    return [string]::Equals($leftPath, $rightPath, [StringComparison]::OrdinalIgnoreCase)
}

function Find-Summary {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedPerformerId
    )
    $parent = Split-Path -Parent $Root
    $matches = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in @(Get-ChildItem -LiteralPath $parent -Filter "*-summary.json" -File -ErrorAction SilentlyContinue)) {
        try { $value = Read-Json -Path $candidate.FullName -Label "Photoreal overnight summary candidate" }
        catch { continue }
        if ([string]$value.format -ne "bodyrig-photoreal-v2-overnight-summary") { continue }
        if ([string]$value.performer_id -ne $ExpectedPerformerId) { continue }
        if ([string]::IsNullOrWhiteSpace([string]$value.output_root)) { continue }
        try {
            if (Same-Path -Left ([string]$value.output_root) -Right $Root) {
                $matches.Add($candidate.FullName)
            }
        } catch { continue }
    }
    if ($matches.Count -eq 0) {
        throw "Could not discover the overnight summary bound to P0Root. Pass -SummaryPath explicitly."
    }
    if ($matches.Count -gt 1) {
        throw "Multiple overnight summaries bind this P0Root. Pass -SummaryPath explicitly."
    }
    return $matches[0]
}

function Resolve-Python {
    param([string]$Requested,[Parameter(Mandatory = $true)][string]$RepoRoot)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Need-File -Path $Requested -Label "BodyRig Python"
    }
    $venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "Python not found. Pass -BodyRigPython explicitly." }
    return $command.Source
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1) { throw "Could not resolve BodyRig Git branch." }
if (([string]$branch[0]).Trim() -ne "main") {
    throw "Post-P0 continuation requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Post-P0 continuation requires an exact clean BodyRig checkout."
}

$P0Root = Need-Directory -Path $P0Root -Label "P0 root"
$statusPath = Need-File -Path (Join-Path $P0Root "p0-status.json") -Label "P0 status"
$status = Read-Json -Path $statusPath -Label "P0 status"
if ([string]$status.format -ne "bodyrig-photoreal-p0-status" -or -not (Test-NumericV1 -Value $status.version)) {
    throw "P0 status format/version mismatch."
}
if ([string]$status.performer_id -ne $PerformerId) { throw "P0 status performer mismatch." }
$revision = ([string]$status.bodyrig_revision).Trim().ToLowerInvariant()
if ($revision -notmatch '^[0-9a-f]{40}$') { throw "P0 status BodyRig revision is invalid." }
if ([string]$status.status -ne "teacher-training-authorized") { throw "P0 status does not authorize teacher training." }
if (@($status.blockers).Count -ne 0) { throw "P0 status still contains blockers." }
if (-not (Test-StrictBoolean -Value $status.teacher_training_authorized -Expected $true)) { throw "P0 status lacks teacher-training authority." }
if (-not (Test-StrictBoolean -Value $status.human_visual_acceptance_required -Expected $true)) { throw "P0 status removed human visual acceptance." }
if (-not (Test-StrictBoolean -Value $status.photoreal_acceptance_authority -Expected $false)) { throw "P0 status crossed photoreal acceptance authority." }
if (-not (Test-StrictBoolean -Value $status.production_activation -Expected $false)) { throw "P0 status crossed production authority." }

if ([string]::IsNullOrWhiteSpace($SummaryPath)) {
    $SummaryPath = Find-Summary -Root $P0Root -ExpectedPerformerId $PerformerId
} else {
    $SummaryPath = Need-File -Path $SummaryPath -Label "Photoreal overnight summary"
}

if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    $WorkRoot = "$P0Root-teacher"
}
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
$readinessPath = Join-Path $P0Root "P0_DOWNSTREAM_READINESS.json"

if (-not (Test-Path -LiteralPath $readinessPath -PathType Leaf)) {
    $verifier = Need-File -Path (Join-Path $repoRoot "review-tools\VERIFY_PHYSICAL_P0_READY.ps1") -Label "P0 readiness verifier"
    $shell = (Get-Process -Id $PID).Path
    $verifyArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $verifier,
        "-SummaryPath", $SummaryPath,
        "-ExpectedBodyRigRevision", $revision,
        "-ExpectedPerformerId", $PerformerId
    )
    Write-Host ""
    Write-Host "=== VERIFY EXACT P0 READINESS ==="
    & $shell @verifyArgs
    $verifyCode = $LASTEXITCODE
    if ($verifyCode -eq 2) {
        Write-Host "Post-P0 continuation: BLOCKED by exact-head software qualification."
        exit 2
    }
    if ($verifyCode -ne 0) {
        throw "P0 readiness verifier failed with code $verifyCode."
    }
}
$readinessPath = Need-File -Path $readinessPath -Label "P0 downstream readiness"

$Python = Resolve-Python -Requested $BodyRigPython -RepoRoot $repoRoot
$arguments = @(
    "-m", "bodyrig.photoreal_post_p0_continuation_cli",
    "--p0-root", $P0Root,
    "--readiness", $readinessPath,
    "--work-root", $WorkRoot,
    "--performer-id", $PerformerId
)
if ($ApproveHumanReview) {
    if ([string]::IsNullOrWhiteSpace($SelectedEpochId)) { throw "-SelectedEpochId is required with -ApproveHumanReview." }
    if ($SourceGroup.Count -eq 0) { throw "At least one -SourceGroup is required with -ApproveHumanReview." }
    if ([string]::IsNullOrWhiteSpace($ReviewedBy)) { throw "-ReviewedBy is required with -ApproveHumanReview." }
    if ([string]::IsNullOrWhiteSpace($ReviewNotes)) { throw "-ReviewNotes is required with -ApproveHumanReview." }
    $arguments += @("--selected-epoch-id", $SelectedEpochId)
    foreach ($group in $SourceGroup) {
        if ([string]::IsNullOrWhiteSpace($group)) { throw "-SourceGroup values must be non-empty." }
        $arguments += @("--source-group", $group)
    }
    $arguments += @("--reviewed-by", $ReviewedBy, "--review-notes", $ReviewNotes, "--approve-human-review")
}

$oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$separator = [IO.Path]::PathSeparator
$newPythonPath = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $repoRoot } else { "$repoRoot$separator$oldPythonPath" }
[Environment]::SetEnvironmentVariable("PYTHONPATH", $newPythonPath, "Process")
try {
    Write-Host ""
    Write-Host "=== ADVANCE POST-P0 TEACHER HANDOFF ==="
    $output = @(& $Python @arguments)
    $code = $LASTEXITCODE
} finally {
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process")
}

foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -notin @(0, 2)) {
    throw "Post-P0 continuation failed with code $code."
}
if ($output.Count -eq 0) { throw "Post-P0 continuation returned no status payload." }

try { $result = ([string]$output[-1]) | ConvertFrom-Json }
catch { throw "Post-P0 continuation returned invalid status JSON." }

Write-Host ""
if ($code -eq 2) {
    Write-Host "BODYRIG PHOTOREAL POST-P0: HUMAN REVIEW REQUIRED"
    Write-Host "Review template: $($result.appearance_epoch_review_template)"
    Write-Host "Candidate source groups:"
    foreach ($group in @($result.candidate_source_groups)) {
        Write-Host ("  {0,-10} {1}" -f [string]$group.split, [string]$group.group_id)
    }
    Write-Host ""
    Write-Host "Rerun this script only after visually reviewing the source groups."
    Write-Host "Supply -SelectedEpochId, repeated -SourceGroup values covering train + evaluation,"
    Write-Host "-ReviewedBy, -ReviewNotes and -ApproveHumanReview."
    Write-Host "Photoreal acceptance: FALSE"
    Write-Host "Production activation: FALSE"
    exit 2
}

Write-Host "BODYRIG PHOTOREAL POST-P0: STRICT TEACHER INPUT READY"
Write-Host "Teacher input: $($result.teacher_input)"
Write-Host "Next stage:    pinned static teacher benchmark (ExAvatar first)"
Write-Host "Human visual acceptance remains REQUIRED"
Write-Host "Photoreal acceptance: FALSE"
Write-Host "Production activation: FALSE"
