param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [string]$P3Root = "",
    [string]$WindowsPython = "",
    [int]$TimeoutSeconds = 86400
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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

function Get-ConfigArg {
    param(
        [Parameter(Mandatory = $true)][object[]]$Command,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $matches = @()
    for ($i = 0; $i -lt $Command.Count; $i++) {
        if ([string]$Command[$i] -eq $Name) { $matches += $i }
    }
    if ($matches.Count -ne 1) { throw "Teacher config must contain exactly one $Name." }
    $index = [int]$matches[0]
    if ($index + 1 -ge $Command.Count) { throw "Teacher config $Name has no value." }
    $value = ([string]$Command[$index + 1]).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { throw "Teacher config $Name is empty." }
    return $value
}

function Resolve-WindowsPython {
    param([string]$Requested)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Need-File -Path $Requested -Label "Windows Python"
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "Windows Python not found. Pass -WindowsPython explicitly." }
    return $command.Source
}

if ($TimeoutSeconds -lt 1 -or $TimeoutSeconds -gt 604800) {
    throw "TimeoutSeconds must be in 1..604800."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1 -or ([string]$branch[0]).Trim() -ne "main") {
    throw "P3 ExAvatar Quest2 adapter config requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P3 ExAvatar Quest2 adapter config requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$teacherConfigPath = Need-File -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-config.json") -Label "ExAvatar teacher config"
$adapterPath = Need-File -Path (Join-Path $repoRoot "tools\photoreal_p3_exavatar_quest2_pbr_adapter.py") -Label "ExAvatar Quest2 PBR adapter"

if ([string]::IsNullOrWhiteSpace($P3Root)) {
    $P3Root = Join-Path $TeacherWorkRoot "p3-device-distillation"
}
$P3Root = Need-Directory -Path $P3Root -Label "P3 work root"
$outputPath = Join-Path $P3Root "p3-exavatar-quest2-pbr-config.json"
if (Test-Path -LiteralPath $outputPath) {
    throw "P3 ExAvatar Quest2 PBR config already exists: $outputPath"
}

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
$runtimePreflight = Get-ConfigArg -Command $teacherCommand -Name "--runtime-preflight"
if (-not $linuxPython.StartsWith("/") -or -not $linuxWorkspace.StartsWith("/") -or -not $runtimePreflight.StartsWith("/")) {
    throw "Pinned teacher config Linux paths are invalid."
}

$python = Resolve-WindowsPython -Requested $WindowsPython
$revision = (Get-FileHash -LiteralPath $adapterPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($revision.Length -ne 64) { throw "Could not derive adapter SHA-256 revision." }

$config = [ordered]@{
    format = "bodyrig-photoreal-p3-device-distillation-config"
    version = 1
    adapter = "bodyrig-exavatar-quest2-pbr-v1"
    revision = $revision
    entrypoint = $adapterPath
    student_representation = "skinned-mesh-pbr"
    student_components = @(
        "specialized-eye-component",
        "teacher-derived-hair-component"
    )
    command = @(
        $python,
        $adapterPath,
        "--distribution", $distribution,
        "--wsl-exe", $wslExe,
        "--linux-python", $linuxPython,
        "--workspace-root", $linuxWorkspace,
        "--runtime-preflight", $runtimePreflight
    )
    timeout_seconds = $TimeoutSeconds
    supported_target_models = @("quest-2")
    supported_fidelity_delta_dimensions = @(
        "identity_likeness",
        "face_detail",
        "eyes",
        "hair_silhouette_and_appearance",
        "skin_material_response",
        "hands_and_extremities",
        "motion_identity_preservation",
        "temporal_stability"
    )
    reports_teacher_student_delta = $true
    gaussian_splat_target_support = $false
    consumes_staged_teacher_only = $true
}

$config | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $outputPath -Encoding UTF8

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - EXAVATAR QUEST2 PBR ADAPTER CONFIG"
Write-Host "Adapter:              $($config.adapter)"
Write-Host "Revision:             $revision"
Write-Host "Target:               quest-2"
Write-Host "Representation:       skinned-mesh-pbr"
Write-Host "Components:           specialized eyes + teacher-derived hair"
Write-Host "ExAvatar workspace:   $linuxWorkspace"
Write-Host "Linux Python:         $linuxPython"
Write-Host "Staged teacher only:  TRUE"
Write-Host "Physical review:      REQUIRED AFTER DISTILLATION"
Write-Host "Photoreal acceptance: FALSE"
Write-Host "Production:           FALSE"
Write-Host "============================================================"
Write-Host "Config: $outputPath"
exit 0
