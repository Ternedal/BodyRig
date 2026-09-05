param(
    [Parameter(Mandatory = $true)]
    [string]$AssemblyReceipt,

    [Parameter(Mandatory = $true)]
    [string]$BodyReleaseStatus,

    [Parameter(Mandatory = $true)]
    [string]$SourceCaptureId,

    [Parameter(Mandatory = $true)]
    [string]$RenderAuthority,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmWardrobeChecklist,

    [switch]$ConfirmFootwearReview,

    [Parameter(Mandatory = $true)]
    [string]$QualityNote
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-BodyRigPython {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    $command = Get-Command python -ErrorAction Stop
    return $command.Source
}

$assemblyPath = (Resolve-Path -LiteralPath $AssemblyReceipt -ErrorAction Stop).Path
$releasePath = (Resolve-Path -LiteralPath $BodyReleaseStatus -ErrorAction Stop).Path
$renderPath = (Resolve-Path -LiteralPath $RenderAuthority -ErrorAction Stop).Path
if ([System.IO.Path]::GetFileName($renderPath) -ne "wardrobe-render-authority.json") {
    throw "Wardrobe review requires the canonical wardrobe-render-authority.json."
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -ne 0) { throw "Wardrobe authority requires a clean BodyRig checkout." }
$revision = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve canonical BodyRig checkout revision." }
$note = $QualityNote.Trim()
if (-not $note) { throw "Wardrobe authority requires a real quality note." }
if ($note -match '^<[^>]+>$') { throw "Replace the generated quality-note placeholder with your actual wardrobe review." }

$python = Resolve-BodyRigPython
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Wardrobe authority requires Python 3.11+." }
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot
    $imported = (& $python -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not import BodyRig from the operator checkout." }
    $expectedRoot = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
    $actualModule = [System.IO.Path]::GetFullPath($imported)
    if (-not $actualModule.StartsWith($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Python imported BodyRig outside the current checkout: $actualModule"
    }
    $args = @(
        "-m", "bodyrig.wardrobe_authority_cli",
        "--assembly-receipt", $assemblyPath,
        "--body-release-status", $releasePath,
        "--source-capture-id", $SourceCaptureId,
        "--render-authority", $renderPath,
        "--bodyrig-revision", $revision,
        "--confirm-wardrobe-checklist",
        "--quality-note", $note
    )
    if ($ConfirmFootwearReview) { $args += "--confirm-footwear-review" }
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "Wardrobe authority recording failed." }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
