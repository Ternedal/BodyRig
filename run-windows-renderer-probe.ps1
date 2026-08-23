param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$ProbeOutput = "",
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
$ProbeOutput = [System.IO.Path]::GetFullPath($ProbeOutput)
if (Test-Path -LiteralPath $ProbeOutput) { throw "Windows probe evidence already exists: $ProbeOutput" }

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

Write-Host "BodyRig Windows renderer Gate B machine probe"
Write-Host "Runtime: $runtimeManifest"
Write-Host "Probe:   $ProbeOutput"
Write-Host "Close the player after visual inspection; the script will then validate the probe file."

& $playerExe `
    --bodyrig-runtime-manifest $runtimeManifest `
    --bodyrig-probe-output $ProbeOutput `
    --bodyrig-renderer-name $RendererName `
    --bodyrig-renderer-version $RendererVersion
$playerExit = $LASTEXITCODE
if (-not (Test-Path -LiteralPath $ProbeOutput -PathType Leaf)) {
    throw "Windows player exited without producing machine probe evidence (exit $playerExit): $ProbeOutput"
}

try { $probe = Get-Content -LiteralPath $ProbeOutput -Raw | ConvertFrom-Json } catch { throw "Windows machine probe is not valid JSON: $ProbeOutput" }
if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne "windows-unity-univrm" -or [string]$probe.unity_platform -ne "WindowsPlayer") {
    throw "Windows machine probe has the wrong format/platform."
}
if ([string]::IsNullOrWhiteSpace([string]$probe.build_guid)) { throw "Windows machine probe has no Unity build GUID." }
if ([string]$probe.active_renderer.name -ne $RendererName -or [string]$probe.active_renderer.version -ne $RendererVersion) {
    throw "Windows machine probe renderer identity does not match the requested build identity."
}
if ((Need-Sha256 ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $actualRuntimeHash) {
    throw "Windows machine probe does not identify the Gate A runtime manifest bytes."
}

Write-Host "BodyRig Windows machine probe: PASS"
Write-Host "Machine evidence: $ProbeOutput"
Write-Host "Human visual attestation is still required with record-renderer-acceptance.ps1."
exit 0
