param(
    [Parameter(Mandatory = $true)][string]$BaselineCloneOutput,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$SubjectRefitDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [ValidatePattern('^$|^[a-z0-9æøå_-]{1,160}$')][string]$BodyId = "",
    [Parameter(Mandatory = $true)][ValidateLength(1, 160)][string]$Name,
    [string]$BodyRigPython = ""
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
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$Executable,[Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Step)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}
function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Output already exists: $Path" }
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig subject anatomy candidate build is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Subject anatomy candidate build requires an exact clean BodyRig checkout." }

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
$BaselineCloneOutput = Need-Directory -Path $BaselineCloneOutput -Label "Baseline clone output"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$SubjectRefitDir = Need-Directory -Path $SubjectRefitDir -Label "Subject anatomy refit directory"
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Subject anatomy candidate output already exists: $OutputDir" }
New-Item -ItemType Directory -Path $OutputDir | Out-Null

$cloneDir = Need-Directory -Path (Join-Path $BaselineCloneOutput "clone") -Label "Baseline portable clone directory"
$proof = Need-File -Path (Join-Path $cloneDir "bodyrig-recovery-proof.json") -Label "Baseline recovery proof"
$identity = Need-File -Path (Join-Path $cloneDir "bodyrig-visual-identity.json") -Label "Baseline visual identity"
$portableIdentity = Need-File -Path (Join-Path $cloneDir "bodyrig-portable-identity.json") -Label "Baseline portable identity"
$fitterConfig = Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-sith-fitter-config.json") -Label "Baseline SiTH fitter config"
$reconstruction = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\reconstruction.json") -Label "Retained reconstruction authority"
$sourceMesh = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\meshes\000_reco.obj") -Label "Retained source mesh"
$refitEvidence = Need-File -Path (Join-Path $SubjectRefitDir "subject-anatomy-refit.json") -Label "Subject anatomy refit evidence"

try { $portableReceipt = Get-Content -LiteralPath $portableIdentity -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Baseline portable identity is unreadable." }
$portableAlias = ([string]$portableReceipt.requested_alias).Trim()
if ($portableAlias -notmatch '^[a-z0-9æøå_-]{1,160}$') { throw "Baseline portable identity requested_alias is invalid." }
if ([string]::IsNullOrWhiteSpace($BodyId)) {
    $BodyId = $portableAlias
} elseif ($BodyId -ne $portableAlias) {
    throw "Requested BodyId '$BodyId' conflicts with portable identity alias '$portableAlias'. Omit -BodyId to reuse canonical alias."
}

$reconstructionShaBefore = Sha256 $reconstruction
$sourceMeshShaBefore = Sha256 $sourceMesh
$refitEvidenceSha = Sha256 $refitEvidence
$workspace = Join-Path $OutputDir "candidate-workspace"

Write-Host "BodyRig subject anatomy candidate"
Write-Host "Revision:       $head"
Write-Host "Alias:          $BodyId (portable identity authority)"
Write-Host "Reconstruction: $reconstructionShaBefore"
Write-Host "Source mesh:    $sourceMeshShaBefore"
Write-Host "Refit evidence: $refitEvidenceSha"
Write-Host "BodyPrint:      UNCHANGED"
Write-Host "SiTH rerun:     FALSE"
Write-Host "Production:     FALSE"
Write-Host ""

Invoke-Checked -Executable $BodyRigPython -Arguments @(
    "-m", "bodyrig.subject_anatomy_workspace",
    "--retained-workspace", $IdentityWorkspace,
    "--refit-dir", $SubjectRefitDir,
    "--output-workspace", $workspace
) -Step "Stage comparison-only subject anatomy workspace"

$workspaceReceipt = Need-File -Path (Join-Path $workspace "subject-anatomy-workspace.json") -Label "Subject anatomy workspace receipt"
try { $workspaceEvidence = Get-Content -LiteralPath $workspaceReceipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Subject anatomy workspace receipt is unreadable." }
if ([string]$workspaceEvidence.parentReconstructionSha256 -ne $reconstructionShaBefore -or
    [string]$workspaceEvidence.subjectAnatomyRefitSha256 -ne $refitEvidenceSha -or
    $workspaceEvidence.retainedSourceAppearanceBytesPreserved -ne $true -or
    $workspaceEvidence.reconstructionRerun -ne $false -or
    $workspaceEvidence.comparisonOnly -ne $true -or
    $workspaceEvidence.productionReady -ne $false) {
    throw "Subject anatomy workspace receipt violates the retained-authority boundary."
}

$packagePath = Join-Path $OutputDir "$BodyId.mrbody"
Invoke-Checked -Executable $BodyRigPython -Arguments @(
    "-m", "bodyrig.external_fitter_cli",
    $proof,
    "--identity-profile", $identity,
    "--identity-workspace", $workspace,
    "--config", $fitterConfig,
    "--body-id", $BodyId,
    "--portable-identity", $portableIdentity,
    "--subject-anatomy-refit", $refitEvidence,
    "--name", $Name,
    "--out", $packagePath
) -Step "Fit and package subject anatomy candidate"

if ((Sha256 $reconstruction) -ne $reconstructionShaBefore -or (Sha256 $sourceMesh) -ne $sourceMeshShaBefore) {
    throw "Retained reconstruction/source bytes changed during subject anatomy candidate build."
}

$validationCode = "import hashlib,json,pathlib,sys; from bodyrig.package import validate_package; p=pathlib.Path(sys.argv[1]).resolve(); v=validate_package(p); print(json.dumps({'body_id':v.manifest['id'],'package_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'pipeline':v.provenance['pipeline']},separators=(',',':')))"
$validationRaw = @(& $BodyRigPython -c $validationCode $packagePath)
if ($LASTEXITCODE -ne 0 -or $validationRaw.Count -ne 1) { throw "Subject anatomy package failed strict validation." }
try { $validated = ([string]$validationRaw[0]) | ConvertFrom-Json }
catch { throw "Subject anatomy package validator returned unreadable JSON." }
$anatomyStages = @($validated.pipeline | Where-Object { [string]$_.stage -eq "subject-anatomy-refit" })
$adjustmentStages = @($validated.pipeline | Where-Object { [string]$_.stage -eq "bodyprint-adjustment" })
if ($anatomyStages.Count -ne 1) { throw "Subject anatomy package does not contain exactly one refit provenance stage." }
if ([string]$anatomyStages[0].revision -ne $refitEvidenceSha) { throw "Subject anatomy package provenance does not bind the refit evidence bytes." }
if ($adjustmentStages.Count -ne 0) { throw "Subject anatomy comparison unexpectedly contains a BodyPrint adjustment stage." }

$result = [ordered]@{
    format = "bodyrig-subject-anatomy-candidate-result"
    version = 1
    bodyrig_revision = $head
    mode = "derived-smplx-shape-on-retained-sith-source"
    requested_alias = $BodyId
    package = [IO.Path]::GetFileName($packagePath)
    package_sha256 = [string]$validated.package_sha256
    canonical_body_id = [string]$validated.body_id
    parent_reconstruction_sha256 = $reconstructionShaBefore
    retained_source_mesh_sha256 = $sourceMeshShaBefore
    subject_anatomy_refit_sha256 = $refitEvidenceSha
    candidate_reconstruction_sha256 = [string]$workspaceEvidence.candidateReconstructionSha256
    bodyprint_adjustment = $false
    expensive_reconstruction_rerun = $false
    comparison_only = $true
    human_review_required = $true
    production_activation = $false
}
$resultPath = Join-Path $OutputDir "subject-anatomy-candidate-result.json"
Write-CreateOnlyJson -Path $resultPath -Value $result

Write-Host ""
Write-Host "BodyRig subject anatomy candidate: PASS"
Write-Host "Package:        $packagePath"
Write-Host "Package SHA:    $([string]$validated.package_sha256)"
Write-Host "Canonical body: $([string]$validated.body_id)"
Write-Host "Alias:          $BodyId"
Write-Host "Reconstruction: reused unchanged ($reconstructionShaBefore)"
Write-Host "Source mesh:    reused unchanged ($sourceMeshShaBefore)"
Write-Host "BodyPrint:      adjustment FALSE"
Write-Host "Authority:      comparison-only; human review required; production FALSE"
exit 0
