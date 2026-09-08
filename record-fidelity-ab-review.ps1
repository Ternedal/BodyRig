param(
    [Parameter(Mandatory = $true)][string]$AbEvidence,
    [Parameter(Mandatory = $true)][string]$LeftRenderDir,
    [Parameter(Mandatory = $true)][string]$RightRenderDir,
    [Parameter(Mandatory = $true)][ValidateSet("left", "right", "tie", "reject-both")][string]$Decision,
    [Parameter(Mandatory = $true)][ValidateLength(1, 4000)][string]$QualityNote,
    [Parameter(Mandatory = $true)][switch]$ConfirmVisualReview,
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig fidelity A/B human review is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for BodyRig fidelity A/B human review."
}
if (-not $ConfirmVisualReview) {
    throw "Pass -ConfirmVisualReview only after visually comparing all four canonical left/right snapshots."
}
if ([string]::IsNullOrWhiteSpace($QualityNote) -or $QualityNote.Trim() -match '^<[^>]+>$') {
    throw "QualityNote must contain the operator's actual visual A/B assessment."
}

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

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind human A/B review to exact BodyRig checkout."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Human A/B review requires an exact clean BodyRig checkout."
}

$AbEvidence = Need-File -Path $AbEvidence -Label "Revision-bound A/B evidence"
$LeftRenderDir = Need-Directory -Path $LeftRenderDir -Label "Left fidelity render directory"
$RightRenderDir = Need-Directory -Path $RightRenderDir -Label "Right fidelity render directory"
$Output = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $Output) { throw "Human A/B review output already exists: $Output" }

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

$previousPythonPath = [string]$env:PYTHONPATH
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$previousPythonPath" })
    $moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not resolve checkout-bound BodyRig module." }
    $expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
    $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
    if (-not [string]::Equals($expectedModule, $actualModule, [StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports from a different checkout: $actualModule"
    }

    & $BodyRigPython -m bodyrig.fidelity_ab_review `
        --ab-evidence $AbEvidence `
        --left-render-dir $LeftRenderDir `
        --right-render-dir $RightRenderDir `
        --decision $Decision `
        --quality-note $QualityNote.Trim() `
        --expected-renderer-revision $head `
        --confirm-visual-review `
        --out $Output
    if ($LASTEXITCODE -ne 0) { throw "BodyRig fidelity A/B human review failed." }
} finally {
    if ([string]::IsNullOrEmpty($previousPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}

$finalHead = (@(& git -C $repoRoot rev-parse HEAD 2>&1) -join "").Trim().ToLowerInvariant()
$finalDirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $finalHead -ne $head -or $finalDirty.Count -gt 0) {
    if (Test-Path -LiteralPath $Output -PathType Leaf) { Remove-Item -LiteralPath $Output -Force }
    throw "BodyRig checkout changed while human A/B review was being written; removed non-authoritative receipt."
}

Write-Host "BodyRig fidelity A/B human review: PASS"
Write-Host "Decision:   $Decision"
Write-Host "Revision:   $head (matches both render sets)"
Write-Host "Evidence:   $Output"
Write-Host "Authority:  comparison-only human preference; physical acceptance=false; production activation=false"
exit 0
