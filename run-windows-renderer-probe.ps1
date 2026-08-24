param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$ProbeOutput = "",
    [string]$DeformationOutput = "",
    [string]$RendererName = "BodyRig Reference Renderer",
    [string]$RendererVersion = "reference-v1/univrm-0.131.2",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
}
function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical 40-character Git SHA." }
    return $normalized
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [System.IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }

$acceptancePath = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
$runtimeManifest = Join-Path (Join-Path $AcceptanceDir "runtime") "runtime-manifest.json"
foreach ($required in @($acceptancePath, $runtimeManifest)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required Gate A artifact missing: $required" }
}

try { $acceptance = Get-Content -LiteralPath $acceptancePath -Raw | ConvertFrom-Json } catch { throw "Gate A acceptance report is not valid JSON: $acceptancePath" }
if ([string]$acceptance.format -ne "bodyrig-rig-acceptance" -or [int]$acceptance.version -ne 1 -or $acceptance.automated_pass -ne $true -or $acceptance.production_activation -ne $false) {
    throw "Gate A acceptance is not a valid non-activating automated PASS."
}
$acceptedRevision = Need-Revision ([string]$acceptance.bodyrig_revision) "acceptance.bodyrig_revision"
$currentHeadLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $currentHeadLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
$currentHead = Need-Revision ([string]$currentHeadLines[0].Trim()) "current BodyRig HEAD"
if ($currentHead -ne $acceptedRevision) { throw "Current BodyRig checkout does not match Gate A revision; refusing Windows physical renderer evidence." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; Windows physical renderer evidence requires the exact clean Gate A revision." }

$expectedRuntimeHash = Need-Sha256 ([string]$acceptance.runtime.manifest_sha256) "acceptance.runtime.manifest_sha256"
$actualRuntimeHash = (Get-FileHash -LiteralPath $runtimeManifest -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualRuntimeHash -ne $expectedRuntimeHash) { throw "Runtime manifest bytes no longer match Gate A acceptance." }

$customProbe = -not [string]::IsNullOrWhiteSpace($ProbeOutput)
$customDeformation = -not [string]::IsNullOrWhiteSpace($DeformationOutput)
if ($customProbe -ne $customDeformation) { throw "Pass both -ProbeOutput and -DeformationOutput together, or neither." }
if (-not $customProbe) {
    $evidenceDir = Join-Path $AcceptanceDir "windows-evidence"
    $ProbeOutput = Join-Path $evidenceDir "windows-probe.json"
    $DeformationOutput = Join-Path $evidenceDir "windows-deformation-probe.json"
} else {
    $ProbeOutput = [System.IO.Path]::GetFullPath($ProbeOutput)
    $DeformationOutput = [System.IO.Path]::GetFullPath($DeformationOutput)
    $probeParent = Split-Path -Parent $ProbeOutput
    $deformationParent = Split-Path -Parent $DeformationOutput
    if (-not [string]::Equals($probeParent, $deformationParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Custom Windows probe/deformation outputs must share one dedicated evidence directory."
    }
    $evidenceDir = $probeParent
}
$evidenceDir = [System.IO.Path]::GetFullPath($evidenceDir)
$ProbeOutput = [System.IO.Path]::GetFullPath($ProbeOutput)
$DeformationOutput = [System.IO.Path]::GetFullPath($DeformationOutput)
if ([string]::Equals($ProbeOutput, $DeformationOutput, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Windows probe and deformation outputs must be distinct files." }
if (Test-Path -LiteralPath $evidenceDir) { throw "Windows canonical evidence directory already exists; refusing cross-attempt reuse: $evidenceDir" }
$evidenceParent = Split-Path -Parent $evidenceDir
if (-not (Test-Path -LiteralPath $evidenceParent -PathType Container)) { throw "Windows evidence parent directory not found: $evidenceParent" }

$attemptDir = Join-Path $evidenceParent (".bodyrig-windows-attempt-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attemptDir | Out-Null
$stagedProbe = Join-Path $attemptDir ([IO.Path]::GetFileName($ProbeOutput))
$stagedDeformation = Join-Path $attemptDir ([IO.Path]::GetFileName($DeformationOutput))
$committed = $false

try {
    $rendererRoot = Join-Path $repoRoot "reference-renderer"
    $buildScript = Join-Path $rendererRoot "build-reference-renderer.ps1"
    $playerExe = Join-Path $rendererRoot "Builds\Windows\BodyRigReferenceProbe.exe"
    if (-not $SkipBuild) {
        $buildArgs = @{ Platform = "Windows"; Output = $playerExe }
        if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $buildArgs.UnityExe = $UnityExe }
        & $buildScript @buildArgs
        if ($LASTEXITCODE -ne 0) { throw "BodyRig Windows reference renderer build failed with exit code $LASTEXITCODE" }
    }
    if (-not (Test-Path -LiteralPath $playerExe -PathType Leaf)) { throw "Built Windows reference renderer not found: $playerExe" }

    Write-Host "BodyRig Windows renderer Gate B physical probe"
    Write-Host "Revision:     $acceptedRevision"
    Write-Host "Runtime:      $runtimeManifest"
    Write-Host "Staging:      $attemptDir"
    Write-Host "Commit dir:   $evidenceDir"
    Write-Host "The player will cycle the fixed deformation sequence after evidence creation. Close it after visual inspection."

    & $playerExe `
        --bodyrig-runtime-manifest $runtimeManifest `
        --bodyrig-probe-output $stagedProbe `
        --bodyrig-deformation-output $stagedDeformation `
        --bodyrig-renderer-name $RendererName `
        --bodyrig-renderer-version $RendererVersion
    $playerExit = $LASTEXITCODE
    foreach ($required in @($stagedProbe, $stagedDeformation)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Windows player exited without producing the complete staged evidence pair (exit $playerExit): $required" }
    }

    try { $probe = Get-Content -LiteralPath $stagedProbe -Raw | ConvertFrom-Json } catch { throw "Windows machine probe is not valid JSON: $stagedProbe" }
    if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne "windows-unity-univrm" -or [string]$probe.unity_platform -ne "WindowsPlayer") { throw "Windows machine probe has the wrong format/platform." }
    if ((Need-Revision ([string]$probe.bodyrig_revision) "probe.bodyrig_revision") -ne $acceptedRevision) { throw "Windows player was not built from the exact Gate A BodyRig revision." }
    if ([string]::IsNullOrWhiteSpace([string]$probe.build_guid)) { throw "Windows machine probe has no Unity build GUID." }
    if ([string]$probe.active_renderer.name -ne $RendererName -or [string]$probe.active_renderer.version -ne $RendererVersion) { throw "Windows machine probe renderer identity does not match the requested build identity." }
    if ((Need-Sha256 ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $actualRuntimeHash) { throw "Windows machine probe does not identify the Gate A runtime manifest bytes." }

    try { $deformation = Get-Content -LiteralPath $stagedDeformation -Raw | ConvertFrom-Json } catch { throw "Windows deformation probe is not valid JSON: $stagedDeformation" }
    if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or [string]$deformation.platform -ne "windows-unity-univrm" -or [string]$deformation.unity_platform -ne "WindowsPlayer") { throw "Windows deformation probe has the wrong format/platform." }
    if ((Need-Revision ([string]$deformation.bodyrig_revision) "deformation.bodyrig_revision") -ne $acceptedRevision -or [string]$deformation.bodyrig_revision -ne [string]$probe.bodyrig_revision) { throw "Windows deformation evidence was not produced by the same exact BodyRig revision as Gate A/machine probe." }
    if ([string]$deformation.sequence_revision -ne "humanoid-muscle-sweep-v1" -or [int]$deformation.pose_count -ne 6 -or $deformation.required_muscles_resolved -ne $true -or $deformation.restored_neutral -ne $true -or $deformation.complete -ne $true -or $deformation.manual_review_required -ne $true) { throw "Windows deformation probe did not complete the fixed BodyRig pose sequence." }
    if ((Need-Sha256 ([string]$deformation.runtime_manifest_sha256) "deformation.runtime_manifest_sha256") -ne $actualRuntimeHash -or [string]$deformation.body_id -ne [string]$probe.body_id -or [string]$deformation.package_sha256 -ne [string]$probe.package_sha256 -or [string]$deformation.avatar_sha256 -ne [string]$probe.avatar_sha256 -or [string]$deformation.bodyprint_sha256 -ne [string]$probe.bodyprint_sha256 -or [string]$deformation.build_guid -ne [string]$probe.build_guid) { throw "Windows deformation evidence is not byte/build-bound to the renderer machine probe." }
    $poseIds = @($deformation.poses | ForEach-Object { [string]$_.id })
    if (($poseIds -join ',') -ne 'neutral,arms_abduction,elbows_flexed,arms_forward,left_leg_lift,knee_flexion') { throw "Windows deformation probe pose sequence/order mismatch." }

    Move-Item -LiteralPath $attemptDir -Destination $evidenceDir
    $committed = $true
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $attemptDir -PathType Container)) {
        Remove-Item -LiteralPath $attemptDir -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $ProbeOutput -PathType Leaf) -or -not (Test-Path -LiteralPath $DeformationOutput -PathType Leaf)) {
    throw "Windows evidence directory commit completed without both canonical files."
}
Write-Host "BodyRig Windows physical evidence: PASS | revision $acceptedRevision"
Write-Host "Evidence directory:   $evidenceDir"
Write-Host "Machine evidence:     $ProbeOutput"
Write-Host "Deformation evidence: $DeformationOutput"
Write-Host "Human visual attestation is still required with record-renderer-acceptance.ps1."
exit 0
