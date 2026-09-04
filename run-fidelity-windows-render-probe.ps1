param(
    [string]$AcceptanceDir = "",
    [string]$PackagePath = "",
    [string]$ReviewRuntimeDir = "",
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig fidelity comparison rendering is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for BodyRig fidelity comparison rendering."
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
}
function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical Git SHA." }
    return $normalized
}
function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $Path" }
}
function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Invoke-NativeProcessWait {
    param([Parameter(Mandatory = $true)][string]$FilePath,[Parameter(Mandatory = $true)][string[]]$ArgumentList)
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.UseShellExecute = $false
    foreach ($argument in $ArgumentList) { [void]$startInfo.ArgumentList.Add($argument) }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { throw "Failed to start fidelity renderer: $FilePath" }
        $process.WaitForExit()
        return $process.ExitCode
    } finally {
        $process.Dispose()
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$usingAcceptance = -not [string]::IsNullOrWhiteSpace($AcceptanceDir)
$usingPackage = -not [string]::IsNullOrWhiteSpace($PackagePath)
$usingReviewRuntime = -not [string]::IsNullOrWhiteSpace($ReviewRuntimeDir)
$modeCount = 0
if ($usingAcceptance) { $modeCount++ }
if ($usingPackage) { $modeCount++ }
if ($usingReviewRuntime) { $modeCount++ }
if ($modeCount -ne 1) {
    throw "Pass exactly one of -AcceptanceDir, -PackagePath or -ReviewRuntimeDir for fidelity comparison rendering."
}

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Fidelity render output already exists; refusing cross-iteration reuse: $OutputDir" }
$currentHeadRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $currentHeadRaw.Count -ne 1) { throw "Could not resolve current BodyRig revision." }
$currentHead = Need-Revision ([string]$currentHeadRaw[0]) "current BodyRig HEAD"
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Fidelity rendering requires an exact clean BodyRig checkout." }

$parent = Split-Path -Parent $OutputDir
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw "Fidelity output parent does not exist: $parent" }
$attempt = Join-Path $parent (".bodyrig-fidelity-render-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attempt | Out-Null
$probePath = Join-Path $attempt "machine-probe.json"
$deformationPath = Join-Path $attempt "deformation-probe.json"
$hairDeformationPath = Join-Path $attempt "hair-deformation-probe.json"
$snapshotDir = Join-Path $attempt "snapshots"
$runtimeManifest = ""
$acceptedRevision = $currentHead
$expectedRuntimeSha = ""
$comparisonAuthority = ""
$reviewRuntimeAuthoritySha = ""
$reviewAvatarSha = ""
$reviewBodyprintSha = ""
$reviewPackageSha = ""
$committed = $false

try {
    if ($usingAcceptance) {
        $AcceptanceDir = [System.IO.Path]::GetFullPath($AcceptanceDir)
        if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Gate A acceptance directory not found: $AcceptanceDir" }
        $acceptancePath = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
        $runtimeManifest = Join-Path (Join-Path $AcceptanceDir "runtime") "runtime-manifest.json"
        $acceptance = Read-Json $acceptancePath "Gate A acceptance report"
        if ([string]$acceptance.format -ne "bodyrig-rig-acceptance" -or [int]$acceptance.version -ne 1 -or $acceptance.automated_pass -ne $true) {
            throw "Fidelity rendering requires a valid Gate A automated PASS."
        }
        if ($acceptance.production_activation -ne $false -or [string]$acceptance.physical_renderer_acceptance -ne "pending") {
            throw "Fidelity rendering requires a non-activating Gate A candidate with renderer acceptance still pending."
        }
        $acceptedRevision = Need-Revision ([string]$acceptance.bodyrig_revision) "acceptance.bodyrig_revision"
        if ($currentHead -ne $acceptedRevision) { throw "Current BodyRig checkout differs from Gate A candidate revision." }
        if (-not (Test-Path -LiteralPath $runtimeManifest -PathType Leaf)) { throw "Gate A runtime manifest not found: $runtimeManifest" }
        $expectedRuntimeSha = Need-Sha256 ([string]$acceptance.runtime.manifest_sha256) "acceptance.runtime.manifest_sha256"
        $actualRuntimeSha = (Get-FileHash -LiteralPath $runtimeManifest -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualRuntimeSha -ne $expectedRuntimeSha) { throw "Gate A runtime manifest changed after acceptance." }
        $comparisonAuthority = "gate-a-pending-candidate"
    } elseif ($usingPackage) {
        $PackagePath = Need-File -Path $PackagePath -Label "Comparison-only .mrbody package"
        if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
            $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
            else {
                $python = Get-Command python -ErrorAction SilentlyContinue
                if ($null -eq $python) { throw "BodyRig Python not found for direct package materialization." }
                $BodyRigPython = $python.Source
            }
        }
        $BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
        $runtimeRoot = Join-Path $attempt "runtime"
        $materializeRaw = @(& $BodyRigPython -m bodyrig.materialize_cli $PackagePath --out $runtimeRoot)
        if ($LASTEXITCODE -ne 0 -or $materializeRaw.Count -ne 1) { throw "Comparison-only package materialization failed." }
        try { $materialize = ([string]$materializeRaw[0]) | ConvertFrom-Json }
        catch { throw "Comparison-only materializer returned unreadable JSON." }
        $runtimeManifest = Need-File -Path ([string]$materialize.runtime_manifest) -Label "Comparison-only runtime manifest"
        $expectedPackageSha = Need-Sha256 ([string]$materialize.package_sha256) "materialize.package_sha256"
        $actualPackageSha = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualPackageSha -ne $expectedPackageSha) { throw "Comparison-only package changed after strict materialization." }
        $expectedRuntimeSha = (Get-FileHash -LiteralPath $runtimeManifest -Algorithm SHA256).Hash.ToLowerInvariant()
        $comparisonAuthority = "validated-package-comparison-only"
    } else {
        $ReviewRuntimeDir = [System.IO.Path]::GetFullPath($ReviewRuntimeDir)
        if (-not (Test-Path -LiteralPath $ReviewRuntimeDir -PathType Container)) { throw "Hair+eye review runtime directory not found: $ReviewRuntimeDir" }
        $runtimeManifest = Need-File -Path (Join-Path $ReviewRuntimeDir "runtime-manifest.json") -Label "Hair+eye review runtime manifest"
        $reviewAuthorityPath = Need-File -Path (Join-Path $ReviewRuntimeDir "review-runtime-authority.json") -Label "Hair+eye review runtime authority"
        $reviewAuthority = Read-Json $reviewAuthorityPath "Hair+eye review runtime authority"
        $expectedReviewAuthorityFields = @(
            "format","version","bodyrigRevision","bodyId","packageSha256","sourceReviewReceiptSha256",
            "reviewVrmSha256","bodyprintSha256","runtimeManifestSha256","sourceHairRuntimeApplied",
            "sourceEyeSurfaceApplied","cornealMaterialStatus","physicalSilhouetteReviewRequired",
            "physicalFaceCloseupReviewRequired","comparisonOnly","humanReviewRequired",
            "physicalAcceptanceAuthority","productionActivation"
        )
        if (@(Compare-Object -ReferenceObject $expectedReviewAuthorityFields -DifferenceObject @($reviewAuthority.PSObject.Properties.Name)).Count -ne 0) {
            throw "Hair+eye review runtime authority fields do not match v1."
        }
        if ([string]$reviewAuthority.format -ne "bodyrig-source-hair-eye-preview-runtime" -or [int]$reviewAuthority.version -ne 1) {
            throw "Hair+eye review runtime authority format/version mismatch."
        }
        $acceptedRevision = Need-Revision ([string]$reviewAuthority.bodyrigRevision) "reviewRuntime.bodyrigRevision"
        if ($acceptedRevision -ne $currentHead) { throw "Hair+eye review runtime was materialized from a different BodyRig revision." }
        if ($reviewAuthority.sourceHairRuntimeApplied -ne $true -or $reviewAuthority.sourceEyeSurfaceApplied -ne $true -or
            [string]$reviewAuthority.cornealMaterialStatus -ne "runtime-applied" -or
            $reviewAuthority.physicalSilhouetteReviewRequired -ne $true -or $reviewAuthority.physicalFaceCloseupReviewRequired -ne $true -or
            $reviewAuthority.comparisonOnly -ne $true -or $reviewAuthority.humanReviewRequired -ne $true -or
            $reviewAuthority.physicalAcceptanceAuthority -ne $false -or $reviewAuthority.productionActivation -ne $false) {
            throw "Hair+eye review runtime authority crossed the comparison-only boundary."
        }
        $reviewPackageSha = Need-Sha256 ([string]$reviewAuthority.packageSha256) "reviewRuntime.packageSha256"
        $reviewAvatarSha = Need-Sha256 ([string]$reviewAuthority.reviewVrmSha256) "reviewRuntime.reviewVrmSha256"
        $reviewBodyprintSha = Need-Sha256 ([string]$reviewAuthority.bodyprintSha256) "reviewRuntime.bodyprintSha256"
        $expectedRuntimeSha = Need-Sha256 ([string]$reviewAuthority.runtimeManifestSha256) "reviewRuntime.runtimeManifestSha256"
        $actualRuntimeSha = (Get-FileHash -LiteralPath $runtimeManifest -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualRuntimeSha -ne $expectedRuntimeSha) { throw "Hair+eye review runtime manifest changed after materialization." }
        $runtime = Read-Json $runtimeManifest "Hair+eye review runtime manifest"
        if ([string]$runtime.format -ne "bodyrig-runtime-assets" -or [int]$runtime.version -ne 1 -or
            [string]$runtime.body_id -ne [string]$reviewAuthority.bodyId -or
            (Need-Sha256 ([string]$runtime.package_sha256) "review runtime package SHA") -ne $reviewPackageSha -or
            [string]$runtime.avatar -ne "avatar.vrm" -or [string]$runtime.bodyprint -ne "bodyprint.json" -or
            (Need-Sha256 ([string]$runtime.avatar_sha256) "review runtime avatar SHA") -ne $reviewAvatarSha -or
            (Need-Sha256 ([string]$runtime.bodyprint_sha256) "review runtime bodyprint SHA") -ne $reviewBodyprintSha) {
            throw "Hair+eye review runtime manifest does not bind the exact review avatar/bodyprint authority."
        }
        $payloads = @($runtime.payloads | ForEach-Object { [string]$_ })
        if ($payloads.Count -ne 2 -or ($payloads -notcontains "avatar.vrm") -or ($payloads -notcontains "bodyprint.json")) {
            throw "Hair+eye review runtime manifest payload set is not canonical."
        }
        $reviewRuntimeAuthoritySha = (Get-FileHash -LiteralPath $reviewAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $comparisonAuthority = "source-hair-eye-review-runtime"
    }

    $contract = Read-Json (Join-Path $repoRoot "reference-renderer\renderer-contract.json") "Reference renderer contract"
    if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) {
        throw "Unsupported reference renderer contract."
    }
    $rendererName = [string]$contract.renderer_name
    $rendererVersion = [string]$contract.renderer_version
    $expectedUnityVersion = [string]$contract.unity_editor_version
    if ([string]::IsNullOrWhiteSpace($rendererName) -or [string]::IsNullOrWhiteSpace($rendererVersion) -or [string]::IsNullOrWhiteSpace($expectedUnityVersion)) {
        throw "Reference renderer contract is incomplete."
    }

    $rendererRoot = Join-Path $repoRoot "reference-renderer"
    $buildScript = Join-Path $rendererRoot "build-reference-renderer.ps1"
    $playerExe = Join-Path $rendererRoot "Builds\Windows\BodyRigReferenceProbe.exe"
    if (-not $SkipBuild) {
        $buildDir = Split-Path -Parent $playerExe
        if (Test-Path -LiteralPath $buildDir) { Remove-Item -LiteralPath $buildDir -Recurse -Force }
        $buildArgs = @{ Platform = "Windows"; Output = $playerExe }
        if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $buildArgs.UnityExe = $UnityExe }
        & $buildScript @buildArgs
        if ($LASTEXITCODE -ne 0) { throw "BodyRig fidelity Windows renderer build failed with exit code $LASTEXITCODE" }
    }
    if (-not (Test-Path -LiteralPath $playerExe -PathType Leaf)) { throw "Built reference player not found: $playerExe" }

    $args = @(
        "--bodyrig-runtime-manifest", $runtimeManifest,
        "--bodyrig-probe-output", $probePath,
        "--bodyrig-deformation-output", $deformationPath,
        "--bodyrig-fidelity-snapshot-dir", $snapshotDir,
        "--bodyrig-renderer-name", $rendererName,
        "--bodyrig-renderer-version", $rendererVersion,
        "--bodyrig-quit-after-probe"
    )
    if ($usingReviewRuntime) {
        $args += @("--bodyrig-hair-deformation-output", $hairDeformationPath)
    }
    $exitCode = Invoke-NativeProcessWait -FilePath $playerExe -ArgumentList $args
    if ($exitCode -ne 0) { throw "Fidelity reference player exited with code $exitCode" }

    $probe = Read-Json $probePath "Fidelity renderer machine probe"
    $deformation = Read-Json $deformationPath "Fidelity renderer deformation probe"
    $manifestPath = Join-Path $snapshotDir "fidelity-render-set.json"
    $manifest = Read-Json $manifestPath "Fidelity render-set manifest"

    if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [string]$probe.platform -ne "windows-unity-univrm") { throw "Fidelity machine probe format/platform mismatch." }
    if ((Need-Revision ([string]$probe.bodyrig_revision) "probe.bodyrig_revision") -ne $acceptedRevision) { throw "Fidelity player was not built from current comparison revision." }
    if ([string]$probe.unity_version -ne $expectedUnityVersion) { throw "Fidelity player Unity version does not match renderer contract." }
    if ((Need-Sha256 ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $expectedRuntimeSha) { throw "Fidelity machine probe is not bound to exact runtime bytes." }
    if ($usingReviewRuntime) {
        if ((Need-Sha256 ([string]$probe.package_sha256) "probe.package_sha256") -ne $reviewPackageSha -or
            (Need-Sha256 ([string]$probe.avatar_sha256) "probe.avatar_sha256") -ne $reviewAvatarSha -or
            (Need-Sha256 ([string]$probe.bodyprint_sha256) "probe.bodyprint_sha256") -ne $reviewBodyprintSha) {
            throw "Fidelity player did not load the exact source hair+eye review avatar/runtime bytes."
        }
    }
    if ([string]$deformation.bodyrig_revision -ne [string]$probe.bodyrig_revision -or [string]$deformation.build_guid -ne [string]$probe.build_guid -or $deformation.complete -ne $true) {
        throw "Fidelity deformation probe is not complete and build-bound to the machine probe."
    }

    $hairDeformation = $null
    $hairDeformationSha = ""
    if ($usingReviewRuntime) {
        $hairDeformation = Read-Json $hairDeformationPath "Source hair deformation probe"
        $hairDeformationSha = (Get-FileHash -LiteralPath $hairDeformationPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ([string]$hairDeformation.format -ne "bodyrig-hair-deformation-probe" -or [int]$hairDeformation.version -ne 1 -or
            [string]$hairDeformation.platform -ne "windows-unity-univrm" -or
            [string]$hairDeformation.bodyrig_revision -ne [string]$probe.bodyrig_revision -or
            [string]$hairDeformation.build_guid -ne [string]$probe.build_guid -or
            (Need-Sha256 ([string]$hairDeformation.package_sha256) "hair.package_sha256") -ne $reviewPackageSha -or
            (Need-Sha256 ([string]$hairDeformation.runtime_manifest_sha256) "hair.runtime_manifest_sha256") -ne $expectedRuntimeSha -or
            (Need-Sha256 ([string]$hairDeformation.avatar_sha256) "hair.avatar_sha256") -ne $reviewAvatarSha -or
            (Need-Sha256 ([string]$hairDeformation.bodyprint_sha256) "hair.bodyprint_sha256") -ne $reviewBodyprintSha -or
            [string]$hairDeformation.sequence_revision -ne "source-hair-head-turn-v1" -or
            [string]$hairDeformation.hair_node -ne "BodyRigSourceHairReview" -or
            [string]$hairDeformation.hair_mesh -ne "BodyRigSourceHairReviewMesh" -or
            [int]$hairDeformation.hair_bone_count -lt 1 -or [int]$hairDeformation.vertex_count -lt 3 -or
            $hairDeformation.skinned_mesh_renderer_found -ne $true -or
            $hairDeformation.head_bone_resolved -ne $true -or $hairDeformation.head_bone_bound -ne $true -or
            $hairDeformation.vertex_motion_observed -ne $true -or $hairDeformation.restored_neutral -ne $true -or
            $hairDeformation.complete -ne $true -or $hairDeformation.human_review_required -ne $true -or
            $hairDeformation.comparison_only -ne $true -or $hairDeformation.hair_component_authority -ne $false -or
            $hairDeformation.production_activation -ne $false) {
            throw "Source hair deformation probe is incomplete, stale or crossed the review-only authority boundary."
        }
        if ([double]$hairDeformation.observed_head_turn_degrees -lt 18.2 -or
            [double]$hairDeformation.vertex_motion_rms_m -lt 0.00025 -or
            [double]$hairDeformation.vertex_motion_max_m -lt 0.001 -or
            [double]$hairDeformation.restoration_rms_m -gt 0.00025 -or
            [double]$hairDeformation.restoration_max_m -gt 0.001) {
            throw "Source hair deformation metrics do not satisfy the canonical machine-evidence thresholds."
        }
    }

    if ([string]$manifest.format -ne "bodyrig-fidelity-render-set" -or [int]$manifest.version -ne 1 -or [string]$manifest.semantics -ne "visual-fidelity-not-identity-verification") {
        throw "Fidelity render-set manifest format/semantics mismatch."
    }
    if ([string]$manifest.body_id -ne [string]$probe.body_id -or (Need-Sha256 ([string]$manifest.package_sha256) "render-set.package_sha256") -ne (Need-Sha256 ([string]$probe.package_sha256) "probe.package_sha256")) {
        throw "Fidelity render-set is not bound to the exact comparison candidate."
    }
    $snapshots = @($manifest.snapshots)
    if ($snapshots.Count -ne 4) { throw "Fidelity render-set must contain exactly four canonical views." }
    $expectedViews = @("front-full", "three-quarter-full", "side-full", "face-front")
    $actualViews = @($snapshots | ForEach-Object { [string]$_.view })
    if (($actualViews -join ',') -ne ($expectedViews -join ',')) { throw "Fidelity render-set canonical view order mismatch." }
    foreach ($snapshot in $snapshots) {
        if ([int]$snapshot.width -ne 1024 -or [int]$snapshot.height -ne 1024) { throw "Fidelity snapshot dimensions must be 1024x1024." }
        $name = [string]$snapshot.file
        if ($name -ne ([string]$snapshot.view + ".png")) { throw "Fidelity snapshot filename/view binding mismatch." }
        $path = Join-Path $snapshotDir $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Fidelity snapshot missing: $path" }
        $expectedSha = Need-Sha256 ([string]$snapshot.sha256) "snapshot.sha256"
        $actualSha = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha -ne $expectedSha) { throw "Fidelity snapshot changed after renderer capture: $name" }
    }

    $comparison = [ordered]@{
        format = "bodyrig-fidelity-comparison-authority"
        version = 1
        authority = $comparisonAuthority
        bodyrig_revision = $acceptedRevision
        runtime_manifest_sha256 = $expectedRuntimeSha
        package_sha256 = Need-Sha256 ([string]$probe.package_sha256) "probe.package_sha256"
        physical_acceptance_authority = $usingAcceptance
        comparison_only = $true
        production_activation = $false
    }
    if ($usingReviewRuntime) {
        $comparison.review_runtime_authority_sha256 = $reviewRuntimeAuthoritySha
        $comparison.review_avatar_sha256 = $reviewAvatarSha
        $comparison.source_hair_runtime_applied = $true
        $comparison.source_eye_surface_applied = $true
        $comparison.corneal_material_status = "runtime-applied"
        $comparison.hair_deformation_probe_sha256 = Need-Sha256 $hairDeformationSha "hair deformation probe SHA"
        $comparison.hair_deformation_machine_pass = $true
        $comparison.hair_deformation_human_review_required = $true
    }
    $comparison | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $attempt "comparison-authority.json") -Encoding UTF8

    Move-Item -LiteralPath $attempt -Destination $OutputDir
    $committed = $true
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $attempt -PathType Container)) {
        Remove-Item -LiteralPath $attempt -Recurse -Force
    }
}

Write-Host "BodyRig fidelity comparison renders: PASS"
Write-Host "Candidate:  $([string]$probe.package_sha256)"
Write-Host "Output:     $OutputDir"
Write-Host "Authority:  $comparisonAuthority; comparison-only; no renderer/human/release acceptance was written"
if ($usingReviewRuntime) {
    Write-Host "Avatar:     source hair + source-baked eyes + runtime cornea"
    Write-Host "Hair move:  MACHINE PASS; human deformation review still required"
    Write-Host "Snapshots:  front-full / three-quarter-full / side-full / face-front"
}
exit 0
