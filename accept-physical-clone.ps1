param(
    [Parameter(Mandatory = $true)][string]$SessionReport,
    [string]$BodyRigPython = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Resolve-InputDirectory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Sha256([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Read-Json([string]$Path,[string]$Label) {
    $resolved = Resolve-InputFile -Path $Path -Label $Label
    try { $value = Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $resolved" }
    return [pscustomobject]@{ Path=$resolved; Value=$value; Hash=(Sha256 $resolved) }
}
function Copy-Exact([string]$Source,[string]$Destination,[string]$Label) {
    Copy-Item -LiteralPath $Source -Destination $Destination
    if ((Sha256 $Source) -ne (Sha256 $Destination)) { throw "$Label changed while copying into acceptance bundle." }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Could not bind high-fidelity acceptance to BodyRig Git HEAD." }
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; high-fidelity Gate A requires the exact clean clone revision." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"
$SessionReport = Resolve-InputFile -Path $SessionReport -Label "Physical clone session report"

$sessionRaw = & $BodyRigPython -m bodyrig.physical_session validate $SessionReport
if ($LASTEXITCODE -ne 0) { throw "Physical clone session failed strict validation." }
try { $session = $sessionRaw | ConvertFrom-Json } catch { throw "Physical clone session validator returned unreadable JSON." }
if ([string]$session.status -ne "pass" -or [string]$session.stage -ne "complete") { throw "Physical clone session is not a completed PASS." }
if ($session.bodyrig_checkout_clean -ne $true) { throw "Physical clone session did not start from a clean BodyRig checkout." }
if (([string]$session.bodyrig_revision).ToLowerInvariant() -ne $head) { throw "Current BodyRig HEAD does not match the physical clone session revision." }
$sessionHash = Sha256 $SessionReport

$readinessPath = [System.IO.Path]::ChangeExtension($SessionReport, "readiness.json")
$readinessFile = Read-Json $readinessPath "Physical clone readiness report"
$readiness = $readinessFile.Value
if ($readinessFile.Hash -ne ([string]$session.readiness_sha256).ToLowerInvariant()) { throw "Readiness report SHA-256 no longer matches the physical clone session." }
if ([string]$readiness.format -ne "bodyrig-rig-readiness" -or [int]$readiness.version -ne 1 -or $readiness.ready -ne $true) { throw "Physical clone readiness report is not a valid READY v1 report." }
if (([string]$readiness.rig_setup_sha256).ToLowerInvariant() -ne ([string]$session.rig_setup_sha256).ToLowerInvariant()) { throw "Rig setup SHA-256 differs between session and readiness evidence." }

$cloneRoot = Resolve-InputDirectory -Path ([string]$session.clone_output) -Label "Physical clone output"
$cloneDir = Resolve-InputDirectory -Path (Join-Path $cloneRoot "clone") -Label "Portable clone artifacts"
$bodyId = [string]$session.body_id
$packageSource = Resolve-InputFile -Path (Join-Path $cloneDir "$bodyId.mrbody") -Label "High-fidelity .mrbody"
$preflightFile = Read-Json (Join-Path $cloneDir "bodyrig-recovery-preflight.json") "Recovery preflight"
$proofPath = Resolve-InputFile -Path (Join-Path $cloneDir "bodyrig-recovery-proof.json") -Label "Recovery proof"
$identityPath = Resolve-InputFile -Path (Join-Path $cloneDir "bodyrig-visual-identity.json") -Label "Visual identity profile"

if ([string]::IsNullOrWhiteSpace($OutputDir)) { $OutputDir = Join-Path $cloneRoot "acceptance" }
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Acceptance output already exists; refusing cross-run reuse: $OutputDir" }
New-Item -ItemType Directory -Path $OutputDir | Out-Null

$packagePath = Join-Path $OutputDir "$bodyId.mrbody"
$sessionCopy = Join-Path $OutputDir "bodyrig-physical-clone-session.json"
$readinessCopy = Join-Path $OutputDir "bodyrig-rig-readiness.json"
Copy-Exact $packageSource $packagePath "High-fidelity .mrbody"
Copy-Exact $SessionReport $sessionCopy "Physical clone session"
Copy-Exact $readinessFile.Path $readinessCopy "Rig readiness report"

$inspectCode = @'
import hashlib, json, pathlib, sys, zipfile
from bodyrig.avatar import validate_vrm1
from bodyrig.identity import bind_visual_identity_to_proof
from bodyrig.package import validate_package
from bodyrig.proof import load_recovery_proof, read_canonical_json
proof = load_recovery_proof(sys.argv[1])
identity = bind_visual_identity_to_proof(read_canonical_json(sys.argv[2], label="visual identity profile"), proof)
p = pathlib.Path(sys.argv[3]).resolve()
v = validate_package(p)
pipeline = v.provenance["pipeline"]
recovery = next((s for s in pipeline if s.get("stage") == "body-recovery"), None)
visual = next((s for s in pipeline if s.get("stage") == "visual-identity-capture"), None)
fitting = next((s for s in pipeline if s.get("stage") == "avatar-fitting"), None)
with zipfile.ZipFile(p, "r") as archive:
    vrm = validate_vrm1(archive.read("avatar.vrm"))
extra = vrm.get("extras", {}).get("bodyrig", {})
print(json.dumps({
    "package_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    "body_id": v.manifest["id"],
    "body_name": v.manifest["name"],
    "payload_names": list(v.payload_names),
    "bodyprint_matches_proof": v.bodyprint == proof.get("bodyprint"),
    "source_count_matches": v.provenance["source"]["count"] == proof.get("source_count"),
    "recovery_provenance_matches": bool(recovery and recovery.get("adapter") == proof.get("adapter") and recovery.get("revision") == proof.get("revision")),
    "visual_identity_provenance_matches": bool(visual and visual.get("adapter") == identity.get("adapter") and visual.get("revision") == identity.get("revision")),
    "avatar_fitting_provenance_present": bool(fitting and fitting.get("adapter") and fitting.get("revision")),
    "fitting_adapter": fitting.get("adapter") if fitting else None,
    "fitting_revision": fitting.get("revision") if fitting else None,
    "vrm_spec_version": vrm["extensions"]["VRMC_vrm"]["specVersion"],
    "placeholder_avatar": extra.get("placeholder") is True,
    "source_count": proof["source_count"],
    "recovery_adapter": proof["adapter"],
    "recovery_revision": proof["revision"],
    "track_id": proof["track_id"],
    "observed_frames": proof["observed_frames"],
    "shape_present": all(k in proof["bodyprint"].get("shape", {}) for k in ("shoulder_to_height","hip_to_height","arm_to_height","leg_to_height")),
    "motion_present": "energy" in proof["bodyprint"].get("motion", {}) and any(k in proof["bodyprint"].get("motion", {}) for k in ("gesture_amplitude","head_motion")),
}, separators=(",", ":"), allow_nan=False))
'@
$packageInfoRaw = & $BodyRigPython -c $inspectCode $proofPath $identityPath $packagePath
if ($LASTEXITCODE -ne 0) { throw "High-fidelity package/proof/identity inspection failed." }
try { $packageInfo = $packageInfoRaw | ConvertFrom-Json } catch { throw "High-fidelity package inspection returned unreadable JSON." }

if ([string]$packageInfo.body_id -ne $bodyId) { throw "Physical session body id does not match .mrbody." }
if ($preflightFile.Value.ok -ne $true) { throw "Recovery preflight did not report ok=true." }
if ($packageInfo.bodyprint_matches_proof -ne $true -or $packageInfo.source_count_matches -ne $true -or $packageInfo.recovery_provenance_matches -ne $true) { throw "High-fidelity package is not bound to the recovery proof." }
if ($packageInfo.visual_identity_provenance_matches -ne $true) { throw "High-fidelity package is not bound to the visual identity profile." }
if ($packageInfo.avatar_fitting_provenance_present -ne $true -or [string]$packageInfo.fitting_adapter -ne "sith-smplx-vrm" -or [string]$packageInfo.fitting_revision -ne "1") { throw "Physical Gate A requires the built-in sith-smplx-vrm v1 fitting path." }
if ([string]$packageInfo.vrm_spec_version -ne "1.0") { throw "High-fidelity avatar is not VRM 1.0." }
if ($packageInfo.placeholder_avatar -eq $true) { throw "Physical Gate A refuses a placeholder avatar; the accepted package must be source-derived high fidelity." }
if ([int64]$packageInfo.observed_frames -lt 2 -or $packageInfo.shape_present -ne $true -or $packageInfo.motion_present -ne $true) { throw "Recovery proof lacks required source-derived shape/motion evidence." }

$runtimeDir = Join-Path $OutputDir "runtime"
& $BodyRigPython -m bodyrig.materialize_cli $packagePath --out $runtimeDir | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Runtime materialization from accepted high-fidelity .mrbody failed." }
$runtimeManifestPath = Resolve-InputFile -Path (Join-Path $runtimeDir "runtime-manifest.json") -Label "Materialized runtime manifest"
$runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$packageHash = Sha256 $packagePath
if ([string]$runtimeManifest.format -ne "bodyrig-runtime-assets" -or [int]$runtimeManifest.version -ne 1 -or [string]$runtimeManifest.body_id -ne $bodyId -or ([string]$runtimeManifest.package_sha256).ToLowerInvariant() -ne $packageHash) { throw "Materialized runtime identity does not match the accepted high-fidelity package." }
$runtimeHash = Sha256 $runtimeManifestPath

$checks = [ordered]@{
    bodyrig_checkout_clean = $true
    preflight_ok = $true
    recovery_adapter_pinned = $true
    observed_frames_ge_2 = $true
    source_derived_shape_present = $true
    source_derived_motion_present = $true
    bodyprint_matches_package = $true
    source_count_matches_package = $true
    recovery_provenance_matches = $true
    avatar_fitting_provenance_present = $true
    avatar_is_vrm_1_0 = $true
    runtime_materialized_from_package = $true
}
$report = [ordered]@{
    format = "bodyrig-rig-acceptance"
    version = 1
    created_at = [DateTime]::UtcNow.ToString("o")
    bodyrig_revision = $head
    bodyrig_checkout_clean = $true
    source_count = [int]$packageInfo.source_count
    physical_clone = [ordered]@{
        session_sha256 = (Sha256 $sessionCopy)
        readiness_sha256 = (Sha256 $readinessCopy)
        mode = "stash-sith-high-fidelity"
    }
    recovery = [ordered]@{
        adapter = [string]$packageInfo.recovery_adapter
        revision = [string]$packageInfo.recovery_revision
        track_id = [string]$packageInfo.track_id
        observed_frames = [int]$packageInfo.observed_frames
    }
    package = [ordered]@{
        package_sha256 = $packageHash
        body_id = $bodyId
        body_name = [string]$packageInfo.body_name
        payload_names = @($packageInfo.payload_names)
        bodyprint_matches_proof = $true
        source_count_matches = $true
        recovery_provenance_matches = $true
        avatar_fitting_provenance_present = $true
        vrm_spec_version = "1.0"
        placeholder_avatar = $false
    }
    runtime = [ordered]@{
        manifest = "runtime/runtime-manifest.json"
        manifest_sha256 = $runtimeHash
        materialized_from_package = $true
    }
    checks = $checks
    automated_pass = $true
    physical_renderer_acceptance = "pending"
    production_activation = $false
}
$reportPath = Join-Path $OutputDir "bodyrig-acceptance.json"
$temp = Join-Path $OutputDir (".bodyrig-acceptance." + [Guid]::NewGuid().ToString("N") + ".tmp")
try {
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $reportPath
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
}

Write-Host "BodyRig high-fidelity Gate A: PASS"
Write-Host "Revision: $head"
Write-Host "Package: $packagePath"
Write-Host "Package SHA-256: $packageHash"
Write-Host "Runtime manifest: $runtimeManifestPath"
Write-Host "Acceptance report: $reportPath"
Write-Host "Next: load the same runtime manifest in built WindowsPlayer and Quest-class Android renderer."
exit 0
