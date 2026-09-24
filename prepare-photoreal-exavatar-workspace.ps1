param(
    [Parameter(Mandatory = $true)][string]$MaterializationWorkspace,
    [Parameter(Mandatory = $true)][string]$StrictPreflightPath,
    [Parameter(Mandatory = $true)][string]$AssetRoot,
    [Parameter(Mandatory = $true)][string]$ReferenceModelRoot,
    [Parameter(Mandatory = $true)][ValidateSet("female", "male", "neutral")][string]$SmplxGender,
    [Parameter(Mandatory = $true)][string]$LinuxWorkspaceRoot,
    [string]$LinuxDependencyRoot = "/opt/bodyrig-exavatar/deps",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$WslExe = "wsl.exe",
    [switch]$RebuildWorkspace
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$materializationRoot = (Resolve-Path $MaterializationWorkspace).Path
$dataset = Join-Path $materializationRoot "dataset"
$receipt = Join-Path $dataset "materialization-receipt.json"
$preflight = (Resolve-Path $StrictPreflightPath).Path
$assets = (Resolve-Path $AssetRoot).Path
$reference = (Resolve-Path $ReferenceModelRoot).Path

if (-not (Test-Path -LiteralPath $dataset -PathType Container)) {
    throw "Materialized ExAvatar dataset not found: $dataset"
}
if (-not (Test-Path -LiteralPath $receipt -PathType Leaf)) {
    throw "Materialization receipt not found: $receipt"
}
if ([string]::IsNullOrWhiteSpace($LinuxWorkspaceRoot) -or -not $LinuxWorkspaceRoot.StartsWith('/')) {
    throw "LinuxWorkspaceRoot must be an absolute Linux path."
}
if ($LinuxWorkspaceRoot -eq "/") { throw "LinuxWorkspaceRoot may not be '/'." }
if ([string]::IsNullOrWhiteSpace($LinuxDependencyRoot) -or -not $LinuxDependencyRoot.StartsWith('/')) {
    throw "LinuxDependencyRoot must be an absolute Linux path."
}

$py = if (Test-Path (Join-Path $repo ".venv\Scripts\python.exe")) {
    (Resolve-Path (Join-Path $repo ".venv\Scripts\python.exe")).Path
} else {
    (Get-Command python).Source
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL EXAVATAR WORKSPACE"
Write-Host "Materialization:    $materializationRoot"
Write-Host "SMPL-X prior:       $SmplxGender"
Write-Host "WSL distribution:   $Distribution"
Write-Host "Dependency root:    $LinuxDependencyRoot"
Write-Host "Workspace root:     $LinuxWorkspaceRoot"
Write-Host "Held-out eval:      NOT DISCLOSED"
Write-Host "Original video:     NOT COPIED"
Write-Host "Production:         FALSE"
Write-Host "============================================================"

& $WslExe -d $Distribution -- /usr/bin/test -f "$LinuxWorkspaceRoot/workspace-receipt.json" 2>$null
$reuseExisting = ($LASTEXITCODE -eq 0)

$code = @'
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo))
from bodyrig.photoreal_exavatar_workspace_wsl import (
    prepare_exavatar_workspace_wsl,
    remove_exavatar_workspace_wsl,
    validate_exavatar_workspace_wsl,
)

reuse = sys.argv[13].lower() == "true"
rebuild = sys.argv[14].lower() == "true"
if rebuild and reuse:
    remove_exavatar_workspace_wsl(
        materialization_receipt_path=sys.argv[3],
        strict_preflight_path=sys.argv[4],
        linux_workspace_root=sys.argv[8],
        smplx_gender=sys.argv[9],
        distribution=sys.argv[10],
        wsl_exe=sys.argv[12],
    )
    reuse = False
if reuse:
    result = validate_exavatar_workspace_wsl(
        materialization_receipt_path=sys.argv[3],
        strict_preflight_path=sys.argv[4],
        linux_workspace_root=sys.argv[8],
        smplx_gender=sys.argv[9],
        distribution=sys.argv[10],
        wsl_exe=sys.argv[12],
    )
else:
    result = prepare_exavatar_workspace_wsl(
        materialized_dataset_dir=sys.argv[2],
        materialization_receipt_path=sys.argv[3],
        strict_preflight_path=sys.argv[4],
        linux_dependency_root=sys.argv[5],
        asset_root=sys.argv[6],
        reference_model_root=sys.argv[7],
        linux_workspace_root=sys.argv[8],
        smplx_gender=sys.argv[9],
        distribution=sys.argv[10],
        linux_python=sys.argv[11],
        wsl_exe=sys.argv[12],
    )
print(json.dumps({
    "format": result["format"],
    "version": result["version"],
    "subject_id": result["subject_id"],
    "smplx_gender": result["smplx_gender"],
    "dataset": result["dataset"],
    "frame_count": result["frame_count"],
    "workspace_sha256": result["workspace_sha256"],
    "held_out_evaluation_disclosed": result["held_out_evaluation_disclosed"],
    "production_activation": result["production_activation"],
}, sort_keys=True, separators=(",", ":")))
'@

& $py -c $code `
    $repo `
    $dataset `
    $receipt `
    $preflight `
    $LinuxDependencyRoot `
    $assets `
    $reference `
    $LinuxWorkspaceRoot `
    $SmplxGender `
    $Distribution `
    $LinuxPython `
    $WslExe `
    $reuseExisting.ToString().ToLowerInvariant() `
    $RebuildWorkspace.IsPresent.ToString().ToLowerInvariant()

if ($LASTEXITCODE -ne 0) {
    throw "BodyRig Photoreal ExAvatar workspace preparation failed with code $LASTEXITCODE"
}

$hand4wholeStage = Join-Path $repo "stage-photoreal-exavatar-hand4whole-assets.ps1"
if (-not (Test-Path -LiteralPath $hand4wholeStage -PathType Leaf)) {
    throw "Hand4Whole asset staging operator not found: $hand4wholeStage"
}
& $hand4wholeStage `
    -LinuxWorkspaceRoot $LinuxWorkspaceRoot `
    -Distribution $Distribution `
    -LinuxPython $LinuxPython `
    -WslExe $WslExe

Write-Host ""
Write-Host "BodyRig ExAvatar workspace: READY FOR PREPROCESSING"
Write-Host "Hand4Whole assets: VERIFIED + STAGED"
Write-Host "Photoreal acceptance: FALSE"
Write-Host "Production: FALSE"
