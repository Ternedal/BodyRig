param(
    [Parameter(Mandatory = $true)][string]$BaselineCloneOutput,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$AdjustmentEvidence = "",
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-V1Version($Value) {
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }
}
function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath (Need-File -Path $Path -Label "Hash input") -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $clean = $Value.Trim().ToLowerInvariant()
    if ($clean -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $clean
}
function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$Executable,[Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Step)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}
function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Output already exists: $Path" }
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig retained fidelity package refresh is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Retained fidelity package refresh requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedBodyRigModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout-bound BodyRig module"
$moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound BodyRig Python authority." }
$actualBodyRigModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
if (-not [string]::Equals($actualBodyRigModule, $expectedBodyRigModule, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from a different checkout/package: $actualBodyRigModule"
}

$floorRaw = @(& $BodyRigPython -c "from bodyrig.physical_handoff_floor import MINIMUM_PHYSICAL_HANDOFF_REVISION; print(MINIMUM_PHYSICAL_HANDOFF_REVISION)" 2>&1)
if ($LASTEXITCODE -ne 0 -or $floorRaw.Count -ne 1) { throw "Could not resolve current physical fidelity floor." }
$floor = ([string]$floorRaw[0]).Trim().ToLowerInvariant()
if ($floor -notmatch '^[0-9a-f]{40}$') { throw "Current physical fidelity floor is invalid." }
& git -C $repoRoot merge-base --is-ancestor $floor $head 2>$null
if ($LASTEXITCODE -ne 0) { throw "Current checkout $head does not meet the physical fidelity floor $floor." }

if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    $RigSetupReport = [string][Environment]::GetEnvironmentVariable("BODYRIG_RIG_SETUP_REPORT")
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport) -and -not [string]::IsNullOrWhiteSpace([string]$env:LOCALAPPDATA)) {
    $candidate = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $RigSetupReport = $candidate }
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    throw "BodyRig rig setup report is required to rehydrate reboot-safe SiTH resume authority."
}
$RigSetupReport = Need-File -Path $RigSetupReport -Label "BodyRig rig setup report"
$rigRaw = @(& $BodyRigPython -m bodyrig.rig_setup $RigSetupReport 2>&1)
if ($LASTEXITCODE -ne 0 -or $rigRaw.Count -lt 1) { throw "BodyRig rig setup report failed live validation." }
try { $rig = (($rigRaw -join "`n").Trim() | ConvertFrom-Json -Depth 50) }
catch { throw "BodyRig rig setup validator returned unreadable JSON." }
$sithSetupReport = Need-File -Path ([string]$rig.high_fidelity.setup_report) -Label "Nested SiTH setup report"
$sithRaw = @(& $BodyRigPython -m bodyrig.sith_setup $sithSetupReport 2>&1)
if ($LASTEXITCODE -ne 0 -or $sithRaw.Count -lt 1) { throw "Nested SiTH setup report failed live validation." }
try { $sith = (($sithRaw -join "`n").Trim() | ConvertFrom-Json -Depth 50) }
catch { throw "SiTH setup validator returned unreadable JSON." }
$reconCheckpointSha = Need-Sha256 -Value ([string]$sith.checkpoints.recon_model.sha256) -Label "SiTH recon checkpoint SHA-256"
$smplxCheckpointSha = Need-Sha256 -Value ([string]$sith.checkpoints.smplerx.sha256) -Label "SiTH SMPL-X checkpoint SHA-256"
$rigSetupSha = Sha256 $RigSetupReport
$sithSetupSha = Sha256 $sithSetupReport

$BaselineCloneOutput = Need-Directory -Path $BaselineCloneOutput -Label "Baseline clone output"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Retained fidelity refresh output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Retained fidelity refresh output must have a parent directory." }
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
$attempt = Join-Path $outputParent ("." + [IO.Path]::GetFileName($OutputDir) + ".partial-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attempt | Out-Null
$committed = $false

try {
    $cloneDir = Need-Directory -Path (Join-Path $BaselineCloneOutput "clone") -Label "Baseline portable clone directory"
    $proof = Need-File -Path (Join-Path $cloneDir "bodyrig-recovery-proof.json") -Label "Baseline recovery proof"
    $identity = Need-File -Path (Join-Path $cloneDir "bodyrig-visual-identity.json") -Label "Baseline visual identity"
    $portableIdentity = Need-File -Path (Join-Path $cloneDir "bodyrig-portable-identity.json") -Label "Baseline portable identity"
    $baselineFitterConfig = Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-sith-fitter-config.json") -Label "Baseline SiTH fitter config"
    $reconstruction = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\reconstruction.json") -Label "Retained SiTH reconstruction"
    $reconstructionAuthority = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\reconstruction-authority.json") -Label "Retained SiTH reconstruction authority"
    $sourceMesh = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\meshes\000_reco.obj") -Label "Retained source mesh"
    $donorObj = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\smplx\000_smplx.obj") -Label "Retained fitted donor OBJ"
    $fitParams = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\smplx\000_fit.json") -Label "Retained fitted donor parameters"

    try { $reconstructionAuthorityValue = Get-Content -LiteralPath $reconstructionAuthority -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
    catch { throw "Retained SiTH reconstruction authority is unreadable." }
    $bodyModelGender = ([string]$reconstructionAuthorityValue.body_model_gender).Trim().ToLowerInvariant()
    if ([string]$reconstructionAuthorityValue.format -ne "bodyrig-sith-reconstruction-authority" -or
        -not (Test-V1Version $reconstructionAuthorityValue.version) -or
        $bodyModelGender -notin @("female","male","neutral")) {
        throw "Retained SiTH reconstruction authority cannot provide canonical body-model gender."
    }
    $authorityProbeCode = @'
import json,sys
from bodyrig.sith_reconstruction_authority import validate_reconstruction_authority
print(json.dumps(validate_reconstruction_authority(sys.argv[1],expected_body_model_gender=sys.argv[2]),separators=(",",":")))
'@
    $authorityProbe = @(& $BodyRigPython -c $authorityProbeCode $IdentityWorkspace $bodyModelGender 2>&1)
    if ($LASTEXITCODE -ne 0 -or $authorityProbe.Count -ne 1) {
        throw "Retained SiTH reconstruction authority failed current strict validation."
    }

    $sourcePackageMatches = @(Get-ChildItem -LiteralPath $cloneDir -Filter "*.mrbody" -File)
    if ($sourcePackageMatches.Count -ne 1) { throw "Baseline clone must contain exactly one .mrbody package; found $($sourcePackageMatches.Count)." }
    $sourcePackage = $sourcePackageMatches[0].FullName

    $inspectCode = @'
import hashlib,json,pathlib,sys
from bodyrig.package import validate_package
p=pathlib.Path(sys.argv[1]).resolve(); v=validate_package(p)
print(json.dumps({"body_id":v.manifest["id"],"name":v.manifest["name"],"builder_revision":v.manifest["builder"].get("revision"),"package_sha256":hashlib.sha256(p.read_bytes()).hexdigest()},separators=(",",":")))
'@
    $sourceRaw = @(& $BodyRigPython -c $inspectCode $sourcePackage 2>&1)
    if ($LASTEXITCODE -ne 0 -or $sourceRaw.Count -ne 1) { throw "Baseline package failed strict validation." }
    try { $sourceInfo = ([string]$sourceRaw[0]) | ConvertFrom-Json }
    catch { throw "Baseline package validator returned unreadable JSON." }

    try { $portable = Get-Content -LiteralPath $portableIdentity -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
    catch { throw "Baseline portable identity is unreadable." }
    $bodyAlias = ([string]$portable.requested_alias).Trim()
    if ($bodyAlias -notmatch '^[a-z0-9æøå_-]{1,160}$') { throw "Baseline portable identity requested_alias is invalid." }
    if ([string]::IsNullOrWhiteSpace([string]$sourceInfo.name)) { throw "Baseline package display name is empty." }

    try { $fitter = Get-Content -LiteralPath $baselineFitterConfig -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
    catch { throw "Baseline SiTH fitter config is unreadable." }
    $fitterFields = @($fitter.PSObject.Properties.Name | Sort-Object)
    $expectedFitterFields = @("adapter","capabilities","command","format","revision","timeout_seconds","version" | Sort-Object)
    if (($fitterFields -join ",") -ne ($expectedFitterFields -join ",") -or
        [string]$fitter.format -ne "bodyrig-external-fitter-config" -or
        -not (Test-V1Version $fitter.version) -or
        [string]$fitter.adapter -ne "sith-smplx-vrm" -or
        [string]$fitter.revision -ne "1") {
        throw "Baseline fitter config is not the canonical built-in SiTH v1 config."
    }
    $capabilities = $fitter.capabilities
    if ($null -eq $capabilities -or
        $capabilities.visual_identity -isnot [bool] -or $capabilities.visual_identity -ne $true -or
        $capabilities.textures -isnot [bool] -or $capabilities.textures -ne $true -or
        $capabilities.hair -isnot [bool] -or $capabilities.hair -ne $false -or
        $capabilities.clothing -isnot [bool] -or $capabilities.clothing -ne $false) {
        throw "Baseline fitter config capabilities do not match the built-in SiTH v1 boundary."
    }
    $fitterCommand = @($fitter.command)
    if ($fitterCommand.Count -lt 3 -or [string]$fitterCommand[1] -ne "-m" -or [string]$fitterCommand[2] -ne "bodyrig.sith_fitter_orchestrator") {
        throw "Baseline fitter config does not invoke the canonical BodyRig SiTH orchestrator."
    }
    $rehydratedCommand = @($BodyRigPython)
    for ($index = 1; $index -lt $fitterCommand.Count; $index++) { $rehydratedCommand += [string]$fitterCommand[$index] }
    $currentFitterConfigValue = [ordered]@{
        format = "bodyrig-external-fitter-config"
        version = 1
        adapter = "sith-smplx-vrm"
        revision = "1"
        command = $rehydratedCommand
        capabilities = [ordered]@{
            visual_identity = $true
            textures = $true
            hair = $false
            clothing = $false
        }
        timeout_seconds = [int]$fitter.timeout_seconds
    }
    if ($currentFitterConfigValue.timeout_seconds -lt 1 -or $currentFitterConfigValue.timeout_seconds -gt 86400) {
        throw "Baseline fitter timeout is outside the canonical v1 range."
    }
    $currentFitterConfig = Join-Path $attempt "current-floor-sith-fitter-config.json"
    Write-CreateOnlyJson -Path $currentFitterConfig -Value $currentFitterConfigValue

    $reconstructionShaBefore = Sha256 $reconstruction
    $reconstructionAuthorityShaBefore = Sha256 $reconstructionAuthority
    $sourceMeshShaBefore = Sha256 $sourceMesh
    $donorShaBefore = Sha256 $donorObj
    $fitShaBefore = Sha256 $fitParams
    $sourcePackageSha = Sha256 $sourcePackage
    $proofShaBefore = Sha256 $proof
    $identityShaBefore = Sha256 $identity
    $portableIdentityShaBefore = Sha256 $portableIdentity
    $baselineFitterConfigShaBefore = Sha256 $baselineFitterConfig
    $currentFitterConfigSha = Sha256 $currentFitterConfig

    $fitArgs = @(
        "-m", "bodyrig.external_fitter_cli",
        $proof,
        "--identity-profile", $identity,
        "--identity-workspace", $IdentityWorkspace,
        "--config", $currentFitterConfig,
        "--body-id", $bodyAlias,
        "--portable-identity", $portableIdentity,
        "--name", [string]$sourceInfo.name
    )

    $adjustmentEvidenceSha = ""
    $adjustmentEvidenceCopy = ""
    if (-not [string]::IsNullOrWhiteSpace($AdjustmentEvidence)) {
        $AdjustmentEvidence = Need-File -Path $AdjustmentEvidence -Label "Proof-bound BodyPrint adjustment evidence"
        $adjustmentEvidenceSha = Sha256 $AdjustmentEvidence
        $adjustmentEvidenceCopy = Join-Path $attempt "bodyrig-bodyprint-adjustment.json"
        Copy-Item -LiteralPath $AdjustmentEvidence -Destination $adjustmentEvidenceCopy
        if ((Sha256 $adjustmentEvidenceCopy) -ne $adjustmentEvidenceSha) { throw "Adjustment evidence changed while staging current-floor refresh." }
        $adjustmentProbe = @(& $BodyRigPython -c "import sys; from bodyrig.bodyprint_adjustment import load_adjustment_evidence; load_adjustment_evidence(sys.argv[1], proof_path=sys.argv[2]); print('ok')" $adjustmentEvidenceCopy $proof 2>&1)
        if ($LASTEXITCODE -ne 0 -or $adjustmentProbe.Count -ne 1 -or ([string]$adjustmentProbe[0]).Trim() -ne "ok") {
            throw "Adjustment evidence is not valid for the exact retained recovery proof."
        }
        $fitArgs += @("--bodyprint-adjustment", $adjustmentEvidenceCopy)
    }

    $packagePath = Join-Path $attempt "$bodyAlias.mrbody"
    $fitArgs += @("--out", $packagePath)

    Write-Host "BodyRig retained fidelity package refresh"
    Write-Host "Revision:       $head"
    Write-Host "Physical floor: $floor"
    Write-Host "BodyRig module: $actualBodyRigModule"
    Write-Host "Source package: $sourcePackageSha"
    Write-Host "Reconstruction: $reconstructionShaBefore"
    Write-Host "SMPL-X gender:  $bodyModelGender"
    Write-Host "Adjustment:     $(if ($adjustmentEvidenceSha) { $adjustmentEvidenceSha } else { '<none>' })"
    Write-Host "SiTH rerun:     FALSE"
    Write-Host "Fitter rerun:   TRUE (current checkout orchestrator)"
    Write-Host "Production:     FALSE"
    Write-Host ""

    $environmentNames = @(
        "BODYRIG_SITH_RECON_CHECKPOINT_SHA256",
        "BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256",
        "BODYRIG_SITH_BODY_MODEL_GENDER"
    )
    $previousEnvironment = @{}
    foreach ($name in $environmentNames) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, [EnvironmentVariableTarget]::Process)
    }
    try {
        Set-Item -Path "Env:BODYRIG_SITH_RECON_CHECKPOINT_SHA256" -Value $reconCheckpointSha
        Set-Item -Path "Env:BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256" -Value $smplxCheckpointSha
        Set-Item -Path "Env:BODYRIG_SITH_BODY_MODEL_GENDER" -Value $bodyModelGender
        Invoke-Checked -Executable $BodyRigPython -Arguments $fitArgs -Step "Refit/repackage retained SiTH reconstruction on current fidelity floor"
    } finally {
        foreach ($name in $environmentNames) {
            $prior = $previousEnvironment[$name]
            if ($null -eq $prior) { Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue }
            else { Set-Item -Path "Env:$name" -Value ([string]$prior) }
        }
    }

    if ((Sha256 $reconstruction) -ne $reconstructionShaBefore -or
        (Sha256 $reconstructionAuthority) -ne $reconstructionAuthorityShaBefore -or
        (Sha256 $sourceMesh) -ne $sourceMeshShaBefore -or
        (Sha256 $donorObj) -ne $donorShaBefore -or
        (Sha256 $fitParams) -ne $fitShaBefore -or
        (Sha256 $sourcePackage) -ne $sourcePackageSha -or
        (Sha256 $proof) -ne $proofShaBefore -or
        (Sha256 $identity) -ne $identityShaBefore -or
        (Sha256 $portableIdentity) -ne $portableIdentityShaBefore -or
        (Sha256 $baselineFitterConfig) -ne $baselineFitterConfigShaBefore -or
        (-not [string]::IsNullOrWhiteSpace($AdjustmentEvidence) -and (Sha256 $AdjustmentEvidence) -ne $adjustmentEvidenceSha)) {
        throw "Retained current-floor refresh authority inputs changed during fitter execution."
    }

    $refreshedRaw = @(& $BodyRigPython -c $inspectCode $packagePath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $refreshedRaw.Count -ne 1) { throw "Refreshed package failed strict validation." }
    try { $refreshed = ([string]$refreshedRaw[0]) | ConvertFrom-Json }
    catch { throw "Refreshed package validator returned unreadable JSON." }
    if ([string]$refreshed.builder_revision -ne $head) { throw "Refreshed package builder revision is not the exact current checkout." }
    if ([string]$refreshed.body_id -ne [string]$sourceInfo.body_id) { throw "Refreshed package changed canonical body identity." }

    $pipelineCode = @'
import json,sys
from bodyrig.package import validate_package
v=validate_package(sys.argv[1])
print(json.dumps(v.provenance["pipeline"],separators=(",",":")))
'@
    $pipelineRaw = @(& $BodyRigPython -c $pipelineCode $packagePath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $pipelineRaw.Count -ne 1) { throw "Refreshed package provenance could not be read." }
    try { $pipeline = @(([string]$pipelineRaw[0]) | ConvertFrom-Json) }
    catch { throw "Refreshed package provenance returned unreadable JSON." }
    $adjustmentStages = @($pipeline | Where-Object { [string]$_.stage -eq "bodyprint-adjustment" })
    if ([string]::IsNullOrWhiteSpace($adjustmentEvidenceSha)) {
        if ($adjustmentStages.Count -ne 0) { throw "Unadjusted current-floor refresh unexpectedly contains a bodyprint-adjustment stage." }
    } else {
        if ($adjustmentStages.Count -ne 1) { throw "Adjusted current-floor refresh must contain exactly one bodyprint-adjustment stage." }
        if ([string]$adjustmentStages[0].revision -ne $adjustmentEvidenceSha) {
            throw "Adjusted current-floor refresh does not preserve the exact selected adjustment evidence provenance."
        }
    }

    $result = [ordered]@{
        format = "bodyrig-retained-fidelity-package-refresh"
        version = 1
        bodyrig_revision = $head
        minimum_physical_handoff_revision = $floor
        checkout_bound_bodyrig_module = $actualBodyRigModule
        body_alias = $bodyAlias
        canonical_body_id = [string]$refreshed.body_id
        source_package_sha256 = $sourcePackageSha
        source_builder_revision = [string]$sourceInfo.builder_revision
        recovery_proof_sha256 = $proofShaBefore
        visual_identity_sha256 = $identityShaBefore
        portable_identity_sha256 = $portableIdentityShaBefore
        baseline_fitter_config_sha256 = $baselineFitterConfigShaBefore
        current_fitter_config_sha256 = $currentFitterConfigSha
        rig_setup_sha256 = $rigSetupSha
        sith_setup_sha256 = $sithSetupSha
        sith_recon_checkpoint_sha256 = $reconCheckpointSha
        sith_smplx_checkpoint_sha256 = $smplxCheckpointSha
        body_model_gender = $bodyModelGender
        refreshed_package_sha256 = [string]$refreshed.package_sha256
        refreshed_builder_revision = [string]$refreshed.builder_revision
        reconstruction_sha256 = $reconstructionShaBefore
        reconstruction_authority_sha256 = $reconstructionAuthorityShaBefore
        retained_source_mesh_sha256 = $sourceMeshShaBefore
        retained_donor_obj_sha256 = $donorShaBefore
        retained_fit_params_sha256 = $fitShaBefore
        adjustment_evidence_sha256 = $adjustmentEvidenceSha
        expensive_reconstruction_rerun = $false
        fitter_rerun = $true
        comparison_only = $true
        human_visual_authority_required = $true
        production_activation = $false
        semantics = "current-floor-refit-repackage-from-retained-sith-with-checkout-bound-fitter-not-reconstruction"
    }
    $resultPath = Join-Path $attempt "retained-fidelity-package-refresh.json"
    Write-CreateOnlyJson -Path $resultPath -Value $result

    if (Test-Path -LiteralPath $OutputDir) { throw "Retained fidelity refresh output appeared during build: $OutputDir" }
    Move-Item -LiteralPath $attempt -Destination $OutputDir
    $committed = $true

    Write-Host ""
    Write-Host "BodyRig retained fidelity package refresh: PASS"
    Write-Host "Package:        $(Join-Path $OutputDir "$bodyAlias.mrbody")"
    Write-Host "Package SHA:    $([string]$refreshed.package_sha256)"
    Write-Host "Builder:        $([string]$refreshed.builder_revision)"
    Write-Host "Reconstruction: reused unchanged ($reconstructionShaBefore)"
    Write-Host "Authority:      comparison-only; human visual review required; no production activation"
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $attempt -PathType Container)) {
        Remove-Item -LiteralPath $attempt -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit 0