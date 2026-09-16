param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Test-StrictBoolean {
    param(
        [AllowNull()]$Value,
        [Parameter(Mandatory = $true)][bool]$Expected
    )
    return ($Value -is [bool]) -and ([bool]$Value -eq $Expected)
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Spatial metadata probe requires an exact clean BodyRig checkout."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $Python = (Resolve-Path -LiteralPath $localPython).Path
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python was not found." }
        $Python = $command.Source
    }
} else {
    $Python = Need-File -Path $BodyRigPython -Label "BodyRig Python"
}

$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (-not (Test-Path -LiteralPath $OutputRoot -PathType Container)) {
    throw "Photoreal P0 output root not found: $OutputRoot"
}
$InventoryPath = Need-File -Path (Join-Path $OutputRoot "source-inventory.json") -Label "Photoreal source inventory"
$ReceiptPath = Need-File -Path (Join-Path $OutputRoot "source-receipt.json") -Label "Photoreal source receipt"
$ProbePath = Join-Path $OutputRoot "spatial-container-probe.json"
if (Test-Path -LiteralPath $ProbePath) { throw "Spatial metadata probe output already exists: $ProbePath" }

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - SPATIAL CONTAINER PROBE"
Write-Host "Revision:          $head"
Write-Host "P0 output:         $OutputRoot"
Write-Host "Diagnostic only:   TRUE"
Write-Host "Deprojection auth: FALSE"
Write-Host "Photoreal accept:  FALSE"
Write-Host "Production:        FALSE"
Write-Host "============================================================"

$priorPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })
    & $Python -m bodyrig.photoreal_spatial_metadata_probe_cli `
        --inventory $InventoryPath `
        --receipt $ReceiptPath `
        --out $ProbePath
    if ($LASTEXITCODE -ne 0) { throw "Spatial metadata probe failed with exit code $LASTEXITCODE." }
} finally {
    $env:PYTHONPATH = $priorPythonPath
}

$ProbePath = Need-File -Path $ProbePath -Label "Spatial metadata probe output"
try { $probe = Get-Content -LiteralPath $ProbePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 }
catch { throw "Spatial metadata probe output is unreadable JSON." }

if ([string]$probe.format -ne "bodyrig-photoreal-spatial-container-probe" -or
    [int]$probe.version -ne 1 -or
    -not (Test-StrictBoolean -Value $probe.diagnostic_only -Expected $true) -or
    -not (Test-StrictBoolean -Value $probe.deprojection_authority -Expected $false) -or
    -not (Test-StrictBoolean -Value $probe.photoreal_acceptance_authority -Expected $false) -or
    -not (Test-StrictBoolean -Value $probe.build_only -Expected $true) -or
    -not (Test-StrictBoolean -Value $probe.runtime_dependency -Expected $false) -or
    -not (Test-StrictBoolean -Value $probe.production_activation -Expected $false)) {
    throw "Spatial metadata probe crossed its diagnostic-only authority boundary."
}

Write-Host ""
Write-Host "BodyRig spatial container probe: READY"
Write-Host "Video sources:       $([int]$probe.video_source_count)"
Write-Host "Parsed ISO BMFF:     $([int]$probe.parsed_isobmff_count)"
Write-Host "Spherical V2:        $([int]$probe.spherical_v2_source_count)"
Write-Host "Mesh projection:     $([int]$probe.mesh_projection_source_count)"
Write-Host "CAMM tracks:         $([int]$probe.camm_source_count)"
Write-Host "Size mismatches:     $([int]$probe.size_mismatch_count)"
Write-Host "Output:              $ProbePath"
