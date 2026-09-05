param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$ReviewRuntimeDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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
function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
    catch { throw "$Label is unreadable JSON: $Path" }
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
}
function Resolve-BodyRigPython {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$Requested = "")
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { return Need-File -Path $Requested -Label "BodyRig Python" }
    $local = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $local -PathType Leaf) { return (Resolve-Path -LiteralPath $local).Path }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "BodyRig Python was not found." }
    return $command.Source
}
function Assert-CleanHead {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$Expected = "")
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Hair+eye Windows preview requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($Expected) -and $head -ne $Expected) { throw "BodyRig HEAD changed during hair+eye Windows preview." }
    return $head
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig source hair+eye preview is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CleanHead -RepoRoot $repoRoot
$PackagePath = Need-File -Path $PackagePath -Label "Candidate body package"
$ReviewRuntimeDir = Need-Directory -Path $ReviewRuntimeDir -Label "Combined source hair+eye runtime directory"
$sourceReviewReceipt = Need-File -Path (Join-Path $ReviewRuntimeDir "source-hair-eye-review-runtime.json") -Label "Combined source hair+eye runtime receipt"
$sourceReviewVrm = Need-File -Path (Join-Path $ReviewRuntimeDir "source-hair-eye-review.vrm") -Label "Combined source hair+eye review VRM"
$sourceReview = Read-Json -Path $sourceReviewReceipt -Label "Combined source hair+eye runtime receipt"
if ([string]$sourceReview.format -ne "bodyrig-source-hair-eye-review-runtime" -or [int]$sourceReview.version -ne 1 -or
    [string]$sourceReview.bodyrigRevision -ne $head -or [string]$sourceReview.reviewVrmSha256 -ne (Sha256 $sourceReviewVrm) -or
    $sourceReview.sourceHairRuntimeApplied -ne $true -or $sourceReview.sourceEyeSurfaceApplied -ne $true -or
    [string]$sourceReview.cornealMaterialStatus -ne "runtime-applied" -or
    $sourceReview.comparisonOnly -ne $true -or $sourceReview.humanReviewRequired -ne $true -or
    $sourceReview.hairComponentAuthority -ne $false -or $sourceReview.eyeComponentAuthority -ne $false -or
    $sourceReview.productionActivation -ne $false) {
    throw "Combined source hair+eye runtime is not valid review-only input for Windows preview."
}

$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Hair+eye preview output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParent) -or -not (Test-Path -LiteralPath $outputParent -PathType Container)) {
    throw "Hair+eye preview output parent does not exist: $outputParent"
}
$previewRuntime = Join-Path $outputParent (".bodyrig-hair-eye-preview-runtime-" + [Guid]::NewGuid().ToString("N"))
$python = Resolve-BodyRigPython -RepoRoot $repoRoot -Requested $BodyRigPython
$priorPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })
    $raw = @(& $python -m bodyrig.source_hair_eye_preview_runtime --package $PackagePath --review-runtime-dir $ReviewRuntimeDir --destination $previewRuntime 2>&1)
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        foreach ($line in $raw) { Write-Host ([string]$line) }
        throw "Hair+eye preview runtime materialization failed with exit code $code."
    }
    if ($raw.Count -ne 1) { throw "Hair+eye preview runtime materializer returned unexpected output." }
    try { $materialized = ([string]$raw[0]) | ConvertFrom-Json -Depth 20 }
    catch { throw "Hair+eye preview runtime materializer returned unreadable JSON." }
    if ($materialized.ok -ne $true -or $materialized.comparison_only -ne $true -or $materialized.production_activation -ne $false) {
        throw "Hair+eye preview materializer crossed the review-only authority boundary."
    }

    $authorityPath = Need-File -Path (Join-Path $previewRuntime "review-runtime-authority.json") -Label "Hair+eye preview runtime authority"
    $runtimeManifest = Need-File -Path (Join-Path $previewRuntime "runtime-manifest.json") -Label "Hair+eye preview runtime manifest"
    $previewAvatar = Need-File -Path (Join-Path $previewRuntime "avatar.vrm") -Label "Hair+eye preview avatar"
    $authority = Read-Json -Path $authorityPath -Label "Hair+eye preview runtime authority"
    if ([string]$authority.format -ne "bodyrig-source-hair-eye-preview-runtime" -or [int]$authority.version -ne 1 -or
        [string]$authority.bodyrigRevision -ne $head -or [string]$authority.reviewVrmSha256 -ne (Sha256 $previewAvatar) -or
        [string]$authority.runtimeManifestSha256 -ne (Sha256 $runtimeManifest) -or
        $authority.sourceHairRuntimeApplied -ne $true -or $authority.sourceEyeSurfaceApplied -ne $true -or
        [string]$authority.cornealMaterialStatus -ne "runtime-applied" -or
        $authority.physicalAcceptanceAuthority -ne $false -or $authority.productionActivation -ne $false) {
        throw "Materialized hair+eye preview runtime authority is invalid."
    }

    Assert-CleanHead -RepoRoot $repoRoot -Expected $head | Out-Null
    $fidelity = Need-File -Path (Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1") -Label "Fidelity Windows renderer"
    $renderArgs = @{ ReviewRuntimeDir = $previewRuntime; OutputDir = $OutputDir }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $renderArgs.UnityExe = $UnityExe }
    if ($SkipBuild) { $renderArgs.SkipBuild = $true }
    & $fidelity @renderArgs
    if ($LASTEXITCODE -ne 0) { throw "Hair+eye fidelity renderer failed with exit code $LASTEXITCODE." }

    $comparisonPath = Need-File -Path (Join-Path $OutputDir "comparison-authority.json") -Label "Hair+eye preview comparison authority"
    $hairProbePath = Need-File -Path (Join-Path $OutputDir "hair-deformation-probe.json") -Label "Hair deformation machine probe"
    $snapshotManifestPath = Need-File -Path (Join-Path $OutputDir "snapshots\fidelity-render-set.json") -Label "Hair+eye preview snapshot manifest"
    $comparison = Read-Json -Path $comparisonPath -Label "Hair+eye preview comparison authority"
    $hairProbe = Read-Json -Path $hairProbePath -Label "Hair deformation machine probe"
    $snapshotManifest = Read-Json -Path $snapshotManifestPath -Label "Hair+eye preview snapshot manifest"
    $hairProbeSha = Sha256 $hairProbePath
    if ([string]$comparison.authority -ne "source-hair-eye-review-runtime" -or
        [string]$comparison.review_avatar_sha256 -ne (Sha256 $sourceReviewVrm) -or
        $comparison.source_hair_runtime_applied -ne $true -or $comparison.source_eye_surface_applied -ne $true -or
        [string]$comparison.corneal_material_status -ne "runtime-applied" -or
        (Need-Sha256 ([string]$comparison.hair_deformation_probe_sha256) "comparison hair deformation SHA") -ne $hairProbeSha -or
        $comparison.hair_deformation_machine_pass -ne $true -or $comparison.hair_deformation_human_review_required -ne $true -or
        $comparison.physical_acceptance_authority -ne $false -or $comparison.production_activation -ne $false) {
        throw "Hair+eye preview render comparison authority is invalid or lacks exact hair deformation evidence."
    }
    if ([string]$hairProbe.format -ne "bodyrig-hair-deformation-probe" -or [int]$hairProbe.version -ne 1 -or
        [string]$hairProbe.platform -ne "windows-unity-univrm" -or
        [string]$hairProbe.bodyrig_revision -ne $head -or
        [string]$hairProbe.package_sha256 -ne [string]$sourceReview.packageSha256 -or
        [string]$hairProbe.avatar_sha256 -ne (Sha256 $sourceReviewVrm) -or
        [string]$hairProbe.sequence_revision -ne "source-hair-head-turn-v1" -or
        [string]$hairProbe.hair_node -ne "BodyRigSourceHairReview" -or
        [string]$hairProbe.hair_mesh -ne "BodyRigSourceHairReviewMesh" -or
        $hairProbe.skinned_mesh_renderer_found -ne $true -or $hairProbe.head_bone_resolved -ne $true -or $hairProbe.head_bone_bound -ne $true -or
        $hairProbe.vertex_motion_observed -ne $true -or $hairProbe.restored_neutral -ne $true -or $hairProbe.complete -ne $true -or
        $hairProbe.human_review_required -ne $true -or $hairProbe.comparison_only -ne $true -or
        $hairProbe.hair_component_authority -ne $false -or $hairProbe.production_activation -ne $false) {
        throw "Hair deformation machine probe is stale, incomplete or crossed the review-only authority boundary."
    }
    if ([double]$hairProbe.observed_head_turn_degrees -lt 18.2 -or
        [double]$hairProbe.vertex_motion_rms_m -lt 0.00025 -or [double]$hairProbe.vertex_motion_max_m -lt 0.001 -or
        [double]$hairProbe.restoration_rms_m -gt 0.00025 -or [double]$hairProbe.restoration_max_m -gt 0.001) {
        throw "Hair deformation machine metrics do not satisfy the canonical head-turn thresholds."
    }

    $views = @($snapshotManifest.snapshots | ForEach-Object { [string]$_.view })
    if (($views -join ',') -ne 'front-full,three-quarter-full,side-full,face-front') {
        throw "Hair+eye preview renderer did not emit the four canonical views."
    }
    foreach ($view in $views) {
        Need-File -Path (Join-Path $OutputDir ("snapshots\" + $view + ".png")) -Label "Hair+eye preview $view" | Out-Null
    }
    $faceZoomPath = Need-File -Path (Join-Path $OutputDir "snapshots\face-zoom.png") -Label "Hair+eye preview face zoom diagnostic"
    $eyesCloseupPath = Need-File -Path (Join-Path $OutputDir "snapshots\eyes-closeup.png") -Label "Hair+eye preview eye closeup diagnostic"
    Assert-CleanHead -RepoRoot $repoRoot -Expected $head | Out-Null

    Write-Host ""
    Write-Host "BodyRig source hair + eye Windows preview: READY"
    Write-Host "Hair:        RENDERED"
    Write-Host "Hair move:   MACHINE PASS; human clipping/attachment review still required"
    Write-Host "Hair probe:  $hairProbePath"
    Write-Host "Eye surface: RENDERED"
    Write-Host "Cornea:      RENDERED"
    Write-Host "Front:       $(Join-Path $OutputDir 'snapshots\front-full.png')"
    Write-Host "3/4:         $(Join-Path $OutputDir 'snapshots\three-quarter-full.png')"
    Write-Host "Side:        $(Join-Path $OutputDir 'snapshots\side-full.png')"
    Write-Host "Face:        $(Join-Path $OutputDir 'snapshots\face-front.png')"
    Write-Host "Face zoom:   $faceZoomPath"
    Write-Host "Eyes close:  $eyesCloseupPath"
    Write-Host "Authority:   REVIEW ONLY; hair component FALSE; physical acceptance FALSE; production FALSE"
    exit 0
} finally {
    $env:PYTHONPATH = $priorPythonPath
    if (Test-Path -LiteralPath $previewRuntime -PathType Container) {
        Remove-Item -LiteralPath $previewRuntime -Recurse -Force -ErrorAction SilentlyContinue
    }
}