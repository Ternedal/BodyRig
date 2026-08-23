param(
    [Parameter(Mandatory = $true)]
    [string[]]$Source,

    [Parameter(Mandatory = $true)]
    [string]$ExternalPython,

    [Parameter(Mandatory = $true)]
    [string]$FourDHumansRepo,

    [string]$TrackId = "",
    [string]$BodyId = "bodyrig-acceptance",
    [string]$Name = "BodyRig Acceptance",
    [string]$BodyRigPython = "",
    [string]$OutputDir = "",
    [switch]$AllowCpu,
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not bind acceptance to BodyRig Git HEAD."
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect BodyRig Git status."
}
if (-not $AllowDirty -and $dirty.Count -gt 0) {
    throw "BodyRig checkout is dirty. Commit/stash changes or rerun explicitly with -AllowDirty."
}

if ($Source.Count -lt 1 -or $Source.Count -gt 10) {
    throw "BodyRig V1 accepts 1..10 source clips."
}
$resolvedSources = @()
foreach ($item in $Source) {
    if (-not (Test-Path -LiteralPath $item -PathType Leaf)) {
        throw "Source file not found: $item"
    }
    $resolvedSources += (Resolve-Path -LiteralPath $item).Path
}

if (-not (Test-Path -LiteralPath $ExternalPython -PathType Leaf)) {
    throw "External recovery Python not found: $ExternalPython"
}
$ExternalPython = (Resolve-Path -LiteralPath $ExternalPython).Path
if (-not (Test-Path -LiteralPath $FourDHumansRepo -PathType Container)) {
    throw "4D-Humans repo not found: $FourDHumansRepo"
}
$FourDHumansRepo = (Resolve-Path -LiteralPath $FourDHumansRepo).Path

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $BodyRigPython = $venvPython
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) {
            throw "BodyRig Python not found. Create .venv or pass -BodyRigPython."
        }
        $BodyRigPython = $pythonCommand.Source
    }
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $OutputDir = Join-Path ([System.IO.Path]::GetTempPath()) "bodyrig-acceptance-$stamp"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$preflightPath = Join-Path $OutputDir "bodyrig-recovery-preflight.json"
$proofPath = Join-Path $OutputDir "bodyrig-recovery-proof.json"
$packagePath = Join-Path $OutputDir "$BodyId.mrbody"
$reportPath = Join-Path $OutputDir "bodyrig-acceptance.json"

Write-Host "BodyRig acceptance | revision $head"
Write-Host "Artifacts: $OutputDir"
Write-Host "Source clips: $($resolvedSources.Count) (filenames are not written to the acceptance report)"

$preflightArgs = @(
    "-m", "bodyrig.preflight_cli",
    "--python", $ExternalPython,
    "--repo", $FourDHumansRepo,
    "--out", $preflightPath
)
if ($AllowCpu) {
    $preflightArgs += "--allow-cpu"
}
Invoke-Checked -Executable $BodyRigPython -Arguments $preflightArgs -Step "Recovery preflight"

$recoverArgs = @(
    "-m", "bodyrig.recover_cli",
    "--python", $ExternalPython,
    "--repo", $FourDHumansRepo,
    "--out", $proofPath
)
if (-not [string]::IsNullOrWhiteSpace($TrackId)) {
    $recoverArgs += @("--track-id", $TrackId)
}
$recoverArgs += $resolvedSources
Invoke-Checked -Executable $BodyRigPython -Arguments $recoverArgs -Step "Video recovery"

$fitArgs = @(
    "-m", "bodyrig.avatar_cli",
    $proofPath,
    "--body-id", $BodyId,
    "--name", $Name,
    "--out", $packagePath
)
Invoke-Checked -Executable $BodyRigPython -Arguments $fitArgs -Step "Avatar fitting / .mrbody build"

$inspectCode = @'
import hashlib, json, pathlib, sys
from bodyrig.avatar import parse_glb_json, validate_vrm1
from bodyrig.package import validate_package
proof_path = pathlib.Path(sys.argv[1])
package_path = pathlib.Path(sys.argv[2])
proof = json.loads(proof_path.read_text(encoding="utf-8"))
validated = validate_package(package_path)
pipeline = validated.provenance["pipeline"]
recovery = next((s for s in pipeline if s.get("stage") == "body-recovery"), None)
fitting = next((s for s in pipeline if s.get("stage") == "avatar-fitting"), None)
import zipfile
with zipfile.ZipFile(package_path, "r") as archive:
    vrm = validate_vrm1(archive.read("avatar.vrm"))
extra = vrm.get("extras", {}).get("bodyrig", {})
result = {
    "package_sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
    "body_id": validated.manifest["id"],
    "body_name": validated.manifest["name"],
    "payload_names": list(validated.payload_names),
    "bodyprint_matches_proof": validated.bodyprint == proof.get("bodyprint"),
    "source_count_matches": validated.provenance["source"]["count"] == proof.get("source_count"),
    "recovery_provenance_matches": bool(recovery and recovery.get("adapter") == proof.get("adapter") and recovery.get("revision") == proof.get("revision")),
    "avatar_fitting_provenance_present": bool(fitting and fitting.get("adapter") and fitting.get("revision")),
    "vrm_spec_version": vrm["extensions"]["VRMC_vrm"]["specVersion"],
    "placeholder_avatar": extra.get("placeholder") is True,
}
print(json.dumps(result, separators=(",", ":"), allow_nan=False))
'@
$packageInfoRaw = & $BodyRigPython -c $inspectCode $proofPath $packagePath
if ($LASTEXITCODE -ne 0) {
    throw "Final .mrbody inspection failed with exit code $LASTEXITCODE"
}
$packageInfo = $packageInfoRaw | ConvertFrom-Json
$preflight = Get-Content -LiteralPath $preflightPath -Raw | ConvertFrom-Json
$proof = Get-Content -LiteralPath $proofPath -Raw | ConvertFrom-Json

$observedFramesOk = ($proof.observed_frames -is [int] -or $proof.observed_frames -is [long]) -and [int64]$proof.observed_frames -ge 2
$shape = $proof.bodyprint.shape
$shapePresent = $null -ne $shape -and $null -ne $shape.shoulder_to_height -and $null -ne $shape.hip_to_height -and $null -ne $shape.arm_to_height -and $null -ne $shape.leg_to_height
$motion = $proof.bodyprint.motion
$motionPresent = $null -ne $motion -and $null -ne $motion.energy -and ($null -ne $motion.gesture_amplitude -or $null -ne $motion.head_motion)

$checks = [ordered]@{
    bodyrig_checkout_clean = ($dirty.Count -eq 0)
    preflight_ok = ($preflight.ok -eq $true)
    recovery_adapter_pinned = (-not [string]::IsNullOrWhiteSpace([string]$proof.adapter) -and -not [string]::IsNullOrWhiteSpace([string]$proof.revision))
    observed_frames_ge_2 = $observedFramesOk
    source_derived_shape_present = $shapePresent
    source_derived_motion_present = $motionPresent
    bodyprint_matches_package = ($packageInfo.bodyprint_matches_proof -eq $true)
    source_count_matches_package = ($packageInfo.source_count_matches -eq $true)
    recovery_provenance_matches = ($packageInfo.recovery_provenance_matches -eq $true)
    avatar_fitting_provenance_present = ($packageInfo.avatar_fitting_provenance_present -eq $true)
    avatar_is_vrm_1_0 = ([string]$packageInfo.vrm_spec_version -eq "1.0")
}
$automatedPass = -not ($checks.Values -contains $false)

$report = [ordered]@{
    format = "bodyrig-rig-acceptance"
    version = 1
    created_at = [DateTime]::UtcNow.ToString("o")
    bodyrig_revision = $head
    bodyrig_checkout_clean = ($dirty.Count -eq 0)
    source_count = $resolvedSources.Count
    recovery = [ordered]@{
        adapter = $proof.adapter
        revision = $proof.revision
        track_id = $proof.track_id
        observed_frames = $proof.observed_frames
    }
    package = $packageInfo
    checks = $checks
    automated_pass = $automatedPass
    physical_renderer_acceptance = "pending"
    production_activation = $false
}
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding UTF8

if (-not $automatedPass) {
    Write-Error "BodyRig automated acceptance: FAIL. See $reportPath"
    exit 1
}

Write-Host ""
Write-Host "BodyRig automated acceptance: PASS"
Write-Host "Package: $packagePath"
Write-Host "Report:  $reportPath"
Write-Host "Physical Unity/Quest renderer acceptance: PENDING"
Write-Host "production_activation=false"
exit 0
