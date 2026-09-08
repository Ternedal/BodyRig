param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId,
    [string]$RigSetupReport = "",
    [ValidatePattern('^[A-Za-z0-9._/-]{1,200}$')]
    [string]$CandidateRef = "candidate/skin-pbr-v2-current-main-20260908",
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

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$runner = Need-File -Path (Join-Path $repoRoot "run-pbr-ab-physical-review.ps1") -Label "PBR A/B retained-reconstruction runner"

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
        $selected = $candidate.FullName
        break
    }
} finally {
    if ([string]::IsNullOrEmpty($previousPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}

if ([string]::IsNullOrWhiteSpace($selected)) {
    $detail = if ($rejections.Count -gt 0) { $rejections -join [Environment]::NewLine } else { "no usable candidates" }
    throw "No verified retained convergence checkpoint is usable for '$BodyId'.`n$detail"
}

Write-Host "BodyRig latest retained PBR A/B"
Write-Host "BodyId:       $BodyId"
Write-Host "Convergence:  $selected"
Write-Host "Candidate:    $CandidateRef"
Write-Host "Selection:    newest convergence root whose latest checkpoint passes strict byte verification"
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
