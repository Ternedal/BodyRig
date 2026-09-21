param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$DistillationPlan,
    [string]$P2Root = "",
    [string]$CandidateWorkspace = "",
    [string]$CanonicalUvTemplate = "",
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
        if ([string]$Command[$i] -eq $Name) {
            $matches += $i
        }
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

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 refined candidate stage requires an exact clean BodyRig checkout."
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
$DistillationPlan = Need-File -Path $DistillationPlan -Label "P3 distillation plan"
$teacherConfigPath = Need-File -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-config.json") -Label "ExAvatar teacher config"
$teacherOutputRoot = Need-Directory -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-output\output") -Label "Accepted ExAvatar teacher output root"

if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"
$identityRoot = Need-Directory -Path (Join-Path $P2Root "animation-input\exavatar-identity") -Label "Accepted ExAvatar identity export root"

$p3Root = Split-Path -Parent $DistillationPlan
if ([string]::IsNullOrWhiteSpace($CandidateWorkspace)) {
    $CandidateWorkspace = Join-Path $p3Root "quest2-refined-student-candidate"
} else {
    $CandidateWorkspace = [System.IO.Path]::GetFullPath($CandidateWorkspace)
}
if (Test-Path -LiteralPath $CandidateWorkspace) {
    throw "Quest2 refined candidate workspace already exists: $CandidateWorkspace"
}
$candidateParent = Split-Path -Parent $CandidateWorkspace
if ([string]::IsNullOrWhiteSpace($candidateParent)) {
    throw "Quest2 candidate parent path is invalid."
}
if (-not (Test-Path -LiteralPath $candidateParent -PathType Container)) {
    New-Item -ItemType Directory -Path $candidateParent -Force | Out-Null
}
$candidateParent = (Resolve-Path -LiteralPath $candidateParent).Path

$configPath = Join-Path $candidateParent "quest2-refined-student-candidate-config.json"
if (Test-Path -LiteralPath $configPath) {
    throw "Quest2 refined candidate config already exists: $configPath"
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
if (
    [string]::IsNullOrWhiteSpace($distribution) -or
    [string]::IsNullOrWhiteSpace($wslExe) -or
    -not $linuxPython.StartsWith("/") -or
    -not $linuxWorkspace.StartsWith("/")
) {
    throw "Pinned teacher config runtime fields are invalid."
}

$adapter = Need-File -Path (Join-Path $repoRoot "tools\photoreal_p3_exavatar_quest2_student_candidate.py") -Label "Quest2 candidate adapter"
$adapterSha = Sha256 $adapter

$repoWsl = Convert-ToWslPath -WindowsPath $repoRoot -WslExe $wslExe -Distribution $distribution
$adapterWsl = Convert-ToWslPath -WindowsPath $adapter -WslExe $wslExe -Distribution $distribution
$planWsl = Convert-ToWslPath -WindowsPath $DistillationPlan -WslExe $wslExe -Distribution $distribution
$teacherOutputWsl = Convert-ToWslPath -WindowsPath $teacherOutputRoot -WslExe $wslExe -Distribution $distribution
$identityWsl = Convert-ToWslPath -WindowsPath $identityRoot -WslExe $wslExe -Distribution $distribution
$candidateWsl = Convert-ToWslPath -WindowsPath $CandidateWorkspace -WslExe $wslExe -Distribution $distribution
$configWsl = Convert-ToWslPath -WindowsPath $configPath -WslExe $wslExe -Distribution $distribution

if ([string]::IsNullOrWhiteSpace($CanonicalUvTemplate)) {
    $homeRaw = @(
        & $wslExe -d $distribution -- /usr/bin/python3 -c "import pathlib; print(pathlib.Path.home().as_posix())" 2>&1
    )
    if (
        $LASTEXITCODE -ne 0 -or
        $homeRaw.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$homeRaw[0])
    ) {
        throw "Could not resolve WSL home for canonical SMPL-X UV template."
    }
    $linuxHome = ([string]$homeRaw[0]).Trim()
    $canonicalUvWsl = "$($linuxHome.TrimEnd('/'))/.local/share/bodyrig/sith/data/smplx_uv.obj"
} elseif ($CanonicalUvTemplate.StartsWith("/")) {
    $canonicalUvWsl = $CanonicalUvTemplate
} else {
    $CanonicalUvTemplate = Need-File -Path $CanonicalUvTemplate -Label "Canonical SMPL-X UV template"
    $canonicalUvWsl = Convert-ToWslPath -WindowsPath $CanonicalUvTemplate -WslExe $wslExe -Distribution $distribution
}
& $wslExe -d $distribution -- /usr/bin/test -f $canonicalUvWsl
if ($LASTEXITCODE -ne 0) {
    throw "Canonical SMPL-X UV template is missing in WSL: $canonicalUvWsl"
}

& $wslExe -d $distribution -- /usr/bin/test -x $linuxPython
if ($LASTEXITCODE -ne 0) {
    throw "Pinned ExAvatar Linux Python is missing/not executable: $linuxPython"
}
& $wslExe -d $distribution -- /usr/bin/test -d $linuxWorkspace
if ($LASTEXITCODE -ne 0) {
    throw "Pinned ExAvatar workspace is missing in WSL: $linuxWorkspace"
}

$runtimePreflightCode = @'
import importlib
import json
import torch

required = ("numpy", "PIL", "pytorch3d", "nvdiffrast")
for name in required:
    importlib.import_module(name)

import bodyrig.photoreal_p3_quest2_student_candidate_runner

if not torch.cuda.is_available():
    raise SystemExit("CUDA unavailable in pinned ExAvatar Python")

print(json.dumps({
    "cuda_available": True,
    "cuda_version": torch.version.cuda,
    "device_name": torch.cuda.get_device_name(0),
    "required_modules": list(required),
}, sort_keys=True, separators=(",", ":")))
'@
$runtimePreflightArgs = @(
    "-d", $distribution,
    "--",
    "/usr/bin/env",
    "PYTHONPATH=$repoWsl",
    "PYTHONNOUSERSITE=1",
    $linuxPython,
    "-c", $runtimePreflightCode
)
$runtimePreflightRaw = @(& $wslExe @runtimePreflightArgs 2>&1)
if ($LASTEXITCODE -ne 0 -or $runtimePreflightRaw.Count -lt 1) {
    throw "Pinned ExAvatar Quest2 candidate runtime preflight failed: $([string]::Join(' | ', $runtimePreflightRaw))"
}
try {
    $runtimePreflight = ([string]$runtimePreflightRaw[-1]) | ConvertFrom-Json
} catch {
    throw "Pinned ExAvatar Quest2 candidate runtime preflight returned invalid JSON."
}
if ($runtimePreflight.cuda_available -ne $true) {
    throw "Pinned ExAvatar Quest2 candidate runtime did not prove CUDA."
}

$dimensions = @(
    "identity_likeness",
    "face_detail",
    "eyes",
    "hair_silhouette_and_appearance",
    "skin_material_response",
    "hands_and_extremities",
    "motion_identity_preservation",
    "temporal_stability"
)
$config = [ordered]@{
    format = "bodyrig-photoreal-p3-device-distillation-config"
    version = 1
    adapter = "bodyrig-exavatar-quest2-student-candidate-v1"
    revision = $adapterSha
    entrypoint = $adapterWsl
    student_representation = "skinned-mesh-pbr"
    student_components = @(
        "specialized-eye-component",
        "teacher-derived-hair-component"
    )
    command = @(
        $linuxPython,
        $adapterWsl,
        "--exavatar-workspace-root",
        $linuxWorkspace,
        "--canonical-uv-template",
        $canonicalUvWsl
    )
    timeout_seconds = 86400
    supported_target_models = @("quest-2")
    supported_fidelity_delta_dimensions = $dimensions
    reports_teacher_student_delta = $true
    gaussian_splat_target_support = $false
    consumes_staged_teacher_only = $true
}
$config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $configPath -Encoding UTF8

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - REFINED EXAVATAR QUEST2 CANDIDATE"
Write-Host "Revision:              $head"
Write-Host "P3 plan:               $DistillationPlan"
Write-Host "Teacher output:        $teacherOutputRoot"
Write-Host "Identity export:       $identityRoot"
Write-Host "ExAvatar workspace:    $linuxWorkspace"
Write-Host "Canonical UV:          $canonicalUvWsl"
Write-Host "Adapter SHA:           $adapterSha"
Write-Host "Candidate workspace:   $CandidateWorkspace"
Write-Host "Execution runtime:     WSL / pinned ExAvatar Python"
Write-Host "CUDA device:           $($runtimePreflight.device_name)"
Write-Host "Teacher authority:     REFINED ExAvatar geometry + RGB"
Write-Host "P3 complete:           FALSE"
Write-Host "Physical review:       REQUIRED LATER"
Write-Host "Production:            FALSE"
Write-Host "============================================================"

$wslArgs = @(
    "-d", $distribution,
    "--",
    "/usr/bin/env",
    "PYTHONPATH=$repoWsl",
    "PYTHONNOUSERSITE=1",
    $linuxPython,
    "-m", "bodyrig.photoreal_p3_quest2_student_candidate_runner",
    "--config", $configWsl,
    "--plan", $planWsl,
    "--teacher-output-root", $teacherOutputWsl,
    "--identity-root", $identityWsl,
    "--workspace", $candidateWsl
)
& $wslExe @wslArgs
if ($LASTEXITCODE -ne 0) {
    throw "Quest2 refined candidate failed with exit code $LASTEXITCODE."
}

$candidateReceipt = Need-File -Path (Join-Path $CandidateWorkspace "p3-quest2-student-candidate-receipt.json") -Label "Quest2 candidate receipt"
$candidateManifest = Need-File -Path (Join-Path $CandidateWorkspace "output\quest2-student-candidate.json") -Label "Quest2 candidate manifest"
$avatar = Need-File -Path (Join-Path $CandidateWorkspace "output\student\avatar.vrm") -Label "Quest2 candidate VRM"
$basecolor = Need-File -Path (Join-Path $CandidateWorkspace "output\student\basecolor.png") -Label "Quest2 candidate basecolor"

$manifest = Get-Content -LiteralPath $candidateManifest -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$receipt = Get-Content -LiteralPath $candidateReceipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    [string]$manifest.format -ne "bodyrig-photoreal-p3-exavatar-quest2-student-candidate" -or
    ([string]$manifest.adapter_revision).ToLowerInvariant() -ne $adapterSha -or
    $manifest.student_candidate_complete -ne $true -or
    $manifest.p3_distillation_complete -ne $false -or
    $manifest.runtime_acceptance_authority -ne $false -or
    $manifest.photoreal_acceptance_authority -ne $false -or
    $manifest.production_activation -ne $false
) {
    throw "Quest2 refined candidate manifest crossed or lost its expected authority boundary."
}
if (
    $receipt.student_candidate_complete -ne $true -or
    $receipt.p3_distillation_complete -ne $false -or
    $receipt.runtime_acceptance_authority -ne $false -or
    $receipt.photoreal_acceptance_authority -ne $false -or
    $receipt.production_activation -ne $false
) {
    throw "Quest2 refined candidate receipt crossed its expected authority boundary."
}

Write-Host ""
Write-Host "Quest2 refined candidate: COMPLETE"
Write-Host "VRM:                    $avatar"
Write-Host "Basecolor:              $basecolor"
Write-Host "Manifest:               $candidateManifest"
Write-Host "Receipt:                $candidateReceipt"
Write-Host "Adapter config:         $configPath"
Write-Host "P3 complete:            FALSE"
Write-Host "Physical review:        REQUIRED LATER"
Write-Host "Production:             FALSE"
exit 0
