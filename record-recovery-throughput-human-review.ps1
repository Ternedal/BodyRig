param(
    [Parameter(Mandatory = $true)]
    [string]$BundleDir,

    [Parameter(Mandatory = $true)]
    [ValidateSet("pass", "fail")]
    [string]$IdentityShape,

    [Parameter(Mandatory = $true)]
    [ValidateSet("pass", "fail")]
    [string]$FaceIdentity,

    [Parameter(Mandatory = $true)]
    [ValidateSet("pass", "fail")]
    [string]$SkinTextureAlignment,

    [Parameter(Mandatory = $true)]
    [ValidateSet("pass", "fail")]
    [string]$GrossAnatomy,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Note,

    [string]$Reviewer = "",
    [string]$Out = "",
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = $PSScriptRoot
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "BodyRig virtualenv Python not found: $python"
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to bind human A/B review to exact candidate software authority."
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) {
    throw "RepoRoot is not a BodyRig Git checkout: $RepoRoot"
}

$BundleDir = (Resolve-Path -LiteralPath $BundleDir).Path
$bundleReceiptPath = Join-Path $BundleDir "review-bundle.json"
if (-not (Test-Path -LiteralPath $bundleReceiptPath -PathType Leaf)) {
    throw "BodyRig recovery throughput review bundle receipt not found: $BundleDir"
}
if (-not (Test-Path -LiteralPath (Join-Path $BundleDir "machine-audit.json") -PathType Leaf)) {
    throw "BodyRig recovery throughput machine audit not found: $BundleDir"
}
try {
    $bundleReceipt = Get-Content -LiteralPath $bundleReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40
} catch {
    throw "BodyRig recovery throughput review bundle receipt is unreadable."
}
$bundleCandidateRevision = ([string]$bundleReceipt.candidate_bodyrig_revision).Trim().ToLowerInvariant()
if ($bundleCandidateRevision -notmatch '^[0-9a-f]{40}$') {
    throw "Review bundle candidate BodyRig revision is invalid."
}

$head = (& git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact candidate checkout revision for human review."
}
$dirty = @(& git -C $RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not read candidate checkout status for human review."
}
if ($dirty.Count -gt 0) {
    throw "Candidate checkout is dirty. Refusing to record revision-bound human A/B review."
}
if ($head -cne $bundleCandidateRevision) {
    throw "Current BodyRig checkout does not match the review bundle candidate revision. Expected $bundleCandidateRevision, got $head."
}

if ([string]::IsNullOrWhiteSpace($Reviewer)) {
    $Reviewer = [string]$env:USERNAME
}
if ([string]::IsNullOrWhiteSpace($Reviewer)) {
    throw "Reviewer is required. Pass -Reviewer explicitly when USERNAME is unavailable."
}
if ([string]::IsNullOrWhiteSpace($Note)) {
    throw "A human review note is required."
}

if ([string]::IsNullOrWhiteSpace($Out)) {
    $Out = "$BundleDir.human-review.json"
}
$Out = [System.IO.Path]::GetFullPath($Out)

Write-Host "BodyRig recovery throughput explicit human A/B review"
Write-Host "Bundle:    $BundleDir"
Write-Host "Reviewer:  $Reviewer"
Write-Host "Candidate software authority: $head"
Write-Host "Shape:     $IdentityShape"
Write-Host "Face:      $FaceIdentity"
Write-Host "Texture:   $SkinTextureAlignment"
Write-Host "Anatomy:   $GrossAnatomy"
Write-Host "Output:    $Out"
Write-Host "This records human evidence only; it cannot promote or activate anything."

$moduleName = "bodyrig.recovery_throughput_human_review"
$expectedModule = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\recovery_throughput_human_review.py"))
$moduleArgs = @(
    $BundleDir,
    "--out", $Out,
    "--reviewer", $Reviewer,
    "--identity-shape", $IdentityShape,
    "--face-identity", $FaceIdentity,
    "--skin-texture-alignment", $SkinTextureAlignment,
    "--gross-anatomy", $GrossAnatomy,
    "--note", $Note
)
$previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$previousNoBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
$locationPushed = $false
$moduleExitCode = 1
try {
    Push-Location -LiteralPath $RepoRoot
    $locationPushed = $true
    $boundPythonPath = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$previousPythonPath" }
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $boundPythonPath, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")

    $probeCode = "import importlib,pathlib,sys; m=importlib.import_module(sys.argv[1]); print(pathlib.Path(m.__file__).resolve())"
    $moduleRaw = @(& $python -c $probeCode $moduleName 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) {
        throw "Could not resolve checkout-bound recovery throughput human-review module."
    }
    $actualModule = [System.IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Recovery throughput human review imported BodyRig from a different checkout: $actualModule"
    }

    & $python -m $moduleName @moduleArgs
    $moduleExitCode = $LASTEXITCODE
} finally {
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $previousPythonPath, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $previousNoBytecode, "Process")
    if ($locationPushed) { Pop-Location }
}
if ($moduleExitCode -ne 0) {
    exit $moduleExitCode
}

Write-Host "BodyRig recovery throughput human review: RECORDED"
Write-Host "Receipt:   $Out"
Write-Host "Authority: human evidence only; promotion/production remain false."
exit 0
