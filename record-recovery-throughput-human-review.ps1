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

$BundleDir = (Resolve-Path -LiteralPath $BundleDir).Path
if (-not (Test-Path -LiteralPath (Join-Path $BundleDir "review-bundle.json") -PathType Leaf)) {
    throw "BodyRig recovery throughput review bundle receipt not found: $BundleDir"
}
if (-not (Test-Path -LiteralPath (Join-Path $BundleDir "machine-audit.json") -PathType Leaf)) {
    throw "BodyRig recovery throughput machine audit not found: $BundleDir"
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
Write-Host "Shape:     $IdentityShape"
Write-Host "Face:      $FaceIdentity"
Write-Host "Texture:   $SkinTextureAlignment"
Write-Host "Anatomy:   $GrossAnatomy"
Write-Host "Output:    $Out"
Write-Host "This records human evidence only; it cannot promote or activate anything."

& $python -m bodyrig.recovery_throughput_human_review `
    $BundleDir `
    --out $Out `
    --reviewer $Reviewer `
    --identity-shape $IdentityShape `
    --face-identity $FaceIdentity `
    --skin-texture-alignment $SkinTextureAlignment `
    --gross-anatomy $GrossAnatomy `
    --note $Note
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "BodyRig recovery throughput human review: RECORDED"
Write-Host "Receipt:   $Out"
Write-Host "Authority: human evidence only; promotion/production remain false."
exit 0
