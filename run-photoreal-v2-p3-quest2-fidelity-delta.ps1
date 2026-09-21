param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$CandidateWorkspace,
    [Parameter(Mandatory = $true)][string]$HairOutputRoot,
    [string]$Output = "",
    [string]$WindowsPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Get-ConfigArg {
    param(
        [Parameter(Mandatory = $true)][object[]]$Command,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $matches = @()
    for ($i = 0; $i -lt $Command.Count; $i++) {
        if ([string]$Command[$i] -eq $Name) { $matches += $i }
    }
    if ($matches.Count -ne 1) {
        throw "Teacher config must contain exactly one $Name."
    }
    $index = [int]$matches[0]
    if ($index + 1 -ge $Command.Count) {
        throw "Teacher config $Name has no value."
    }
    $value = ([string]$Command[$index + 1]).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Teacher config $Name is empty."
    }
    return $value
}

function Resolve-WindowsPython {
    param([string]$Requested,[string]$RepoRoot)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Need-File -Path $Requested -Label "Windows Python"
    }
    $venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $venv).Path
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Windows Python not found. Pass -WindowsPython explicitly."
    }
    return $command.Source
}

function Convert-ToWslPath {
    param(
        [Parameter(Mandatory = $true)][string]$WindowsPath,
        [Parameter(Mandatory = $true)][string]$WslExe,
        [Parameter(Mandatory = $true)][string]$Distribution
    )
    $raw = @(& $WslExe -d $Distribution -- wslpath -a -u $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) {
        throw "Could not convert Windows path to WSL path: $WindowsPath"
    }
    $value = ([string]$raw[0]).Trim()
    if (-not $value.StartsWith("/")) {
        throw "WSL path conversion returned an invalid path: $value"
    }
    return $value
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 fidelity-delta stage requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$CandidateWorkspace = Need-Directory -Path $CandidateWorkspace -Label "Quest2 candidate workspace"
$HairOutputRoot = Need-Directory -Path $HairOutputRoot -Label "Quest2 hair output root"
$teacherConfigPath = Need-File -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-config.json") -Label "ExAvatar teacher config"
$candidateReceipt = Need-File -Path (Join-Path $CandidateWorkspace "p3-quest2-student-candidate-receipt.json") -Label "Quest2 candidate receipt"
$hairReceipt = Need-File -Path (Join-Path $HairOutputRoot "p3-quest2-hair-student-receipt.json") -Label "Quest2 hair receipt"
$toolPath = Need-File -Path (Join-Path $repoRoot "tools\photoreal_p3_exavatar_quest2_fidelity_delta.py") -Label "Quest2 fidelity-delta generator"

$teacherConfig = Get-Content -LiteralPath $teacherConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    [string]$teacherConfig.format -ne "bodyrig-photoreal-teacher-config" -or
    $teacherConfig.version -is [bool] -or
    [double]$teacherConfig.version -ne 1.0 -or
    [string]$teacherConfig.adapter -ne "exavatar-benchmark" -or
    [string]$teacherConfig.upstream_commit -ne "d45268730c779fae4118f1a361cf9ff639bc4d1e"
) {
    throw "ExAvatar teacher config is not the pinned BodyRig authority."
}

$teacherCommand = @($teacherConfig.command)
$distribution = Get-ConfigArg -Command $teacherCommand -Name "--distribution"
$wslExe = Get-ConfigArg -Command $teacherCommand -Name "--wsl-exe"
$linuxPython = Get-ConfigArg -Command $teacherCommand -Name "--linux-python"
$linuxWorkspace = Get-ConfigArg -Command $teacherCommand -Name "--workspace-root"
if (-not $linuxPython.StartsWith("/") -or -not $linuxWorkspace.StartsWith("/")) {
    throw "Pinned teacher config Linux paths are invalid."
}

if ([string]::IsNullOrWhiteSpace($Output)) {
    $fidelityWorkspace = Join-Path (Split-Path -Parent $HairOutputRoot) "p3-quest2-fidelity-delta"
    if (Test-Path -LiteralPath $fidelityWorkspace) {
        throw "Quest2 fidelity workspace already exists: $fidelityWorkspace"
    }
    New-Item -ItemType Directory -Path $fidelityWorkspace | Out-Null
    $Output = Join-Path $fidelityWorkspace "p3-quest2-fidelity-delta-evidence.json"
} else {
    $Output = [System.IO.Path]::GetFullPath($Output)
}
if (Test-Path -LiteralPath $Output) {
    throw "Quest2 fidelity evidence already exists: $Output"
}
$resolvedHairRoot = [System.IO.Path]::GetFullPath($HairOutputRoot).TrimEnd('\\')
$resolvedOutput = [System.IO.Path]::GetFullPath($Output)
if ($resolvedOutput.StartsWith($resolvedHairRoot + "\\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Quest2 fidelity evidence must live outside the immutable hair output root."
}
$outputParent = Split-Path -Parent $Output
if ([string]::IsNullOrWhiteSpace($outputParent)) {
    throw "Quest2 fidelity evidence parent is invalid."
}
if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) {
    New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
}
$outputParent = (Resolve-Path -LiteralPath $outputParent).Path

$toolWsl = Convert-ToWslPath -WindowsPath $toolPath -WslExe $wslExe -Distribution $distribution
$candidateWsl = Convert-ToWslPath -WindowsPath $CandidateWorkspace -WslExe $wslExe -Distribution $distribution
$hairRootWsl = Convert-ToWslPath -WindowsPath $HairOutputRoot -WslExe $wslExe -Distribution $distribution
$outputParentWsl = Convert-ToWslPath -WindowsPath $outputParent -WslExe $wslExe -Distribution $distribution
$outputWsl = "$($outputParentWsl.TrimEnd('/'))/$(Split-Path -Leaf $Output)"

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 FIDELITY DELTA"
Write-Host "Revision:             $head"
Write-Host "Candidate workspace:  $CandidateWorkspace"
Write-Host "Candidate receipt:    $candidateReceipt"
Write-Host "Hair output:          $HairOutputRoot"
Write-Host "Hair receipt:         $hairReceipt"
Write-Host "ExAvatar workspace:   $linuxWorkspace"
Write-Host "Evidence output:      $Output"
Write-Host "Teacher retraining:   NO"
Write-Host "P0/P2 corpus rehash:  NO"
Write-Host "Measurements:         geometry + basecolor + pose residual"
Write-Host "Weighted score:       NO"
Write-Host "Physical review:      STILL REQUIRED"
Write-Host "Photoreal acceptance: FALSE"
Write-Host "Production:           FALSE"
Write-Host "============================================================"

$wslArgs = @(
    "-d", $distribution,
    "--",
    "/usr/bin/env",
    "PYTHONNOUSERSITE=1",
    $linuxPython,
    $toolWsl,
    "--candidate-workspace", $candidateWsl,
    "--exavatar-workspace-root", $linuxWorkspace,
    "--hair-output-root", $hairRootWsl,
    "--output", $outputWsl
)
& $wslExe @wslArgs
if ($LASTEXITCODE -ne 0) {
    throw "Quest2 fidelity measurement failed with exit code $LASTEXITCODE."
}
$Output = Need-File -Path $Output -Label "Generated Quest2 fidelity evidence"

$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot
$coreArgs = @(
    "-m", "bodyrig.photoreal_p3_quest2_fidelity_delta",
    "--evidence", $Output,
    "--hair-receipt", $hairReceipt,
    "--hair-output-root", $HairOutputRoot
)
& $python @coreArgs
if ($LASTEXITCODE -ne 0) {
    throw "Quest2 fidelity evidence strict readback failed with exit code $LASTEXITCODE."
}

$result = Get-Content -LiteralPath $Output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    [string]$result.format -ne "bodyrig-photoreal-p3-quest2-fidelity-delta-evidence" -or
    $result.version -is [bool] -or
    [double]$result.version -ne 1.0 -or
    $result.fidelity_delta_complete -ne $true -or
    $result.p3_distillation_complete -ne $false -or
    $result.human_runtime_visual_acceptance_required -ne $true -or
    $result.runtime_acceptance_authority -ne $false -or
    $result.photoreal_acceptance_authority -ne $false -or
    $result.production_activation -ne $false
) {
    throw "Quest2 fidelity evidence crossed the expected authority boundary."
}
$measurements = @($result.fidelity_delta_measurements)
if ($measurements.Count -ne 8) {
    throw "Quest2 fidelity evidence did not produce all eight canonical dimensions."
}

Write-Host ""
Write-Host "Quest2 fidelity-delta stage complete."
foreach ($measurement in $measurements) {
    Write-Host ("  {0}: {1} {2}" -f [string]$measurement.dimension, [string]$measurement.value, [string]$measurement.unit)
}
Write-Host "Evidence:             $Output"
Write-Host "Remaining blockers:   $([string]::Join(', ', @($result.remaining_blockers)))"
Write-Host "P3 complete:           FALSE"
Write-Host "Physical review:       STILL REQUIRED"
Write-Host "Production:            FALSE"
exit 0
