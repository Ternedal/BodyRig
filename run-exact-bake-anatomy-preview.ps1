param(
    [Parameter(Mandatory = $true)][string]$BaselineCloneOutput,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$EndpointRefitDir,
    [Parameter(Mandatory = $true)][string]$LineSearchDir,
    [Parameter(Mandatory = $true)][ValidateRange(0.000001, 0.999999)][double]$Alpha,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9æøå_-]{1,160}$')][string]$BodyId,
    [Parameter(Mandatory = $true)][ValidateLength(1, 160)][string]$Name,
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
    [switch]$SkipRendererBuild
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
function Assert-CheckoutAuthority {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$ExpectedHead = "")
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not bind exact-bake anatomy preview to BodyRig Git HEAD." }
    $head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is not canonical." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout changed during exact-bake anatomy preview; expected $ExpectedHead, got $head."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Exact-bake anatomy preview requires an exact clean BodyRig checkout." }
    return $head
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

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig exact-bake anatomy preview is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot
$repoBoundary = $repoRoot + [IO.Path]::DirectorySeparatorChar

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
$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "BodyRig Python could not prove checkout-bound import authority." }
$actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from a different checkout: $actualModule"
}

$BaselineCloneOutput = Need-Directory -Path $BaselineCloneOutput -Label "Baseline clone output"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$EndpointRefitDir = Need-Directory -Path $EndpointRefitDir -Label "V3 endpoint refit directory"
$LineSearchDir = Need-Directory -Path $LineSearchDir -Label "Exact-bake line-search directory"
$lineSearchReceipt = Need-File -Path (Join-Path $LineSearchDir "line-search.json") -Label "Exact-bake line-search receipt"
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if ([string]::Equals($OutputDir,$repoRoot,[StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($repoBoundary,[StringComparison]::OrdinalIgnoreCase)) {
    throw "Exact-bake anatomy preview output must be outside the BodyRig Git checkout."
}
if (Test-Path -LiteralPath $OutputDir) { throw "Exact-bake anatomy preview output already exists: $OutputDir" }
$parent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($parent)) { throw "Exact-bake anatomy preview output must have a parent directory." }
New-Item -ItemType Directory -Path $parent -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDir | Out-Null
$completed = $false

try {
    $cloneDir = Need-Directory -Path (Join-Path $BaselineCloneOutput "clone") -Label "Baseline portable clone directory"
    $proof = Need-File -Path (Join-Path $cloneDir "bodyrig-recovery-proof.json") -Label "Baseline recovery proof"
    $identity = Need-File -Path (Join-Path $cloneDir "bodyrig-visual-identity.json") -Label "Baseline visual identity"
    $portableIdentity = Need-File -Path (Join-Path $cloneDir "bodyrig-portable-identity.json") -Label "Baseline portable identity"
    $fitterConfig = Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-sith-fitter-config.json") -Label "Baseline SiTH fitter config"
    $retainedReconstruction = Need-File -Path (Join-Path $IdentityWorkspace "sith-input-v1\reconstruction.json") -Label "Retained reconstruction authority"
    $retainedReconstructionSha = Sha256 $retainedReconstruction

    $alphaText = $Alpha.ToString("0.####", [Globalization.CultureInfo]::InvariantCulture)
    $workspace = Join-Path $OutputDir "candidate-workspace"
    Write-Host "BodyRig exact-bake anatomy preview"
    Write-Host "Revision:       $head"
    Write-Host "Alpha:          $alphaText"
    Write-Host "Line search:    $(Sha256 $lineSearchReceipt)"
    Write-Host "Reconstruction: $retainedReconstructionSha"
    Write-Host "Mode:           comparison-only"
    Write-Host "Promotion:      FALSE"
    Write-Host "Production:     FALSE"
    Write-Host "SiTH rerun:     FALSE"
    Write-Host ""

    Invoke-Checked -Executable $BodyRigPython -Arguments @(
        "-m", "bodyrig.exact_bake_anatomy_preview",
        "--identity-workspace", $IdentityWorkspace,
        "--endpoint-refit-dir", $EndpointRefitDir,
        "--line-search-dir", $LineSearchDir,
        "--alpha", $alphaText,
        "--output-workspace", $workspace
    ) -Step "Stage exact-bake selected-alpha preview workspace"

    $workspaceReceipt = Need-File -Path (Join-Path $workspace "exact-bake-anatomy-preview-workspace.json") -Label "Exact-bake preview workspace receipt"
    try { $workspaceEvidence = Get-Content -LiteralPath $workspaceReceipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
    catch { throw "Exact-bake preview workspace receipt is unreadable." }
    if ([string]$workspaceEvidence.format -ne "bodyrig-exact-bake-anatomy-preview-workspace" -or [int]$workspaceEvidence.version -ne 1 -or
        $workspaceEvidence.comparisonOnly -ne $true -or $workspaceEvidence.humanReviewRequired -ne $true -or
        $workspaceEvidence.promotionEligible -ne $false -or $workspaceEvidence.productionReady -ne $false -or
        $workspaceEvidence.reconstructionRerun -ne $false) {
        throw "Exact-bake preview workspace crossed its comparison-only authority boundary."
    }
    if (-not [math]::IsClose([double]$workspaceEvidence.selectedAlpha,$Alpha,0.0,1e-12)) {
        throw "Exact-bake preview workspace selected a different alpha."
    }
    if ([string]$workspaceEvidence.retainedReconstructionSha256 -ne $retainedReconstructionSha) {
        throw "Exact-bake preview workspace does not bind retained reconstruction bytes."
    }

    $packageDir = Join-Path $OutputDir "candidate-package"
    New-Item -ItemType Directory -Path $packageDir | Out-Null
    $packagePath = Join-Path $packageDir "$BodyId.mrbody"
    Invoke-Checked -Executable $BodyRigPython -Arguments @(
        "-m", "bodyrig.external_fitter_cli",
        $proof,
        "--identity-profile", $identity,
        "--identity-workspace", $workspace,
        "--config", $fitterConfig,
        "--body-id", $BodyId,
        "--portable-identity", $portableIdentity,
        "--name", $Name,
        "--out", $packagePath
    ) -Step "Fit selected-alpha diagnostic package"
    $packagePath = Need-File -Path $packagePath -Label "Selected-alpha diagnostic package"

    $validationCode = "import hashlib,json,pathlib,sys; from bodyrig.package import validate_package; p=pathlib.Path(sys.argv[1]).resolve(); v=validate_package(p); print(json.dumps({'body_id':v.manifest['id'],'package_sha256':hashlib.sha256(p.read_bytes()).hexdigest()},separators=(',',':')))"
    $validationRaw = @(& $BodyRigPython -c $validationCode $packagePath)
    if ($LASTEXITCODE -ne 0 -or $validationRaw.Count -ne 1) { throw "Selected-alpha diagnostic package failed strict validation." }
    try { $validated = ([string]$validationRaw[0]) | ConvertFrom-Json }
    catch { throw "Selected-alpha package validator returned unreadable JSON." }
    if ([string]$validated.body_id -notmatch '^bodyid-[0-9a-f]{24}$') { throw "Selected-alpha package returned an invalid canonical body id." }

    if ((Sha256 $retainedReconstruction) -ne $retainedReconstructionSha) {
        throw "Retained reconstruction bytes changed while producing selected-alpha preview."
    }
    [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head)

    $renderDir = Join-Path $OutputDir "comparison-render"
    $renderScript = Need-File -Path (Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1") -Label "Fidelity Windows comparison renderer"
    $renderArgs = @{
        PackagePath = $packagePath
        OutputDir = $renderDir
        BodyRigPython = $BodyRigPython
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $renderArgs.UnityExe = $UnityExe }
    if ($SkipRendererBuild) { $renderArgs.SkipBuild = $true }
    & $renderScript @renderArgs
    if ($LASTEXITCODE -ne 0) { throw "Selected-alpha Windows comparison render failed with exit code $LASTEXITCODE." }

    $renderManifest = Need-File -Path (Join-Path $renderDir "snapshots\fidelity-render-set.json") -Label "Selected-alpha fidelity render manifest"
    [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head)
    if ((Sha256 $retainedReconstruction) -ne $retainedReconstructionSha) {
        throw "Retained reconstruction bytes changed after selected-alpha rendering."
    }

    $result = [ordered]@{
        format = "bodyrig-exact-bake-anatomy-preview-result"
        version = 1
        bodyrig_revision = $head
        selected_alpha = [double]$Alpha
        canonical_body_id = [string]$validated.body_id
        line_search_sha256 = Sha256 $lineSearchReceipt
        workspace_receipt_sha256 = Sha256 $workspaceReceipt
        package = $packagePath
        package_sha256 = [string]$validated.package_sha256
        render_manifest = $renderManifest
        render_manifest_sha256 = Sha256 $renderManifest
        reconstruction_authority_sha256 = $retainedReconstructionSha
        reconstruction_rerun = $false
        exact_production_bake_selection = $true
        comparison_only = $true
        human_review_required = $true
        promotion_eligible = $false
        production_activation = $false
    }
    $resultPath = Join-Path $OutputDir "exact-bake-anatomy-preview-result.json"
    Write-CreateOnlyJson -Path $resultPath -Value $result
    $completed = $true

    Write-Host ""
    Write-Host "BodyRig exact-bake anatomy preview: PASS"
    Write-Host "Alpha:          $alphaText"
    Write-Host "Package SHA:    $([string]$validated.package_sha256)"
    Write-Host "Snapshots:      $(Join-Path $renderDir 'snapshots')"
    Write-Host "Result:         $resultPath"
    Write-Host "Reconstruction: reused unchanged ($retainedReconstructionSha)"
    Write-Host "Authority:      comparison-only; human review required; promotion FALSE; production FALSE"
    exit 0
}
finally {
    if (-not $completed -and (Test-Path -LiteralPath $OutputDir -PathType Container)) {
        Write-Host "Exact-bake preview failed; preserving output for diagnosis: $OutputDir"
    }
}
