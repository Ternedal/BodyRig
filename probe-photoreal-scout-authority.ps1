param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$ProbeRoot = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
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

function Assert-Diagnostic-Boundary {
    param([Parameter(Mandatory = $true)]$Probe)
    if ([string]$Probe.format -ne "bodyrig-photoreal-spatial-container-probe" -or
        [int]$Probe.version -ne 1 -or
        -not (Test-StrictBoolean -Value $Probe.diagnostic_only -Expected $true) -or
        -not (Test-StrictBoolean -Value $Probe.deprojection_authority -Expected $false) -or
        -not (Test-StrictBoolean -Value $Probe.photoreal_acceptance_authority -Expected $false) -or
        -not (Test-StrictBoolean -Value $Probe.build_only -Expected $true) -or
        -not (Test-StrictBoolean -Value $Probe.runtime_dependency -Expected $false) -or
        -not (Test-StrictBoolean -Value $Probe.production_activation -Expected $false)) {
        throw "Spatial metadata diagnostic crossed its authority boundary."
    }
}

function Assert-Scout-Diagnostic-Boundary {
    param([Parameter(Mandatory = $true)]$Scan)
    if ([string]$Scan.format -ne "bodyrig-photoreal-scan-plan" -or
        [int]$Scan.version -ne 1 -or
        -not (Test-StrictBoolean -Value $Scan.teacher_training_authorized -Expected $false) -or
        -not (Test-StrictBoolean -Value $Scan.build_only -Expected $true) -or
        -not (Test-StrictBoolean -Value $Scan.runtime_dependency -Expected $false) -or
        -not (Test-StrictBoolean -Value $Scan.production_activation -Expected $false)) {
        throw "Diagnostic scout replay crossed its pre-training authority boundary."
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Scout authority replay requires an exact clean BodyRig checkout."
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
$PlanPath = Need-File -Path (Join-Path $OutputRoot "dataset-plan.json") -Label "Photoreal dataset plan"
$ReceiptPath = Need-File -Path (Join-Path $OutputRoot "source-receipt.json") -Label "Photoreal source receipt"

if ([string]::IsNullOrWhiteSpace($ProbeRoot)) {
    $ProbeRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-photoreal-scout-probe-" + [guid]::NewGuid().ToString("N"))
} else {
    $ProbeRoot = [IO.Path]::GetFullPath($ProbeRoot)
}
$oldPrefix = $OutputRoot.TrimEnd([char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)) + [IO.Path]::DirectorySeparatorChar
if ($ProbeRoot.Equals($OutputRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $ProbeRoot.StartsWith($oldPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "ProbeRoot must remain outside the original P0 output root."
}
if (Test-Path -LiteralPath $ProbeRoot) {
    throw "ProbeRoot must be a new non-existing directory: $ProbeRoot"
}
New-Item -ItemType Directory -Path $ProbeRoot | Out-Null
$ProbeRoot = (Resolve-Path -LiteralPath $ProbeRoot).Path

$SpatialProbePath = Join-Path $ProbeRoot "diagnostic-spatial-container-probe.json"
$DiagnosticScanPath = Join-Path $ProbeRoot "diagnostic-scan-plan.json"

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - READ-ONLY STAGE-4 AUTHORITY REPLAY"
Write-Host "Revision:          $head"
Write-Host "Original P0 root:  $OutputRoot"
Write-Host "Diagnostic root:   $ProbeRoot"
Write-Host "Original mutation: FALSE"
Write-Host "Teacher auth:      FALSE"
Write-Host "Photoreal accept:  FALSE"
Write-Host "Production:        FALSE"
Write-Host "============================================================"

$priorPythonPath = $env:PYTHONPATH
$scanExit = -1
$nativeErrorPreferenceVariable = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
$priorNativeErrorPreference = $null
if ($null -ne $nativeErrorPreferenceVariable) {
    $priorNativeErrorPreference = [bool]$nativeErrorPreferenceVariable.Value
    $PSNativeCommandUseErrorActionPreference = $false
}
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })

    & $Python -m bodyrig.photoreal_spatial_metadata_probe_cli `
        --inventory $InventoryPath `
        --receipt $ReceiptPath `
        --out $SpatialProbePath
    if ($LASTEXITCODE -ne 0) { throw "Spatial metadata diagnostic failed with exit code $LASTEXITCODE." }

    & $Python -m bodyrig.photoreal_scan_plan_cli `
        --plan $PlanPath `
        --receipt $ReceiptPath `
        --out $DiagnosticScanPath
    $scanExit = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $priorPythonPath
    if ($null -ne $nativeErrorPreferenceVariable) {
        $PSNativeCommandUseErrorActionPreference = $priorNativeErrorPreference
    }
}

$SpatialProbePath = Need-File -Path $SpatialProbePath -Label "Diagnostic spatial metadata output"
try { $probe = Get-Content -LiteralPath $SpatialProbePath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Diagnostic spatial metadata output is unreadable JSON." }
Assert-Diagnostic-Boundary -Probe $probe

$sources = @($probe.sources)
$equiCount = @($sources | Where-Object { [string]$_.projection_type -eq "equi" }).Count
$meshCount = @($sources | Where-Object { [string]$_.projection_type -eq "mshp" }).Count
$cubemapCount = @($sources | Where-Object { [string]$_.projection_type -eq "cbmp" }).Count
$leftRightCount = @($sources | Where-Object { [string]$_.stereo_mode -eq "left-right" }).Count
$topBottomCount = @($sources | Where-Object { [string]$_.stereo_mode -eq "top-bottom" }).Count
$monoCount = @($sources | Where-Object { [string]$_.stereo_mode -eq "mono" }).Count
$stereoCustomCount = @($sources | Where-Object { [string]$_.stereo_mode -eq "stereo-custom" }).Count
$rightLeftCount = @($sources | Where-Object { [string]$_.stereo_mode -eq "right-left" }).Count
$reservedStereoCount = @($sources | Where-Object { [string]$_.stereo_mode -eq "reserved-or-unknown" }).Count
$meshCustomCandidateCount = @($sources | Where-Object {
    [string]$_.projection_type -eq "mshp" -and [string]$_.stereo_mode -eq "stereo-custom"
}).Count
$noV2Count = @($sources | Where-Object { -not [bool]$_.sv3d_present }).Count

Write-Host ""
Write-Host "BodyRig spatial truth from existing byte-bound sources"
Write-Host "Video sources:          $([int]$probe.video_source_count)"
Write-Host "Spherical V2:           $([int]$probe.spherical_v2_source_count)"
Write-Host "Exact equi:             $equiCount"
Write-Host "Exact mesh (mshp):      $meshCount"
Write-Host "Exact cubemap (cbmp):   $cubemapCount"
Write-Host "Stereo left-right:      $leftRightCount"
Write-Host "Stereo top-bottom:      $topBottomCount"
Write-Host "Stereo mono:            $monoCount"
Write-Host "Stereo custom:          $stereoCustomCount"
Write-Host "Stereo right-left:      $rightLeftCount"
Write-Host "Stereo reserved:        $reservedStereoCount"
Write-Host "Mesh+custom candidate:  $meshCustomCandidateCount"
Write-Host "No Spherical V2:        $noV2Count"
Write-Host "Size mismatches:        $([int]$probe.size_mismatch_count)"
Write-Host "Spatial diagnostic:     $SpatialProbePath"

if ($scanExit -ne 0) {
    Write-Host ""
    Write-Host "CURRENT STAGE-4 AUTHORITY GATE: BLOCKED"
    Write-Host "Diagnostic replay only; original P0 output remains unchanged."
    throw "Current stage-4 authority replay failed with exit code $scanExit. Inspect the projection/stereo summary above."
}

$DiagnosticScanPath = Need-File -Path $DiagnosticScanPath -Label "Diagnostic scout plan"
try { $scan = Get-Content -LiteralPath $DiagnosticScanPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Diagnostic scout plan is unreadable JSON." }
Assert-Scout-Diagnostic-Boundary -Scan $scan

$scanSources = @($scan.sources)
$scanEqui = @($scanSources | Where-Object { [string]$_.projection -eq "equi" }).Count
$scanMesh = @($scanSources | Where-Object { [string]$_.projection -eq "mshp" }).Count
$scanCubemap = @($scanSources | Where-Object { [string]$_.projection -eq "cbmp" }).Count
$scanMeshCustom = @($scanSources | Where-Object {
    [string]$_.projection -eq "mshp" -and [string]$_.stereo_layout -eq "mesh-custom"
}).Count
$spatialDecode = @($scanSources | Where-Object { [string]$_.decode_mode -eq "spatial-deprojection-required" }).Count
$spatialBootstrap = @($scanSources | Where-Object {
    [string]$_.decode_mode -eq "spatial-deprojection-required" -and [bool]$_.identity_bootstrap_eligible
}).Count
if ($spatialBootstrap -ne 0) {
    throw "Diagnostic scout replay unexpectedly granted spatial identity bootstrap authority."
}

Write-Host ""
Write-Host "CURRENT STAGE-4 AUTHORITY GATE: PASS (DIAGNOSTIC REPLAY ONLY)"
Write-Host "Exact equi in scout:  $scanEqui"
Write-Host "Exact mesh in scout:  $scanMesh"
Write-Host "Exact cubemap scout:  $scanCubemap"
Write-Host "Mesh-custom in scout: $scanMeshCustom"
Write-Host "Spatial decode-bound: $spatialDecode"
Write-Host "Spatial bootstrap:    FALSE"
Write-Host "Teacher auth:         FALSE"
Write-Host "Production:           FALSE"
Write-Host "Diagnostic scout:     $DiagnosticScanPath"
Write-Host ""
Write-Host "Do not reuse this diagnostic scout plan as canonical P0 authority."
