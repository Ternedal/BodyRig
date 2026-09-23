param(
    [Parameter(Mandatory = $true)][string]$P0Root,
    [string]$TeacherWorkRoot = "",
    [string]$AppearanceReviewRoot = "",
    [string]$AssetRoot = "",
    [string]$ReferenceModelRoot = "",
    [ValidateSet("", "female", "male", "neutral")][string]$SmplxGender = "",
    [ValidateSet("", "colmap", "virtual")][string]$CameraMode = "",
    [switch]$SetupPublicCode,
    [switch]$SetupRuntime,
    [string]$P2MotionConfig = "",
    [string]$P2ReviewSelectionInput = "",
    [string]$SingleMotionDriverSourceRef = "",
    [string]$ReviewedBy = "",
    [string]$ReviewNotes = "",
    [string]$P3TargetProfile = "",
    [string]$P3MachineProbe = "",
    [string]$PersonLibrary = "",
    [string]$PersonId = "",
    [string]$AssemblyReceipt = "",
    [string]$BodyReleaseStatus = "",
    [string]$PhotorealPersonBindingOutput = "",
    [string]$WindowsPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-WindowsPython {
    param([string]$Requested, [string]$RepoRoot)
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

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$P0Root = Need-Directory -Path $P0Root -Label "Photoreal P0 root"
$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

$argsList = @(
    "-m", "bodyrig.photoreal_v2_operator_status_cli",
    "--p0-root", $P0Root,
    "--operator-root", $repoRoot
)

if (-not [string]::IsNullOrWhiteSpace($TeacherWorkRoot)) {
    $argsList += @("--teacher-work-root", [IO.Path]::GetFullPath($TeacherWorkRoot))
}
if (-not [string]::IsNullOrWhiteSpace($AppearanceReviewRoot)) {
    $argsList += @("--appearance-review-root", [IO.Path]::GetFullPath($AppearanceReviewRoot))
}
if (-not [string]::IsNullOrWhiteSpace($AssetRoot)) {
    $argsList += @("--asset-root", [IO.Path]::GetFullPath($AssetRoot))
}
if (-not [string]::IsNullOrWhiteSpace($ReferenceModelRoot)) {
    $argsList += @("--reference-model-root", [IO.Path]::GetFullPath($ReferenceModelRoot))
}
if (-not [string]::IsNullOrWhiteSpace($SmplxGender)) {
    $argsList += @("--smplx-gender", $SmplxGender)
}
if (-not [string]::IsNullOrWhiteSpace($CameraMode)) {
    $argsList += @("--camera-mode", $CameraMode)
}
if ($SetupPublicCode) {
    $argsList += "--setup-public-code"
}
if ($SetupRuntime) {
    $argsList += "--setup-runtime"
}
if (-not [string]::IsNullOrWhiteSpace($P2MotionConfig)) {
    $argsList += @("--p2-motion-config", [IO.Path]::GetFullPath($P2MotionConfig))
}
if (-not [string]::IsNullOrWhiteSpace($P2ReviewSelectionInput)) {
    $argsList += @("--p2-review-selection-input", [IO.Path]::GetFullPath($P2ReviewSelectionInput))
}
if (-not [string]::IsNullOrWhiteSpace($SingleMotionDriverSourceRef)) {
    $argsList += @("--single-motion-driver-source-ref", $SingleMotionDriverSourceRef)
}
if (-not [string]::IsNullOrWhiteSpace($ReviewedBy)) {
    $argsList += @("--reviewed-by", $ReviewedBy)
}
if (-not [string]::IsNullOrWhiteSpace($ReviewNotes)) {
    $argsList += @("--review-notes", $ReviewNotes)
}
if (-not [string]::IsNullOrWhiteSpace($P3TargetProfile)) {
    $argsList += @("--p3-target-profile", [IO.Path]::GetFullPath($P3TargetProfile))
}
if (-not [string]::IsNullOrWhiteSpace($P3MachineProbe)) {
    $argsList += @("--p3-machine-probe", [IO.Path]::GetFullPath($P3MachineProbe))
}
if (-not [string]::IsNullOrWhiteSpace($PersonLibrary)) {
    $argsList += @("--person-library", [IO.Path]::GetFullPath($PersonLibrary))
}
if (-not [string]::IsNullOrWhiteSpace($PersonId)) {
    $argsList += @("--person-id", $PersonId)
}
if (-not [string]::IsNullOrWhiteSpace($AssemblyReceipt)) {
    $argsList += @("--assembly-receipt", [IO.Path]::GetFullPath($AssemblyReceipt))
}
if (-not [string]::IsNullOrWhiteSpace($BodyReleaseStatus)) {
    $argsList += @("--body-release-status", [IO.Path]::GetFullPath($BodyReleaseStatus))
}
if (-not [string]::IsNullOrWhiteSpace($PhotorealPersonBindingOutput)) {
    $argsList += @("--photoreal-person-binding-output", [IO.Path]::GetFullPath($PhotorealPersonBindingOutput))
}

$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot
    & $python @argsList
    exit $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}
