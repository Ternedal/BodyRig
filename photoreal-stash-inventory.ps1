param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Test-NumericV1 {
    param([AllowNull()]$Value)
    if ($null -eq $Value -or $Value -is [bool]) { return $false }
    try {
        $typeCode = [Type]::GetTypeCode($Value.GetType())
    } catch {
        return $false
    }
    $numericTypes = @(
        [TypeCode]::Byte,
        [TypeCode]::Decimal,
        [TypeCode]::Double,
        [TypeCode]::Int16,
        [TypeCode]::Int32,
        [TypeCode]::Int64,
        [TypeCode]::SByte,
        [TypeCode]::Single,
        [TypeCode]::UInt16,
        [TypeCode]::UInt32,
        [TypeCode]::UInt64
    )
    if ($numericTypes -notcontains $typeCode) { return $false }
    $number = [double]$Value
    return (-not [double]::IsNaN($number)) -and (-not [double]::IsInfinity($number)) -and $number -eq 1.0
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
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Photoreal Stash inventory requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $local = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $local -PathType Leaf) {
        $BodyRigPython = (Resolve-Path -LiteralPath $local).Path
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python was not found." }
        $BodyRigPython = $command.Source
    }
} else {
    $BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
}

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = "http://localhost:9999" }
if ([string]::IsNullOrWhiteSpace($PerformerId)) { throw "PerformerId is required." }
if ([string]::IsNullOrWhiteSpace($OutputPath)) { throw "OutputPath is required." }
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $OutputPath) { throw "Photoreal inventory output already exists: $OutputPath" }

Write-Host "BodyRig Photoreal V2 source inventory"
Write-Host "Revision:      $head"
Write-Host "Performer:     $PerformerId"
Write-Host "Stash:         $StashUrl"
Write-Host "Output:        $OutputPath"
Write-Host "VR/stereo:     INCLUDED"
Write-Host "Still images:  INCLUDED"
Write-Host "Galleries:     INCLUDED"
Write-Host "Production:    FALSE"
Write-Host ""

$priorPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })
    & $BodyRigPython -m bodyrig.photoreal_stash_inventory_cli `
        --performer-id $PerformerId `
        --out $OutputPath `
        --stash-url $StashUrl `
        --api-key-env $ApiKeyEnv
    if ($LASTEXITCODE -ne 0) { throw "Photoreal Stash inventory failed with exit code $LASTEXITCODE." }
} finally {
    $env:PYTHONPATH = $priorPythonPath
}

if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) { throw "Photoreal inventory output was not created." }
try { $inventory = Get-Content -LiteralPath $OutputPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 }
catch { throw "Photoreal inventory output is unreadable JSON." }
if ([string]$inventory.format -ne "bodyrig-photoreal-source-inventory" -or -not (Test-NumericV1 -Value $inventory.version) -or
    -not (Test-StrictBoolean -Value $inventory.summary.source_universe_exhaustive -Expected $true) -or
    -not (Test-StrictBoolean -Value $inventory.photoreal_teacher_input -Expected $true) -or
    -not (Test-StrictBoolean -Value $inventory.runtime_dependency -Expected $false) -or
    -not (Test-StrictBoolean -Value $inventory.production_activation -Expected $false)) {
    throw "Photoreal inventory crossed its build-only authority boundary."
}

Write-Host ""
Write-Host "BodyRig Photoreal V2 source inventory: READY"
Write-Host "Scenes:        $([int]$inventory.scene_count)"
Write-Host "Video files:   $([int]$inventory.video_file_count)"
Write-Host "Flat hours:    $([double]$inventory.summary.flat_video_hours)"
Write-Host "Spatial hours: $([double]$inventory.summary.spatial_or_projection_video_hours)"
Write-Host "Galleries:     $([int]$inventory.gallery_count)"
Write-Host "Image files:   $([int]$inventory.image_file_count)"
Write-Host "High-res imgs: $([int]$inventory.summary.high_resolution_image_count)"
Write-Host "Output:        $OutputPath"
