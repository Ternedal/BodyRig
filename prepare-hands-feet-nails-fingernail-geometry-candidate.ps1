param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$PersonId,
    [Parameter(Mandatory=$true)][string]$BodyRevision,
    [Parameter(Mandatory=$true)][string]$CaptureId,
    [Parameter(Mandatory=$true)][string]$CandidateId,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = "python" }
}

$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git revision."
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -gt 0) {
    throw "HFN fingernail geometry preparation requires a clean BodyRig checkout."
}

& $BodyRigPython -m bodyrig.hands_feet_nails_fingernail_geometry_candidate_cli `
    --root $Root `
    --person-id $PersonId `
    --body-revision $BodyRevision `
    --capture-id $CaptureId `
    --candidate-id $CandidateId `
    --bodyrig-revision $head

if ($LASTEXITCODE -ne 0) {
    throw "BodyRig HFN fingernail geometry candidate preparation failed."
}
