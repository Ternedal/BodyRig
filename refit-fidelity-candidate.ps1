param(
    [Parameter(Mandatory = $true)][string]$BaselineCloneOutput,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$AdjustmentRequest,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9æøå_-]{1,160}$')][string]$BodyId,
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
    throw "BodyRig fidelity refit is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Fidelity refit requires an exact clean BodyRig checkout." }

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
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Baseline identity workspace"
$AdjustmentRequest = Need-File -Path $AdjustmentRequest -Label "Bounded adjustment request"
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Refit output already exists: $OutputDir" }
New-Item -ItemType Directory -Path $OutputDir | Out-Null

$cloneDir = Need-Directory -Path (Join-Path $BaselineCloneOutput "clone") -Label "Baseline portable clone directory"
$proof = Need-File -Path (Join-Path $cloneDir "bodyrig-recovery-proof.json") -Label "Baseline recovery proof"
$identity = Need-File -Path (Join-Path $cloneDir "bodyrig-visual-identity.json") -Label "Baseline visual identity"
$portableIdentity = Need-File -Path (Join-Path $cloneDir "bodyrig-portable-identity.json") -Label "Baseline portable identity"
$fitterConfig = Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-sith-fitter-config.json") -Label "Baseline SiTH fitter config"
$reconstruction = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\reconstruction.json") -Label "Baseline SiTH reconstruction authority"
$reconstructionShaBefore = Sha256 $reconstruction
$proofSha = Sha256 $proof

$adjustmentEvidence = Join-Path $OutputDir "bodyrig-bodyprint-adjustment.json"
Invoke-Checked -Executable $BodyRigPython -Arguments @(
    "-m", "bodyrig.bodyprint_adjustment", "bind",
    $AdjustmentRequest,
    $proof,
    "--out", $adjustmentEvidence
) -Step "Bind bounded adjustment to baseline proof"

$packagePath = Join-Path $OutputDir "$BodyId.mrbody"
Invoke-Checked -Executable $BodyRigPython -Arguments @(
    "-m", "bodyrig.external_fitter_cli",
    $proof,
    "--identity-profile", $identity,
    "--identity-workspace", $IdentityWorkspace,
    "--config", $fitterConfig,
    "--body-id", $BodyId,
    "--portable-identity", $portableIdentity,
    "--bodyprint-adjustment", $adjustmentEvidence,
    "--name", $Name,
    "--out", $packagePath
) -Step "Resume SiTH workspace and refit candidate"

$reconstructionShaAfter = Sha256 $reconstruction
if ($reconstructionShaAfter -ne $reconstructionShaBefore) {
    throw "SiTH reconstruction authority changed during cheap fidelity refit; refusing resume claim."
}

$validationCode = "import hashlib,json,pathlib,sys; from bodyrig.package import validate_package; p=pathlib.Path(sys.argv[1]).resolve(); v=validate_package(p); print(json.dumps({'body_id':v.manifest['id'],'package_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'pipeline':v.provenance['pipeline']},separators=(',',':')))"
$validationRaw = @(& $BodyRigPython -c $validationCode $packagePath)
if ($LASTEXITCODE -ne 0 -or $validationRaw.Count -ne 1) { throw "Refit package failed strict validation." }
try { $validated = ([string]$validationRaw[0]) | ConvertFrom-Json }
catch { throw "Refit package validator returned unreadable JSON." }
$adjustmentStages = @($validated.pipeline | Where-Object { [string]$_.stage -eq "bodyprint-adjustment" })
if ($adjustmentStages.Count -ne 1) { throw "Refit package does not contain exactly one proof-bound bodyprint adjustment stage." }

$result = [ordered]@{
    format = "bodyrig-fidelity-refit-result"
    version = 1
    bodyrig_revision = $head
    mode = "resume-existing-sith-reconstruction"
    package = [IO.Path]::GetFileName($packagePath)
    package_sha256 = [string]$validated.package_sha256
    recovery_proof_sha256 = $proofSha
    reconstruction_authority_sha256 = $reconstructionShaBefore
    adjustment_evidence_sha256 = Sha256 $adjustmentEvidence
    expensive_reconstruction_rerun = $false
    comparison_only = $true
    production_activation = $false
}
$resultPath = Join-Path $OutputDir "refit-result.json"
Write-CreateOnlyJson -Path $resultPath -Value $result

Write-Host "BodyRig fidelity refit: PASS"
Write-Host "Package:        $packagePath"
Write-Host "Package SHA:    $([string]$validated.package_sha256)"
Write-Host "Reconstruction: reused unchanged ($reconstructionShaBefore)"
Write-Host "Authority:      comparison-only; no physical/renderer/release acceptance written"
exit 0
