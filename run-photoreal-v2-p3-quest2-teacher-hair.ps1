param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$CandidateWorkspace,
    [Parameter(Mandatory = $true)][string]$EyeOutputRoot,
    [string]$HairEnvelope = "",
    [string]$OutputRoot = "",
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
    throw "Quest2 teacher-hair stage requires an exact clean BodyRig checkout."
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
$EyeOutputRoot = Need-Directory -Path $EyeOutputRoot -Label "Quest2 eye output root"
$teacherConfigPath = Need-File -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-config.json") -Label "ExAvatar teacher config"
$candidateReceipt = Need-File -Path (Join-Path $CandidateWorkspace "p3-quest2-student-candidate-receipt.json") -Label "Quest2 candidate receipt"
$eyeReceipt = Need-File -Path (Join-Path $EyeOutputRoot "p3-quest2-eye-student-receipt.json") -Label "Quest2 eye receipt"
$toolPath = Need-File -Path (Join-Path $repoRoot "tools\photoreal_p3_exavatar_quest2_hair_envelope.py") -Label "Quest2 hair envelope generator"

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

if ([string]::IsNullOrWhiteSpace($HairEnvelope)) {
    $HairEnvelope = Join-Path $CandidateWorkspace "p3-quest2-teacher-hair-envelope.json"
} else {
    $HairEnvelope = [System.IO.Path]::GetFullPath($HairEnvelope)
}
if (Test-Path -LiteralPath $HairEnvelope) {
    throw "Quest2 teacher hair envelope already exists: $HairEnvelope"
}
$envelopeParent = Split-Path -Parent $HairEnvelope
if ([string]::IsNullOrWhiteSpace($envelopeParent)) {
    throw "Quest2 teacher hair envelope parent is invalid."
}
if (-not (Test-Path -LiteralPath $envelopeParent -PathType Container)) {
    New-Item -ItemType Directory -Path $envelopeParent -Force | Out-Null
}
$envelopeParent = (Resolve-Path -LiteralPath $envelopeParent).Path

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $parent = Split-Path -Parent $EyeOutputRoot
    $leaf = Split-Path -Leaf $EyeOutputRoot
    $OutputRoot = Join-Path $parent "$leaf-hair"
} else {
    $OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
}
if (Test-Path -LiteralPath $OutputRoot) {
    throw "Quest2 teacher hair output already exists: $OutputRoot"
}

$toolWsl = Convert-ToWslPath -WindowsPath $toolPath -WslExe $wslExe -Distribution $distribution
$candidateWsl = Convert-ToWslPath -WindowsPath $CandidateWorkspace -WslExe $wslExe -Distribution $distribution
$envelopeParentWsl = Convert-ToWslPath -WindowsPath $envelopeParent -WslExe $wslExe -Distribution $distribution
$envelopeWsl = "$($envelopeParentWsl.TrimEnd('/'))/$(Split-Path -Leaf $HairEnvelope)"

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 TEACHER HAIR"
Write-Host "Revision:             $head"
Write-Host "Candidate workspace:  $CandidateWorkspace"
Write-Host "Candidate receipt:    $candidateReceipt"
Write-Host "Eye output:           $EyeOutputRoot"
Write-Host "Eye receipt:          $eyeReceipt"
Write-Host "ExAvatar workspace:   $linuxWorkspace"
Write-Host "Hair envelope:        $HairEnvelope"
Write-Host "Hair output:          $OutputRoot"
Write-Host "Teacher rerun:        NO"
Write-Host "P0/P2 rehash:         NO"
Write-Host "Physical silhouette:  REQUIRED"
Write-Host "Photoreal acceptance: FALSE"
Write-Host "Production:           FALSE"
Write-Host "============================================================"

$envArgs = @(
    "-d", $distribution,
    "--",
    "/usr/bin/env",
    "PYTHONNOUSERSITE=1",
    $linuxPython,
    $toolWsl,
    "--candidate-workspace", $candidateWsl,
    "--exavatar-workspace-root", $linuxWorkspace,
    "--output", $envelopeWsl
)
& $wslExe @envArgs
if ($LASTEXITCODE -ne 0) {
    throw "Quest2 teacher hair envelope generation failed with exit code $LASTEXITCODE."
}
$HairEnvelope = Need-File -Path $HairEnvelope -Label "Generated Quest2 teacher hair envelope"

$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot
$coreArgs = @(
    "-m", "bodyrig.photoreal_p3_quest2_hair_student_runner",
    "--eye-receipt", $eyeReceipt,
    "--eye-output-root", $EyeOutputRoot,
    "--hair-envelope", $HairEnvelope,
    "--output-root", $OutputRoot
)
& $python @coreArgs
if ($LASTEXITCODE -ne 0) {
    throw "Quest2 teacher hair core stage failed with exit code $LASTEXITCODE."
}

$outputReceipt = Need-File -Path (Join-Path $OutputRoot "p3-quest2-hair-student-receipt.json") -Label "Quest2 hair student receipt"
$result = Get-Content -LiteralPath $outputReceipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    [string]$result.format -ne "bodyrig-photoreal-p3-quest2-hair-student-receipt" -or
    $result.version -is [bool] -or
    [double]$result.version -ne 1.0 -or
    $result.teacher_derived_hair_component_complete -ne $true -or
    $result.p3_distillation_complete -ne $false -or
    $result.physical_hair_silhouette_review_required -ne $true -or
    $result.runtime_acceptance_authority -ne $false -or
    $result.photoreal_acceptance_authority -ne $false -or
    $result.production_activation -ne $false
) {
    throw "Quest2 hair student receipt crossed the expected authority boundary."
}

Write-Host ""
Write-Host "Quest2 teacher-derived hair stage complete."
Write-Host "Receipt:              $outputReceipt"
Write-Host "Remaining blockers:   $([string]::Join(', ', @($result.remaining_blockers)))"
Write-Host "Physical silhouette:  REQUIRED"
Write-Host "P3 complete:           FALSE"
Write-Host "Production:            FALSE"
exit 0
