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
$expectedRuntimeHash = Need-Sha256 ([string]$acceptance.runtime.manifest_sha256) "acceptance.runtime.manifest_sha256"
$actualRuntimeHash = (Get-FileHash -LiteralPath $runtimeManifest -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualRuntimeHash -ne $expectedRuntimeHash) { throw "Runtime manifest bytes no longer match Gate A acceptance." }

if ([string]::IsNullOrWhiteSpace($ProbeOutput)) { $ProbeOutput = Join-Path $AcceptanceDir "windows-probe.json" }
if ([string]::IsNullOrWhiteSpace($DeformationOutput)) { $DeformationOutput = Join-Path $AcceptanceDir "windows-deformation-probe.json" }
$ProbeOutput = [System.IO.Path]::GetFullPath($ProbeOutput)
$DeformationOutput = [System.IO.Path]::GetFullPath($DeformationOutput)
foreach ($output in @($ProbeOutput, $DeformationOutput)) {
    if (Test-Path -LiteralPath $output) { throw "Windows physical evidence already exists: $output" }
}

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
Write-Host "Runtime:      $runtimeManifest"
Write-Host "Machine:      $ProbeOutput"
Write-Host "Deformation:  $DeformationOutput"
Write-Host "The player will cycle the fixed deformation sequence after evidence creation. Close it after visual inspection."

& $playerExe `
    --bodyrig-runtime-manifest $runtimeManifest `
    --bodyrig-probe-output $ProbeOutput `
    --bodyrig-deformation-output $DeformationOutput `
    --bodyrig-renderer-name $RendererName `
    --bodyrig-renderer-version $RendererVersion
$playerExit = $LASTEXITCODE
foreach ($required in @($ProbeOutput, $DeformationOutput)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Windows player exited without producing required physical evidence (exit $playerExit): $required" }
}

try { $probe = Get-Content -LiteralPath $ProbeOutput -Raw | ConvertFrom-Json } catch { throw "Windows machine probe is not valid JSON: $ProbeOutput" }
if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne "windows-unity-univrm" -or [string]$probe.unity_platform -ne "WindowsPlayer") { throw "Windows machine probe has the wrong format/platform." }
if ([string]::IsNullOrWhiteSpace([string]$probe.build_guid)) { throw "Windows machine probe has no Unity build GUID." }
if ([string]$probe.active_renderer.name -ne $RendererName -or [string]$probe.active_renderer.version -ne $RendererVersion) { throw "Windows machine probe renderer identity does not match the requested build identity." }
if ((Need-Sha256 ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $actualRuntimeHash) { throw "Windows machine probe does not identify the Gate A runtime manifest bytes." }

try { $deformation = Get-Content -LiteralPath $DeformationOutput -Raw | ConvertFrom-Json } catch { throw "Windows deformation probe is not valid JSON: $DeformationOutput" }
if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or [string]$deformation.platform -ne "windows-unity-univrm" -or [string]$deformation.unity_platform -ne "WindowsPlayer") { throw "Windows deformation probe has the wrong format/platform." }
if ([string]$deformation.sequence_revision -ne "humanoid-muscle-sweep-v1" -or [int]$deformation.pose_count -ne 6 -or $deformation.required_muscles_resolved -ne $true -or $deformation.restored_neutral -ne $true -or $deformation.complete -ne $true -or $deformation.manual_review_required -ne $true) { throw "Windows deformation probe did not complete the fixed BodyRig pose sequence." }
if ((Need-Sha256 ([string]$deformation.runtime_manifest_sha256) "deformation.runtime_manifest_sha256") -ne $actualRuntimeHash -or [string]$deformation.body_id -ne [string]$probe.body_id -or [string]$deformation.package_sha256 -ne [string]$probe.package_sha256 -or [string]$deformation.avatar_sha256 -ne [string]$probe.avatar_sha256 -or [string]$deformation.bodyprint_sha256 -ne [string]$probe.bodyprint_sha256 -or [string]$deformation.build_guid -ne [string]$probe.build_guid) { throw "Windows deformation evidence is not byte/build-bound to the renderer machine probe." }
$poseIds = @($deformation.poses | ForEach-Object { [string]$_.id })
if (($poseIds -join ',') -ne 'neutral,arms_abduction,elbows_flexed,arms_forward,left_leg_lift,knee_flexion') { throw "Windows deformation probe pose sequence/order mismatch." }

Write-Host "BodyRig Windows physical evidence: PASS"
Write-Host "Machine evidence:     $ProbeOutput"
Write-Host "Deformation evidence: $DeformationOutput"
Write-Host "Human visual attestation is still required with record-renderer-acceptance.ps1."
exit 0
