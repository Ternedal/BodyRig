param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$PersonId,
    [Parameter(Mandatory=$true)][string]$BodyRevision,
    [Parameter(Mandatory=$true)][string]$CaptureId,
    [Parameter(Mandatory=$true)][string]$CandidateId,
    [Parameter(Mandatory=$true)][string]$RenderDir,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [Parameter(Mandatory=$true)][switch]$ConfirmDetailChecklist,
    [Parameter(Mandatory=$true)][string]$QualityNote,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = "python" }
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -gt 0) { throw "HFN human review requires a clean BodyRig checkout." }
$head = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git revision."
}

$note = $QualityNote.Trim()
if (-not $note -or $note -match '^<[^>]+>$') {
    throw "HFN human review requires your real quality note, not a placeholder."
}
$renderRoot = (Resolve-Path -LiteralPath $RenderDir -ErrorAction Stop).Path
$renderManifest = Join-Path (Join-Path $renderRoot "snapshots") "hands-feet-nails-render-set.json"
if (-not (Test-Path -LiteralPath $renderManifest -PathType Leaf)) {
    throw "Canonical HFN render manifest is missing: $renderManifest"
}

& $BodyRigPython -m bodyrig.high_fidelity_hfn_review_cli `
    --output-dir $OutputDir `
    --root $Root `
    --person-id $PersonId `
    --body-revision $BodyRevision `
    --capture-id $CaptureId `
    --candidate-id $CandidateId `
    --render-manifest $renderManifest `
    --bodyrig-revision $head `
    --quality-note $note `
    --confirm-detail-checklist

if ($LASTEXITCODE -ne 0) {
    throw "BodyRig HFN human-review recording failed."
}
