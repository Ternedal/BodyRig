param(
    [string]$ConvergenceWorkRoot = "",
    [string]$BaselineCloneOutput = "",
    [string]$IdentityWorkspace = "",
    [string]$RigSetupReport = "",
    [ValidatePattern('^[A-Za-z0-9._/-]{1,200}$')]
    [string]$CandidateRef = "candidate/skin-pbr-v2-current-main-20260908",
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$UnityExe = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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
function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical Git SHA: $Value" }
    return $normalized
}
function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256: $Value" }
    return $normalized
}
function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Output already exists: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($Path) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path
    } finally {
        if (Test-Path -LiteralPath $temp -PathType Leaf) { Remove-Item -LiteralPath $temp -Force }
    }
}
function Invoke-Git {
    param([Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Step)
    $raw = @(& git @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "$Step failed: $($raw -join ' ')" }
    return @($raw)
}
function Test-CommitExists {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$Revision)
    $spec = $Revision + "^{commit}"
    & git -C $Root cat-file -e $spec 2>$null
    return ($LASTEXITCODE -eq 0)
}
function Test-IsAncestor {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$Ancestor,[Parameter(Mandatory = $true)][string]$Descendant)
    & git -C $Root merge-base --is-ancestor $Ancestor $Descendant 2>$null
    return ($LASTEXITCODE -eq 0)
}
function Assert-CleanCheckout {
    param([Parameter(Mandatory = $true)][string]$Root,[Parameter(Mandatory = $true)][string]$ExpectedRevision,[Parameter(Mandatory = $true)][string]$Label)
    $head = Need-Revision ((Invoke-Git -Arguments @("-C",$Root,"rev-parse","HEAD") -Step "$Label HEAD") -join "") "$Label HEAD"
    if ($head -ne $ExpectedRevision) { throw "$Label revision changed: expected $ExpectedRevision, got $head" }
    $dirty = @(Invoke-Git -Arguments @("-C",$Root,"status","--porcelain") -Step "$Label status")
    if ($dirty.Count -gt 0) { throw "$Label checkout is dirty; refusing revision-bound A/B authority." }
}
function Invoke-CheckoutPython {
    param(
        [Parameter(Mandatory = $true)][string]$CheckoutRoot,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    $checkoutPath = Need-Directory -Path $CheckoutRoot -Label "$Step checkout"
    $oldPythonPath = [string]$env:PYTHONPATH
    $oldNoBytecode = [string]$env:PYTHONDONTWRITEBYTECODE
    $locationPushed = $false
    try {
        Push-Location -LiteralPath $checkoutPath
        $locationPushed = $true
        $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $checkoutPath } else { "$checkoutPath$([IO.Path]::PathSeparator)$oldPythonPath" })
        $env:PYTHONDONTWRITEBYTECODE = "1"
        $moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "$Step could not resolve checkout-bound BodyRig module." }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $checkoutPath "bodyrig\__init__.py"))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) {
            throw "$Step imported BodyRig from wrong checkout: $actualModule"
        }
        $raw = @(& $BodyRigPython @Arguments 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "$Step failed: $($raw -join ' ')" }
        return @($raw)
    } finally {
        if ([string]::IsNullOrEmpty($oldPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
        if ([string]::IsNullOrEmpty($oldNoBytecode)) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode }
        if ($locationPushed) { Pop-Location }
    }
}
function Get-TreeDigest {
    param([Parameter(Mandatory = $true)][string]$Root)
    $code = @'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]).resolve()
if not root.is_dir(): raise SystemExit("tree root is missing")
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
records=[]
total=0
for path in sorted(root.rglob("*"),key=lambda p:p.relative_to(root).as_posix()):
    if path.is_symlink(): raise SystemExit("tree contains a symlink: "+path.relative_to(root).as_posix())
    if not path.is_file(): continue
    size=path.stat().st_size
    total+=size
    records.append({"path":path.relative_to(root).as_posix(),"byte_count":size,"sha256":sha(path)})
raw=json.dumps(records,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
print(json.dumps({"sha256":hashlib.sha256(raw).hexdigest(),"file_count":len(records),"byte_count":total},separators=(",",":")))
'@
    $raw = @(& $BodyRigPython -c $code $Root 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "Could not hash retained SiTH tree: $($raw -join ' ')" }
    try { return ([string]$raw[0]) | ConvertFrom-Json }
    catch { throw "Retained SiTH tree digest returned unreadable JSON." }
}
function Get-PackageAuthority {
    param([Parameter(Mandatory = $true)][string]$Package,[Parameter(Mandatory = $true)][string]$CheckoutRoot)
    $code = @'
import hashlib,json,pathlib,sys
from bodyrig.package import validate_package
p=pathlib.Path(sys.argv[1]).resolve(); v=validate_package(p)
print(json.dumps({"body_id":v.manifest["id"],"name":v.manifest["name"],"builder_revision":v.manifest["builder"].get("revision"),"package_sha256":hashlib.sha256(p.read_bytes()).hexdigest()},separators=(",",":")))
'@
    $raw = Invoke-CheckoutPython -CheckoutRoot $CheckoutRoot -Arguments @("-c",$code,$Package) -Step "Package authority validation"
    try { return (($raw -join "") | ConvertFrom-Json) }
    catch { throw "Package authority validation returned unreadable JSON." }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig PBR A/B physical review is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }
if ($CandidateRef.Contains("..") -or $CandidateRef.StartsWith("-") -or $CandidateRef.Contains("@{")) { throw "CandidateRef is unsafe." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = (Invoke-Git -Arguments @("-C",$repoRoot,"branch","--show-current") -Step "Current branch") -join ""
if ($branchRaw.Trim() -ne "main") { throw "PBR A/B runner must be launched from the canonical main checkout." }
$baselineRevision = Need-Revision ((Invoke-Git -Arguments @("-C",$repoRoot,"rev-parse","HEAD") -Step "Baseline HEAD") -join "") "baseline revision"
Assert-CleanCheckout -Root $repoRoot -ExpectedRevision $baselineRevision -Label "Baseline"

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

$fetchSpecs = @(
    "+refs/heads/main:refs/remotes/origin/main",
    "+refs/heads/${CandidateRef}:refs/remotes/origin/${CandidateRef}"
)
[void](Invoke-Git -Arguments @("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs -Step "Fetch baseline/candidate refs")
$remoteMain = Need-Revision ((Invoke-Git -Arguments @("-C",$repoRoot,"rev-parse","refs/remotes/origin/main") -Step "Resolve origin/main") -join "") "origin/main"
if ($remoteMain -ne $baselineRevision) { throw "Local main is not current origin/main. Run git pull --ff-only origin main before PBR A/B." }
$candidateRevision = Need-Revision ((Invoke-Git -Arguments @("-C",$repoRoot,"rev-parse","refs/remotes/origin/$CandidateRef") -Step "Resolve candidate ref") -join "") "candidate revision"
if ($candidateRevision -eq $baselineRevision) { throw "Candidate revision equals baseline revision; there is no PBR A/B to run." }
[void](Invoke-Git -Arguments @("-C",$repoRoot,"merge-base","--is-ancestor",$baselineRevision,$candidateRevision) -Step "Candidate ancestry")
$distanceRaw = (Invoke-Git -Arguments @("-C",$repoRoot,"rev-list","--count","$baselineRevision..$candidateRevision") -Step "Candidate distance") -join ""
if ([int]$distanceRaw.Trim() -ne 1) { throw "PBR candidate must be exactly one commit ahead of current main; got $($distanceRaw.Trim())." }
$expectedChanged = @(
    "bodyrig/bridges/sith_pbr_material.py",
    "tests/test_sith_basecolor_detail.py",
    "tests/test_sith_pbr_material.py"
)
$actualChanged = @(Invoke-Git -Arguments @("-C",$repoRoot,"diff","--name-only",$baselineRevision,$candidateRevision,"--") -Step "Candidate diff boundary")
if (($actualChanged -join "`n") -ne ($expectedChanged -join "`n")) {
    throw "PBR candidate diff boundary changed. Expected only the canonical three PBR-v2 files; got: $($actualChanged -join ', ')"
}

$usingConvergence = -not [string]::IsNullOrWhiteSpace($ConvergenceWorkRoot)
$usingExplicit = -not [string]::IsNullOrWhiteSpace($BaselineCloneOutput) -or -not [string]::IsNullOrWhiteSpace($IdentityWorkspace)
if ($usingConvergence -and $usingExplicit) { throw "Use -ConvergenceWorkRoot OR explicit -BaselineCloneOutput/-IdentityWorkspace, not both." }
if (-not $usingConvergence -and -not $usingExplicit) { throw "Pass -ConvergenceWorkRoot or both -BaselineCloneOutput and -IdentityWorkspace." }
if ($usingExplicit -and ([string]::IsNullOrWhiteSpace($BaselineCloneOutput) -or [string]::IsNullOrWhiteSpace($IdentityWorkspace))) {
    throw "Explicit mode requires both -BaselineCloneOutput and -IdentityWorkspace."
}

$checkpointRevision = ""
$safeSourceFloorRevision = ""
$sourcePolicySha256 = ""
if ($usingConvergence) {
    $policyPath = Need-File -Path (Join-Path $repoRoot "contracts\pbr-ab-source-policy-v1.json") -Label "PBR A/B retained-source policy"
    try { $policy = Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "PBR A/B retained-source policy is invalid JSON: $policyPath" }
    $policyFields = @($policy.PSObject.Properties.Name)
    if ($policyFields.Count -ne 3 -or ($policyFields -notcontains "format") -or ($policyFields -notcontains "version") -or ($policyFields -notcontains "safe_source_floor_revision") -or
        [string]$policy.format -ne "bodyrig-pbr-ab-source-policy" -or [int]$policy.version -ne 1) {
        throw "PBR A/B retained-source policy fields/format/version do not match v1."
    }
    $safeSourceFloorRevision = Need-Revision -Value ([string]$policy.safe_source_floor_revision) -Label "Safe-source floor revision"
    $sourcePolicySha256 = (Get-FileHash -LiteralPath $policyPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not (Test-CommitExists -Root $repoRoot -Revision $safeSourceFloorRevision)) {
        throw "BodyRig checkout cannot resolve safe-source floor revision $safeSourceFloorRevision. Use a full/current checkout before selecting retained PBR A/B evidence."
    }

    $ConvergenceWorkRoot = Need-Directory -Path $ConvergenceWorkRoot -Label "Fidelity convergence work root"
    $checkpointDir = Need-Directory -Path (Join-Path $ConvergenceWorkRoot "checkpoints") -Label "Fidelity convergence checkpoint directory"
    $checkpoints = @(Get-ChildItem -LiteralPath $checkpointDir -Filter "checkpoint-*.json" -File | Sort-Object Name -Descending)
    if ($checkpoints.Count -lt 1) { throw "Convergence work root contains no verified checkpoint." }
    $latestCheckpoint = $checkpoints[0].FullName
    [void](Invoke-CheckoutPython -CheckoutRoot $repoRoot -Arguments @("-m","bodyrig.fidelity_checkpoint_verify_cli","--checkpoint",$latestCheckpoint,"--work-root",$ConvergenceWorkRoot) -Step "Convergence checkpoint verification")
    try { $checkpoint = Get-Content -LiteralPath $latestCheckpoint -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60 }
    catch { throw "Latest convergence checkpoint is unreadable." }
    $checkpointRevision = Need-Revision -Value ([string]$checkpoint.bodyrig_revision) -Label "checkpoint bodyrig_revision"
    if (-not (Test-CommitExists -Root $repoRoot -Revision $checkpointRevision)) {
        throw "Convergence checkpoint BodyRig revision $checkpointRevision cannot be resolved in this checkout."
    }
    if (-not (Test-IsAncestor -Root $repoRoot -Ancestor $safeSourceFloorRevision -Descendant $checkpointRevision)) {
        throw "Convergence checkpoint revision $checkpointRevision predates or is outside safe-source floor $safeSourceFloorRevision; historical/pre-projection-safety evidence cannot be rebound."
    }
    $relativeBaseline = ([string]$checkpoint.state.current_baseline_clone_output).Replace('/',[IO.Path]::DirectorySeparatorChar)
    $BaselineCloneOutput = [IO.Path]::GetFullPath((Join-Path $ConvergenceWorkRoot $relativeBaseline))
    $IdentityWorkspace = [IO.Path]::GetFullPath([string]$checkpoint.state.current_identity_workspace)
    $checkpointBodyId = [string]$checkpoint.body_alias
    $checkpointName = [string]$checkpoint.state.effective_name
} else {
    $checkpointBodyId = ""
    $checkpointName = ""
}

$BaselineCloneOutput = Need-Directory -Path $BaselineCloneOutput -Label "Baseline clone output"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$cloneDir = Need-Directory -Path (Join-Path $BaselineCloneOutput "clone") -Label "Baseline portable clone directory"
$proof = Need-File -Path (Join-Path $cloneDir "bodyrig-recovery-proof.json") -Label "Baseline recovery proof"
$identity = Need-File -Path (Join-Path $cloneDir "bodyrig-visual-identity.json") -Label "Baseline visual identity"
$portableIdentity = Need-File -Path (Join-Path $cloneDir "bodyrig-portable-identity.json") -Label "Baseline portable identity"
$fitterConfig = Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-sith-fitter-config.json") -Label "Baseline SiTH fitter config"
$stage = Need-Directory -Path (Join-Path $IdentityWorkspace "sith-input-v1") -Label "Retained SiTH reconstruction stage"
$reconstruction = Need-File -Path (Join-Path $stage "reconstruction.json") -Label "Retained SiTH reconstruction evidence"
$reconstructionAuthority = Need-File -Path (Join-Path $stage "reconstruction-authority.json") -Label "Retained SiTH reconstruction authority"

try { $portable = Get-Content -LiteralPath $portableIdentity -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Baseline portable identity is unreadable." }
$bodyId = ([string]$portable.requested_alias).Trim()
if ($bodyId -notmatch '^[a-z0-9æøå_-]{1,160}$') { throw "Portable identity requested alias is invalid." }
if (-not [string]::IsNullOrWhiteSpace($checkpointBodyId) -and $checkpointBodyId -ne $bodyId) { throw "Convergence checkpoint body alias differs from portable identity." }
$sourcePackage = Need-File -Path (Join-Path $cloneDir "$bodyId.mrbody") -Label "Baseline source package"
$sourceAuthority = Get-PackageAuthority -Package $sourcePackage -CheckoutRoot $repoRoot
$name = ([string]$sourceAuthority.name).Trim()
if (-not [string]::IsNullOrWhiteSpace($checkpointName) -and $checkpointName -ne $name) { throw "Convergence checkpoint display name differs from baseline package." }
if ([string]::IsNullOrWhiteSpace($name) -or $name.Length -gt 160) { throw "Baseline package display name is invalid." }

try { $reconAuthority = Get-Content -LiteralPath $reconstructionAuthority -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Retained reconstruction authority is unreadable." }
$bodyModelGender = ([string]$reconAuthority.body_model_gender).Trim().ToLowerInvariant()
if ($bodyModelGender -notin @("female","male","neutral")) { throw "Retained reconstruction authority has invalid SMPL-X gender." }

if ([string]::IsNullOrWhiteSpace($RigSetupReport)) { $RigSetupReport = [string]$env:BODYRIG_RIG_SETUP_REPORT }
if ([string]::IsNullOrWhiteSpace($RigSetupReport) -and -not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $candidateRig = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json"
    if (Test-Path -LiteralPath $candidateRig -PathType Leaf) { $RigSetupReport = $candidateRig }
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport)) { throw "BodyRig rig setup report is required." }
$RigSetupReport = Need-File -Path $RigSetupReport -Label "BodyRig rig setup report"
[void](Invoke-CheckoutPython -CheckoutRoot $repoRoot -Arguments @("-m","bodyrig.rig_setup",$RigSetupReport) -Step "Rig setup validation")
try { $rig = Get-Content -LiteralPath $RigSetupReport -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
catch { throw "Rig setup report is unreadable." }
$sithSetupReport = Need-File -Path ([string]$rig.high_fidelity.setup_report) -Label "SiTH setup report"
[void](Invoke-CheckoutPython -CheckoutRoot $repoRoot -Arguments @("-m","bodyrig.sith_setup",$sithSetupReport) -Step "SiTH setup validation")
try { $sith = Get-Content -LiteralPath $sithSetupReport -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
catch { throw "SiTH setup report is unreadable." }
$reconCheckpointSha = Need-Sha256 ([string]$sith.checkpoints.recon_model.sha256) "reconstruction checkpoint SHA-256"
$smplxCheckpointSha = Need-Sha256 ([string]$sith.checkpoints.smplerx.sha256) "SMPL-X checkpoint SHA-256"

$artifactBase = [string]$env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($artifactBase)) { $artifactBase = [IO.Path]::GetTempPath() }
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $OutputDir = Join-Path $artifactBase "BodyRig\pbr-ab\$bodyId-$stamp"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "PBR A/B output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) { New-Item -ItemType Directory -Path $outputParent -Force | Out-Null }
New-Item -ItemType Directory -Path $OutputDir | Out-Null
$baselineDir = Join-Path $OutputDir "baseline"
$candidateDir = Join-Path $OutputDir "candidate"
New-Item -ItemType Directory -Path $baselineDir,$candidateDir | Out-Null
$baselinePackage = Join-Path $baselineDir "$bodyId.mrbody"
$candidatePackage = Join-Path $candidateDir "$bodyId.mrbody"
$abEvidence = Join-Path $OutputDir "machine-ab.json"
$baselineRender = Join-Path $OutputDir "baseline-render"
$candidateRender = Join-Path $OutputDir "candidate-render"
$runAuthorityPath = Join-Path $OutputDir "run-authority.json"
$reviewPath = Join-Path $OutputDir "human-review.json"

$worktreeBase = Join-Path ([IO.Path]::GetTempPath()) "BodyRig-pbr-ab-worktrees"
if (-not (Test-Path -LiteralPath $worktreeBase -PathType Container)) { New-Item -ItemType Directory -Path $worktreeBase -Force | Out-Null }
$candidateWorktree = Join-Path $worktreeBase ("candidate-" + [Guid]::NewGuid().ToString("N"))
$candidateWorktreeAdded = $false

$oldRecon = [string]$env:BODYRIG_SITH_RECON_CHECKPOINT_SHA256
$oldSmplx = [string]$env:BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256
$oldGender = [string]$env:BODYRIG_SITH_BODY_MODEL_GENDER
try {
    $env:BODYRIG_SITH_RECON_CHECKPOINT_SHA256 = $reconCheckpointSha
    $env:BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256 = $smplxCheckpointSha
    $env:BODYRIG_SITH_BODY_MODEL_GENDER = $bodyModelGender

    [void](Invoke-Git -Arguments @("-C",$repoRoot,"worktree","add","--detach",$candidateWorktree,$candidateRevision) -Step "Create exact candidate worktree")
    $candidateWorktreeAdded = $true
    Assert-CleanCheckout -Root $candidateWorktree -ExpectedRevision $candidateRevision -Label "Candidate"

    $validateAuthorityCode = @'
import json,sys
from bodyrig.sith_reconstruction_authority import validate_reconstruction_authority
print(json.dumps(validate_reconstruction_authority(sys.argv[1],expected_body_model_gender=sys.argv[2]),separators=(",",":")))
'@
    [void](Invoke-CheckoutPython -CheckoutRoot $repoRoot -Arguments @("-c",$validateAuthorityCode,$IdentityWorkspace,$bodyModelGender) -Step "Baseline reconstruction resume authority")
    [void](Invoke-CheckoutPython -CheckoutRoot $candidateWorktree -Arguments @("-c",$validateAuthorityCode,$IdentityWorkspace,$bodyModelGender) -Step "Candidate reconstruction resume authority")

    $treeBefore = Get-TreeDigest -Root $stage
    $reconstructionShaBefore = (Get-FileHash -LiteralPath $reconstruction -Algorithm SHA256).Hash.ToLowerInvariant()
    $reconstructionAuthorityShaBefore = (Get-FileHash -LiteralPath $reconstructionAuthority -Algorithm SHA256).Hash.ToLowerInvariant()

    Write-Host "BodyRig PBR A/B | retained reconstruction"
    Write-Host "Body:       $name | alias=$bodyId"
    Write-Host "Baseline:   $baselineRevision"
    Write-Host "Candidate:  $candidateRevision ($CandidateRef)"
    Write-Host "SMPL-X:     $bodyModelGender"
    Write-Host "Workspace:  $IdentityWorkspace"
    if ($usingConvergence) { Write-Host "Source floor: $safeSourceFloorRevision | checkpoint=$checkpointRevision" }
    else { Write-Host "Source mode:  explicit expert/recovery workspace; no checkpoint ancestry authority claimed" }
    Write-Host "Tree SHA:   $([string]$treeBefore.sha256) | files=$([int]$treeBefore.file_count) | bytes=$([int64]$treeBefore.byte_count)"
    Write-Host ""

    [void](Invoke-CheckoutPython -CheckoutRoot $repoRoot -Arguments @(
        "-m","bodyrig.external_fitter_cli",
        $proof,
        "--identity-profile",$identity,
        "--identity-workspace",$IdentityWorkspace,
        "--config",$fitterConfig,
        "--body-id",$bodyId,
        "--portable-identity",$portableIdentity,
        "--name",$name,
        "--out",$baselinePackage
    ) -Step "Build exact baseline package from retained reconstruction")
    $treeAfterBaseline = Get-TreeDigest -Root $stage
    if ([string]$treeAfterBaseline.sha256 -ne [string]$treeBefore.sha256) { throw "Retained SiTH tree changed during baseline package build." }
    Assert-CleanCheckout -Root $repoRoot -ExpectedRevision $baselineRevision -Label "Baseline"
    $baselineAuthority = Get-PackageAuthority -Package $baselinePackage -CheckoutRoot $repoRoot
    if ([string]$baselineAuthority.builder_revision -ne $baselineRevision) { throw "Baseline package is not builder-bound to exact baseline revision." }

    [void](Invoke-CheckoutPython -CheckoutRoot $candidateWorktree -Arguments @(
        "-m","bodyrig.external_fitter_cli",
        $proof,
        "--identity-profile",$identity,
        "--identity-workspace",$IdentityWorkspace,
        "--config",$fitterConfig,
        "--body-id",$bodyId,
        "--portable-identity",$portableIdentity,
        "--name",$name,
        "--out",$candidatePackage
    ) -Step "Build exact PBR-v2 candidate package from retained reconstruction")
    $treeAfterCandidate = Get-TreeDigest -Root $stage
    if ([string]$treeAfterCandidate.sha256 -ne [string]$treeBefore.sha256) { throw "Retained SiTH tree changed during candidate package build." }
    Assert-CleanCheckout -Root $candidateWorktree -ExpectedRevision $candidateRevision -Label "Candidate"
    $candidateAuthority = Get-PackageAuthority -Package $candidatePackage -CheckoutRoot $repoRoot
    if ([string]$candidateAuthority.builder_revision -ne $candidateRevision) { throw "Candidate package is not builder-bound to exact candidate revision." }
    if ([string]$baselineAuthority.body_id -ne [string]$candidateAuthority.body_id) { throw "Baseline/candidate package body ids differ." }

    $compare = Need-File -Path (Join-Path $repoRoot "compare-fidelity-ab.ps1") -Label "Revision-bound A/B launcher"
    & $compare -LeftPackage $baselinePackage -RightPackage $candidatePackage -Output $abEvidence `
        -ExpectedLeftBuilderRevision $baselineRevision -ExpectedRightBuilderRevision $candidateRevision -BodyRigPython $BodyRigPython
    if ($LASTEXITCODE -ne 0) { throw "Revision-bound clean appearance A/B failed." }

    $renderer = Need-File -Path (Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1") -Label "Canonical Windows fidelity renderer"
    $renderArgs = @{ PackagePath = $baselinePackage; OutputDir = $baselineRender; BodyRigPython = $BodyRigPython }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $renderArgs.UnityExe = $UnityExe }
    & $renderer @renderArgs
    if ($LASTEXITCODE -ne 0) { throw "Baseline fidelity render failed." }
    $renderArgs = @{ PackagePath = $candidatePackage; OutputDir = $candidateRender; BodyRigPython = $BodyRigPython; SkipBuild = $true }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $renderArgs.UnityExe = $UnityExe }
    & $renderer @renderArgs
    if ($LASTEXITCODE -ne 0) { throw "Candidate fidelity render failed." }

    Assert-CleanCheckout -Root $repoRoot -ExpectedRevision $baselineRevision -Label "Baseline"
    Assert-CleanCheckout -Root $candidateWorktree -ExpectedRevision $candidateRevision -Label "Candidate"
    $treeFinal = Get-TreeDigest -Root $stage
    if ([string]$treeFinal.sha256 -ne [string]$treeBefore.sha256) { throw "Retained SiTH tree changed after A/B render preparation." }
    if ((Get-FileHash -LiteralPath $reconstruction -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reconstructionShaBefore) { throw "reconstruction.json changed during PBR A/B." }
    if ((Get-FileHash -LiteralPath $reconstructionAuthority -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reconstructionAuthorityShaBefore) { throw "reconstruction-authority.json changed during PBR A/B." }

    [void](Invoke-Git -Arguments @("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs -Step "Recheck remote refs after A/B")
    $finalRemoteMain = Need-Revision ((Invoke-Git -Arguments @("-C",$repoRoot,"rev-parse","refs/remotes/origin/main") -Step "Recheck origin/main") -join "") "final origin/main"
    $finalCandidate = Need-Revision ((Invoke-Git -Arguments @("-C",$repoRoot,"rev-parse","refs/remotes/origin/$CandidateRef") -Step "Recheck candidate ref") -join "") "final candidate revision"
    if ($finalRemoteMain -ne $baselineRevision -or $finalCandidate -ne $candidateRevision) {
        throw "Baseline or candidate remote ref moved during the A/B run; refusing terminal authority."
    }

    $leftComparison = Need-File -Path (Join-Path $baselineRender "comparison-authority.json") -Label "Baseline render authority"
    $rightComparison = Need-File -Path (Join-Path $candidateRender "comparison-authority.json") -Label "Candidate render authority"
    $leftRenderSet = Need-File -Path (Join-Path $baselineRender "snapshots\fidelity-render-set.json") -Label "Baseline render set"
    $rightRenderSet = Need-File -Path (Join-Path $candidateRender "snapshots\fidelity-render-set.json") -Label "Candidate render set"
    $runAuthority = [ordered]@{
        format = "bodyrig-pbr-ab-run"
        version = 1
        body_alias = $bodyId
        display_name = $name
        candidate_ref = $CandidateRef
        baseline_revision = $baselineRevision
        candidate_revision = $candidateRevision
        renderer_revision = $baselineRevision
        baseline_package_sha256 = Need-Sha256 ([string]$baselineAuthority.package_sha256) "baseline package SHA-256"
        candidate_package_sha256 = Need-Sha256 ([string]$candidateAuthority.package_sha256) "candidate package SHA-256"
        machine_ab_sha256 = (Get-FileHash -LiteralPath $abEvidence -Algorithm SHA256).Hash.ToLowerInvariant()
        baseline_render_authority_sha256 = (Get-FileHash -LiteralPath $leftComparison -Algorithm SHA256).Hash.ToLowerInvariant()
        candidate_render_authority_sha256 = (Get-FileHash -LiteralPath $rightComparison -Algorithm SHA256).Hash.ToLowerInvariant()
        baseline_render_set_sha256 = (Get-FileHash -LiteralPath $leftRenderSet -Algorithm SHA256).Hash.ToLowerInvariant()
        candidate_render_set_sha256 = (Get-FileHash -LiteralPath $rightRenderSet -Algorithm SHA256).Hash.ToLowerInvariant()
        retained_sith_tree_sha256 = Need-Sha256 ([string]$treeBefore.sha256) "retained SiTH tree SHA-256"
        retained_sith_file_count = [int]$treeBefore.file_count
        retained_sith_byte_count = [int64]$treeBefore.byte_count
        reconstruction_sha256 = $reconstructionShaBefore
        reconstruction_authority_sha256 = $reconstructionAuthorityShaBefore
        body_model_gender = $bodyModelGender
        retained_reconstruction_reused = $true
        retained_reconstruction_unchanged = $true
        retained_source_mode = $(if ($usingConvergence) { "verified-safe-convergence" } else { "explicit-expert-recovery" })
        retained_source_policy_sha256 = $(if ($usingConvergence) { Need-Sha256 $sourcePolicySha256 "retained source policy SHA-256" } else { $null })
        safe_source_floor_revision = $(if ($usingConvergence) { $safeSourceFloorRevision } else { $null })
        retained_checkpoint_revision = $(if ($usingConvergence) { $checkpointRevision } else { $null })
        clean_appearance_ab_passed = $true
        human_visual_review_required = $true
        comparison_only = $true
        physical_acceptance_authority = $false
        production_activation = $false
    }
    Write-CreateOnlyJson -Path $runAuthorityPath -Value $runAuthority

    $views = @("front-full","three-quarter-full","side-full","face-front")
    $rows = foreach ($view in $views) {
        "<tr><td>$view</td><td><img src='baseline-render/snapshots/$view.png'></td><td><img src='candidate-render/snapshots/$view.png'></td></tr>"
    }
    $html = @"
<!doctype html><html><head><meta charset="utf-8"><title>BodyRig PBR A/B</title><style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#111;color:#eee}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #444;vertical-align:top}img{width:100%;max-width:720px;height:auto}code{word-break:break-all}</style></head><body><h1>BodyRig PBR A/B</h1><p>LEFT = baseline <code>$baselineRevision</code><br>RIGHT = candidate <code>$candidateRevision</code></p><p>Machine gate: PASS. Human visual preference is still required. This page grants no acceptance or production authority.</p><table><tr><th>View</th><th>LEFT · baseline</th><th>RIGHT · candidate</th></tr>$($rows -join "`n")</table></body></html>
"@
    $html | Set-Content -LiteralPath (Join-Path $OutputDir "review.html") -Encoding UTF8

    $reviewCommand = @"
Review all four LEFT/RIGHT views in review.html, then run ONE of these from the current main checkout:

Candidate wins:
.\record-fidelity-ab-review.ps1 -AbEvidence "$abEvidence" -LeftRenderDir "$baselineRender" -RightRenderDir "$candidateRender" -Decision right -QualityNote "<what is visibly better and any remaining defect>" -ConfirmVisualReview -Output "$reviewPath"

Baseline wins:
.\record-fidelity-ab-review.ps1 -AbEvidence "$abEvidence" -LeftRenderDir "$baselineRender" -RightRenderDir "$candidateRender" -Decision left -QualityNote "<why baseline is visibly better>" -ConfirmVisualReview -Output "$reviewPath"

No reliable difference:
.\record-fidelity-ab-review.ps1 -AbEvidence "$abEvidence" -LeftRenderDir "$baselineRender" -RightRenderDir "$candidateRender" -Decision tie -QualityNote "<what appears equivalent>" -ConfirmVisualReview -Output "$reviewPath"

Both unacceptable:
.\record-fidelity-ab-review.ps1 -AbEvidence "$abEvidence" -LeftRenderDir "$baselineRender" -RightRenderDir "$candidateRender" -Decision reject-both -QualityNote "<what remains unacceptable>" -ConfirmVisualReview -Output "$reviewPath"
"@
    $reviewCommand | Set-Content -LiteralPath (Join-Path $OutputDir "REVIEW-NEXT.txt") -Encoding UTF8

    Write-Host ""
    Write-Host "BodyRig PBR A/B preparation: PASS"
    Write-Host "Baseline package:  $baselinePackage"
    Write-Host "Candidate package: $candidatePackage"
    Write-Host "Machine A/B:       $abEvidence"
    Write-Host "Review page:       $(Join-Path $OutputDir 'review.html')"
    Write-Host "Next commands:     $(Join-Path $OutputDir 'REVIEW-NEXT.txt')"
    Write-Host "Run authority:     $runAuthorityPath"
    Write-Host "Reconstruction:    reused unchanged; no recovery/source selection/full reconstruction rerun"
    Write-Host "Authority:         comparison-only; human visual decision still required"
} finally {
    if ($candidateWorktreeAdded -and (Test-Path -LiteralPath $candidateWorktree -PathType Container)) {
        try { [void](Invoke-Git -Arguments @("-C",$repoRoot,"worktree","remove","--force",$candidateWorktree) -Step "Remove candidate worktree") }
        catch { Write-Warning "Could not remove temporary candidate worktree: $($_.Exception.Message)" }
    }
    if ([string]::IsNullOrEmpty($oldRecon)) { Remove-Item Env:BODYRIG_SITH_RECON_CHECKPOINT_SHA256 -ErrorAction SilentlyContinue } else { $env:BODYRIG_SITH_RECON_CHECKPOINT_SHA256 = $oldRecon }
    if ([string]::IsNullOrEmpty($oldSmplx)) { Remove-Item Env:BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256 -ErrorAction SilentlyContinue } else { $env:BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256 = $oldSmplx }
    if ([string]::IsNullOrEmpty($oldGender)) { Remove-Item Env:BODYRIG_SITH_BODY_MODEL_GENDER -ErrorAction SilentlyContinue } else { $env:BODYRIG_SITH_BODY_MODEL_GENDER = $oldGender }
}

exit 0
