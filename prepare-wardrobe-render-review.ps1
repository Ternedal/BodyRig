param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [string]$UnityExe = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Wardrobe render review is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for wardrobe render review."
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
}
function Resolve-BodyRigPython {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    $command = Get-Command python -ErrorAction Stop
    return $command.Source
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -gt 0) { throw "Wardrobe render review requires a clean BodyRig checkout." }
$revision = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve canonical BodyRig checkout revision." }

$package = (Resolve-Path -LiteralPath $PackagePath -ErrorAction Stop).Path
if ([System.IO.Path]::GetExtension($package) -ne ".mrbody") { throw "Wardrobe render review requires an exact .mrbody package." }
$packageSha = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
$output = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) { throw "Wardrobe render output already exists; refusing cross-attempt reuse." }
$parent = Split-Path -Parent $output
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw "Wardrobe render output parent does not exist: $parent" }
$attempt = Join-Path $parent (".bodyrig-wardrobe-render-" + [Guid]::NewGuid().ToString("N"))
$committed = $false

$python = Resolve-BodyRigPython
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Wardrobe render review requires Python 3.11+." }
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
    $lineageRaw = @(& $python -m bodyrig.wardrobe_package_lineage_cli $package)
    if ($LASTEXITCODE -ne 0 -or $lineageRaw.Count -ne 1) { throw "Wardrobe package-lineage inspection failed." }
    try { $lineage = ([string]$lineageRaw[0]) | ConvertFrom-Json }
    catch { throw "Wardrobe package-lineage CLI returned unreadable JSON." }
    if ([string]$lineage.format -ne "bodyrig-wardrobe-package-lineage" -or [int]$lineage.version -ne 1 -or
        [string]$lineage.policy_revision -ne "bodyrig-wardrobe-package-lineage-v1" -or
        (Need-Sha256 ([string]$lineage.package_sha256) "lineage.package_sha256") -ne $packageSha -or
        $lineage.source_outer_surface_used -ne $true -or $lineage.source_grounded -ne $true -or
        $lineage.comparison_only -ne $true -or $lineage.human_review_required -ne $true -or
        $lineage.production_activation -ne $false) {
        throw "Wardrobe package lineage is stale, incomplete or crossed the review-only boundary."
    }

    $renderScript = Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1"
    if (-not (Test-Path -LiteralPath $renderScript -PathType Leaf)) { throw "Canonical fidelity renderer wrapper is missing: $renderScript" }
    $params = @{ PackagePath = $package; OutputDir = $attempt; BodyRigPython = $python }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $params.UnityExe = $UnityExe }
    if ($SkipBuild) { $params.SkipBuild = $true }
    & $renderScript @params
    if ($LASTEXITCODE -ne 0) { throw "Canonical fidelity renderer failed." }

    $comparisonPath = Join-Path $attempt "comparison-authority.json"
    $machinePath = Join-Path $attempt "machine-probe.json"
    $deformationPath = Join-Path $attempt "deformation-probe.json"
    foreach ($required in @($comparisonPath,$machinePath,$deformationPath)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Wardrobe renderer evidence is incomplete: $required" }
    }
    $comparison = Get-Content -LiteralPath $comparisonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $runtimeSha = Need-Sha256 ([string]$comparison.runtime_manifest_sha256) "comparison.runtime_manifest_sha256"
    if ([string]$comparison.format -ne "bodyrig-fidelity-comparison-authority" -or [int]$comparison.version -ne 1 -or
        [string]$comparison.authority -ne "validated-package-comparison-only" -or [string]$comparison.bodyrig_revision -ne $revision -or
        (Need-Sha256 ([string]$comparison.package_sha256) "comparison.package_sha256") -ne $packageSha -or
        $comparison.physical_acceptance_authority -ne $false -or $comparison.comparison_only -ne $true -or
        $comparison.production_activation -ne $false) {
        throw "M3 requires the exact validated-package comparison authority."
    }

    $machine = Get-Content -LiteralPath $machinePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $deformation = Get-Content -LiteralPath $deformationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$machine.format -ne "bodyrig-renderer-probe" -or [int]$machine.version -ne 1 -or
        [string]$machine.bodyrig_revision -ne $revision -or [string]$machine.platform -ne "windows-unity-univrm" -or
        (Need-Sha256 ([string]$machine.package_sha256) "machine.package_sha256") -ne $packageSha -or
        (Need-Sha256 ([string]$machine.runtime_manifest_sha256) "machine.runtime_manifest_sha256") -ne $runtimeSha -or
        $machine.vrm10_loaded -ne $true -or $machine.humanoid_valid -ne $true -or $machine.required_bones_valid -ne $true) {
        throw "Wardrobe machine probe is stale, mismatched or incomplete."
    }
    $avatarSha = Need-Sha256 ([string]$machine.avatar_sha256) "machine.avatar_sha256"
    if ($avatarSha -ne (Need-Sha256 ([string]$lineage.avatar_sha256) "lineage.avatar_sha256")) {
        throw "Wardrobe renderer did not load the exact source-geometry avatar carried by the package."
    }
    $bodyId = [string]$machine.body_id
    if ([string]::IsNullOrWhiteSpace($bodyId) -or $bodyId -ne [string]$lineage.canonical_body_id) {
        throw "Wardrobe machine probe body id differs from package lineage."
    }

    $expectedPoses = @("neutral","arms_abduction","elbows_flexed","arms_forward","left_leg_lift","knee_flexion")
    $actualPoses = @($deformation.poses | ForEach-Object { [string]$_.id })
    if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or
        [string]$deformation.bodyrig_revision -ne $revision -or [string]$deformation.platform -ne "windows-unity-univrm" -or
        [string]$deformation.body_id -ne $bodyId -or
        (Need-Sha256 ([string]$deformation.package_sha256) "deformation.package_sha256") -ne $packageSha -or
        (Need-Sha256 ([string]$deformation.runtime_manifest_sha256) "deformation.runtime_manifest_sha256") -ne $runtimeSha -or
        (Need-Sha256 ([string]$deformation.avatar_sha256) "deformation.avatar_sha256") -ne $avatarSha -or
        [string]$deformation.build_guid -ne [string]$machine.build_guid -or
        [string]$deformation.sequence_revision -ne "humanoid-muscle-sweep-v1" -or [int]$deformation.pose_count -ne 6 -or
        ($actualPoses -join ',') -ne ($expectedPoses -join ',') -or
        $deformation.required_muscles_resolved -ne $true -or $deformation.restored_neutral -ne $true -or
        $deformation.complete -ne $true -or $deformation.manual_review_required -ne $true) {
        throw "Wardrobe deformation evidence is stale, mismatched or incomplete."
    }

    $snapshotRoot = Join-Path $attempt "snapshots"
    $manifestPath = Join-Path $snapshotRoot "wardrobe-render-set.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Reference renderer did not produce wardrobe-render-set.json." }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedViews = @("front","left_side","right_side","back")
    $actualViews = @($manifest.snapshots | ForEach-Object { [string]$_.view })
    if ([string]$manifest.format -ne "bodyrig-wardrobe-render-set" -or [int]$manifest.version -ne 1 -or
        [string]$manifest.semantics -ne "human-review-diagnostic-not-physical-pass" -or
        [string]$manifest.body_id -ne $bodyId -or
        (Need-Sha256 ([string]$manifest.package_sha256) "wardrobe.package_sha256") -ne $packageSha -or
        ($actualViews -join ',') -ne ($expectedViews -join ',')) {
        throw "Wardrobe render manifest is non-canonical or belongs to different package bytes."
    }
    $viewHashes = [ordered]@{}
    foreach ($snapshot in @($manifest.snapshots)) {
        $view = [string]$snapshot.view
        $filename = [string]$snapshot.file
        if ($filename -ne ($view + ".png") -or [int]$snapshot.width -ne 1024 -or [int]$snapshot.height -ne 1024) {
            throw "Wardrobe snapshot metadata is non-canonical: $view"
        }
        $image = Join-Path $snapshotRoot $filename
        if (-not (Test-Path -LiteralPath $image -PathType Leaf)) { throw "Missing wardrobe snapshot: $filename" }
        $expectedSha = Need-Sha256 ([string]$snapshot.sha256) "$view snapshot SHA-256"
        $actualSha = (Get-FileHash -LiteralPath $image -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha -ne $expectedSha) { throw "Wardrobe snapshot changed after capture: $filename" }
        $viewHashes[$view] = $actualSha
    }

    $lineagePath = Join-Path $attempt "wardrobe-package-lineage.json"
    $lineage | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $lineagePath -Encoding UTF8
    $lineageSha = (Get-FileHash -LiteralPath $lineagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $comparisonSha = (Get-FileHash -LiteralPath $comparisonPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $machineSha = (Get-FileHash -LiteralPath $machinePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $deformationSha = (Get-FileHash -LiteralPath $deformationPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifestSha = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $renderAuthority = [ordered]@{
        format = "bodyrig-wardrobe-render-authority"
        version = 1
        bodyrig_revision = $revision
        body_id = $bodyId
        package_sha256 = $packageSha
        avatar_sha256 = $avatarSha
        runtime_manifest_sha256 = $runtimeSha
        comparison_authority_sha256 = $comparisonSha
        package_lineage_sha256 = $lineageSha
        source_geometry_authority_sha256 = Need-Sha256 ([string]$lineage.source_geometry_authority_sha256) "lineage.source_geometry_authority_sha256"
        source_mesh_sha256 = Need-Sha256 ([string]$lineage.source_mesh_sha256) "lineage.source_mesh_sha256"
        source_material_sha256 = Need-Sha256 ([string]$lineage.source_material_sha256) "lineage.source_material_sha256"
        source_texture_sha256 = Need-Sha256 ([string]$lineage.source_texture_sha256) "lineage.source_texture_sha256"
        render_manifest_sha256 = $manifestSha
        render_view_sha256 = $viewHashes
        machine_probe_sha256 = $machineSha
        deformation_probe_sha256 = $deformationSha
        deformation_sequence_revision = "humanoid-muscle-sweep-v1"
        deformation_machine_pass = $true
        comparison_only = $true
        human_review_required = $true
        production_activation = $false
    }
    $authorityPath = Join-Path $attempt "wardrobe-render-authority.json"
    $renderAuthority | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $authorityPath -Encoding UTF8

    Move-Item -LiteralPath $attempt -Destination $output
    $committed = $true
    [pscustomobject]@{
        ok = $true
        bodyrig_revision = $revision
        package = $package
        output_dir = $output
        render_manifest = (Join-Path (Join-Path $output "snapshots") "wardrobe-render-set.json")
        render_authority = (Join-Path $output "wardrobe-render-authority.json")
        comparison_authority = (Join-Path $output "comparison-authority.json")
        deformation_probe = (Join-Path $output "deformation-probe.json")
        production_activation = $false
    } | ConvertTo-Json -Compress
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    if (-not $committed -and (Test-Path -LiteralPath $attempt -PathType Container)) { Remove-Item -LiteralPath $attempt -Recurse -Force }
}
