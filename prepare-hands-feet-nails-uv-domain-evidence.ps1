param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$PersonId,
    [Parameter(Mandatory=$true)][string]$BodyRevision,
    [Parameter(Mandatory=$true)][string]$CaptureId,
    [Parameter(Mandatory=$true)][string]$LandmarkEvidence,
    [Parameter(Mandatory=$true)][string]$PackagePath,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = "python" }
}

$head = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git revision."
}

& $BodyRigPython -m bodyrig.hands_feet_nails_uv_domain_evidence_cli `
    --root $Root `
    --person-id $PersonId `
    --body-revision $BodyRevision `
    --capture-id $CaptureId `
    --landmark-evidence $LandmarkEvidence `
    --package $PackagePath `
    --bodyrig-revision $head

if ($LASTEXITCODE -ne 0) {
    throw "BodyRig HFN UV-domain evidence preparation failed."
}
