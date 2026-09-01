param(
    [Parameter(Mandatory = $true)][string]$HistoricalRender,
    [Parameter(Mandatory = $true)][string]$Pr40Render,
    [Parameter(Mandatory = $true)][string]$Pr41Render,
    [Parameter(Mandatory = $true)][string]$AbEvidence,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-InputDirectory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$historical = Resolve-InputDirectory -Path $HistoricalRender -Label "Historical render"
$pr40 = Resolve-InputDirectory -Path $Pr40Render -Label "#40 render"
$pr41 = Resolve-InputDirectory -Path $Pr41Render -Label "#41 render"
$evidence = Resolve-InputFile -Path $AbEvidence -Label "A/B evidence"
$output = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) { throw "Review bundle output already exists: $output" }

if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $python = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"
} else {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $python = (Resolve-Path -LiteralPath $venvPython).Path
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python not found. Pass -BodyRigPython from the rig checkout when using a separate helper worktree." }
        $python = $command.Source
    }
}

$previousPythonPath = [string]$env:PYTHONPATH
$bundleCommitted = $false
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$previousPythonPath" })
    $resolvedModules = @(& $python -c "import pathlib,bodyrig.fidelity_review_bundle as b,bodyrig.fidelity_review_receipt as r; print(pathlib.Path(b.__file__).resolve()); print(pathlib.Path(r.__file__).resolve())")
    if ($LASTEXITCODE -ne 0 -or $resolvedModules.Count -ne 2) { throw "Could not resolve BodyRig fidelity review/receipt modules." }
    foreach ($resolved in $resolvedModules) {
        $modulePath = ([string]$resolved).Trim()
        if (-not $modulePath.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "BodyRig fidelity review authority did not resolve from this checkout: $modulePath"
        }
    }

    $indexRaw = @(& $python -m bodyrig.fidelity_review_bundle `
        --historical-render $historical `
        --pr40-render $pr40 `
        --pr41-render $pr41 `
        --ab-evidence $evidence `
        --out $output)
    if ($LASTEXITCODE -ne 0 -or $indexRaw.Count -ne 1) { throw "BodyRig physical fidelity review bundle failed." }
    $index = ([string]$indexRaw[0]).Trim()
    if (-not (Test-Path -LiteralPath $index -PathType Leaf)) { throw "Review bundle did not produce index.html: $index" }

    $receiptRaw = @(& $python -m bodyrig.fidelity_review_receipt_cli seal --root $output --evidence $evidence)
    if ($LASTEXITCODE -ne 0 -or $receiptRaw.Count -ne 1) { throw "BodyRig physical fidelity review receipt failed." }
    try { $receiptResult = ([string]$receiptRaw[0]) | ConvertFrom-Json }
    catch { throw "BodyRig physical fidelity review receipt returned unreadable JSON." }
    if ($receiptResult.ok -ne $true) { throw "BodyRig physical fidelity review receipt did not return ok=true." }
    $receipt = Resolve-InputFile -Path ([string]$receiptResult.receipt) -Label "Physical fidelity review receipt"
    $bundleCommitted = $true
} catch {
    if (-not $bundleCommitted -and (Test-Path -LiteralPath $output -PathType Container)) {
        Remove-Item -LiteralPath $output -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
} finally {
    if ([string]::IsNullOrEmpty($previousPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}

Write-Host "BodyRig physical fidelity review bundle: PASS"
Write-Host "Review page: $index"
Write-Host "Receipt:     $receipt"
Write-Host "NEXT: open index.html and review each row left-to-right: historical bad baseline -> #40 donor topology -> #41 seam-aware UV."
Write-Host "Human visual authority remains mandatory; this bundle cannot grant production activation."
exit 0
