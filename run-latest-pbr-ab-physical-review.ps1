param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId,
    [string]$RigSetupReport = "",
    [ValidatePattern('^[A-Za-z0-9._/-]{1,200}$')]
    [string]$CandidateRef = "candidate/skin-pbr-v3-linear-light-20260909",
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$UnityExe = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig latest PBR A/B launcher is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical Git revision: $Value" }
    return $normalized
}
function Test-CommitExists {
    param([Parameter(Mandatory = $true)][string]$Revision)
    $spec = $Revision + "^{commit}"
    & git -C $repoRoot cat-file -e $spec 2>$null
    return ($LASTEXITCODE -eq 0)
}
function Test-IsAncestor {
    param([Parameter(Mandatory = $true)][string]$Ancestor,[Parameter(Mandatory = $true)][string]$Descendant)
    & git -C $repoRoot merge-base --is-ancestor $Ancestor $Descendant 2>$null
    return ($LASTEXITCODE -eq 0)
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$runner = Need-File -Path (Join-Path $repoRoot "run-pbr-ab-physical-review.ps1") -Label "PBR A/B retained-reconstruction runner"
$policyPath = Need-File -Path (Join-Path $repoRoot "contracts\pbr-ab-source-policy-v1.json") -Label "PBR A/B retained-source policy"
try { $policy = Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "PBR A/B retained-source policy is invalid JSON: $policyPath" }
$policyFields = @($policy.PSObject.Properties.Name)
if ($policyFields.Count -ne 3 -or ($policyFields -notcontains "format") -or ($policyFields -notcontains "version") -or ($policyFields -notcontains "safe_source_floor_revision") -or
    [string]$policy.format -ne "bodyrig-pbr-ab-source-policy" -or [int]$policy.version -ne 1) {
    throw "PBR A/B retained-source policy fields/format/version do not match v1."
}
$safeSourceFloorRevision = Need-Revision -Value ([string]$policy.safe_source_floor_revision) -Label "Safe-source floor revision"
if (-not (Test-CommitExists -Revision $safeSourceFloorRevision)) {
    throw "BodyRig checkout cannot resolve safe-source floor revision $safeSourceFloorRevision. Use a full/current checkout before selecting retained PBR A/B evidence."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidatePython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidatePython -PathType Leaf) { $BodyRigPython = (Resolve-Path -LiteralPath $candidatePython).Path }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"

$artifactBase = [string]$env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($artifactBase)) { $artifactBase = [IO.Path]::GetTempPath() }
$convergenceRoot = Join-Path $artifactBase "BodyRig\fidelity-convergence"
if (-not (Test-Path -LiteralPath $convergenceRoot -PathType Container)) {
    throw "No fidelity-convergence root exists: $convergenceRoot"
}

$candidates = @(Get-ChildItem -LiteralPath $convergenceRoot -Directory -ErrorAction Stop |
    Where-Object { $_.Name.StartsWith("$BodyId-",[StringComparison]::OrdinalIgnoreCase) } |
    Sort-Object LastWriteTimeUtc -Descending)
if ($candidates.Count -eq 0) { throw "No fidelity-convergence work root found for BodyId '$BodyId'." }

$previousPythonPath = [string]$env:PYTHONPATH
$selected = ""
$selectedCheckpointRevision = ""
$rejections = New-Object System.Collections.Generic.List[string]
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$previousPythonPath" })
    foreach ($candidate in $candidates) {
        $checkpointDir = Join-Path $candidate.FullName "checkpoints"
        if (-not (Test-Path -LiteralPath $checkpointDir -PathType Container)) {
            $rejections.Add("$($candidate.Name): no checkpoints directory")
            continue
        }
        $checkpoints = @(Get-ChildItem -LiteralPath $checkpointDir -Filter "checkpoint-*.json" -File | Sort-Object Name -Descending)
        if ($checkpoints.Count -eq 0) {
            $rejections.Add("$($candidate.Name): no checkpoint files")
            continue
        }
        $latest = $checkpoints[0].FullName
        $verifyRaw = @(& $BodyRigPython -m bodyrig.fidelity_checkpoint_verify_cli --checkpoint $latest --work-root $candidate.FullName 2>&1)
        if ($LASTEXITCODE -ne 0) {
            $detail = ($verifyRaw -join " ")
            if ($detail.Length -gt 500) { $detail = $detail.Substring(0,500) }
            $rejections.Add("$($candidate.Name): checkpoint rejected: $detail")
            continue
        }
        try { $checkpoint = Get-Content -LiteralPath $latest -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60 }
        catch {
            $rejections.Add("$($candidate.Name): latest checkpoint unreadable")
            continue
        }
        if ([string]$checkpoint.body_alias -ne $BodyId) {
            $rejections.Add("$($candidate.Name): checkpoint body alias mismatch")
            continue
        }
        try { $checkpointRevision = Need-Revision -Value ([string]$checkpoint.bodyrig_revision) -Label "checkpoint bodyrig_revision" }
        catch {
            $rejections.Add("$($candidate.Name): checkpoint BodyRig revision is invalid")
            continue
        }
        if (-not (Test-CommitExists -Revision $checkpointRevision)) {
            $rejections.Add("$($candidate.Name): checkpoint BodyRig revision $checkpointRevision cannot be resolved in this checkout")
            continue
        }
        if (-not (Test-IsAncestor -Ancestor $safeSourceFloorRevision -Descendant $checkpointRevision)) {
            $rejections.Add("$($candidate.Name): checkpoint revision $checkpointRevision predates or is outside safe-source floor $safeSourceFloorRevision")
            continue
        }
        $selected = $candidate.FullName
        $selectedCheckpointRevision = $checkpointRevision
        break
    }
} finally {
    if ([string]::IsNullOrEmpty($previousPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}

if ([string]::IsNullOrWhiteSpace($selected)) {
    $detail = if ($rejections.Count -gt 0) { $rejections -join [Environment]::NewLine } else { "no usable candidates" }
    throw "No safe verified retained convergence checkpoint is usable for '$BodyId'. Historical/pre-projection-safety evidence remains historical and cannot be rebound.`n$detail"
}

Write-Host "BodyRig latest retained PBR A/B"
Write-Host "BodyId:          $BodyId"
Write-Host "Convergence:     $selected"
Write-Host "Checkpoint rev:  $selectedCheckpointRevision"
Write-Host "Safe-source floor:$safeSourceFloorRevision"
Write-Host "Candidate:       $CandidateRef"
Write-Host "Selection:       newest byte-verified convergence whose BodyRig revision descends from the safe-source floor"
Write-Host ""

$args = @{
    ConvergenceWorkRoot = $selected
    CandidateRef = $CandidateRef
    BodyRigPython = $BodyRigPython
}
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $args.RigSetupReport = $RigSetupReport }
if (-not [string]::IsNullOrWhiteSpace($OutputDir)) { $args.OutputDir = $OutputDir }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $args.UnityExe = $UnityExe }

& $runner @args
if ($LASTEXITCODE -ne 0) { throw "BodyRig PBR A/B runner failed with exit code $LASTEXITCODE." }
exit 0
