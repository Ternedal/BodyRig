param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
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
$AcceptanceDir = [System.IO.Path]::GetFullPath($AcceptanceDir)
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Gate A acceptance directory not found: $AcceptanceDir" }
if (Test-Path -LiteralPath $OutputDir) { throw "Fidelity render output already exists; refusing cross-iteration reuse: $OutputDir" }

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
$currentHeadRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $currentHeadRaw.Count -ne 1) { throw "Could not resolve current BodyRig revision." }
$currentHead = Need-Revision ([string]$currentHeadRaw[0]) "current BodyRig HEAD"
if ($currentHead -ne $acceptedRevision) { throw "Current BodyRig checkout differs from Gate A candidate revision." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Fidelity rendering requires the exact clean Gate A checkout." }

if (-not (Test-Path -LiteralPath $runtimeManifest -PathType Leaf)) { throw "Gate A runtime manifest not found: $runtimeManifest" }
$expectedRuntimeSha = Need-Sha256 ([string]$acceptance.runtime.manifest_sha256) "acceptance.runtime.manifest_sha256"
$actualRuntimeSha = (Get-FileHash -LiteralPath $runtimeManifest -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualRuntimeSha -ne $expectedRuntimeSha) { throw "Gate A runtime manifest changed after acceptance." }

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

$parent = Split-Path -Parent $OutputDir
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw "Fidelity output parent does not exist: $parent" }
$attempt = Join-Path $parent (".bodyrig-fidelity-render-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attempt | Out-Null
$probePath = Join-Path $attempt "machine-probe.json"
$deformationPath = Join-Path $attempt "deformation-probe.json"
$snapshotDir = Join-Path $attempt "snapshots"
$committed = $false

try {
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
    $exitCode = Invoke-NativeProcessWait -FilePath $playerExe -ArgumentList $args
    if ($exitCode -ne 0) { throw "Fidelity reference player exited with code $exitCode" }

    $probe = Read-Json $probePath "Fidelity renderer machine probe"
    $deformation = Read-Json $deformationPath "Fidelity renderer deformation probe"
    $manifestPath = Join-Path $snapshotDir "fidelity-render-set.json"
    $manifest = Read-Json $manifestPath "Fidelity render-set manifest"

    if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [string]$probe.platform -ne "windows-unity-univrm") { throw "Fidelity machine probe format/platform mismatch." }
    if ((Need-Revision ([string]$probe.bodyrig_revision) "probe.bodyrig_revision") -ne $acceptedRevision) { throw "Fidelity player was not built from Gate A revision." }
    if ([string]$probe.unity_version -ne $expectedUnityVersion) { throw "Fidelity player Unity version does not match renderer contract." }
    if ((Need-Sha256 ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $actualRuntimeSha) { throw "Fidelity machine probe is not bound to Gate A runtime bytes." }
    if ([string]$deformation.bodyrig_revision -ne [string]$probe.bodyrig_revision -or [string]$deformation.build_guid -ne [string]$probe.build_guid -or $deformation.complete -ne $true) {
        throw "Fidelity deformation probe is not complete and build-bound to the machine probe."
    }

    if ([string]$manifest.format -ne "bodyrig-fidelity-render-set" -or [int]$manifest.version -ne 1 -or [string]$manifest.semantics -ne "visual-fidelity-not-identity-verification") {
        throw "Fidelity render-set manifest format/semantics mismatch."
    }
    if ([string]$manifest.body_id -ne [string]$probe.body_id -or (Need-Sha256 ([string]$manifest.package_sha256) "render-set.package_sha256") -ne (Need-Sha256 ([string]$probe.package_sha256) "probe.package_sha256")) {
        throw "Fidelity render-set is not bound to the exact Gate A candidate."
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
Write-Host "Authority:  comparison-only; no renderer/human/release acceptance was written"
exit 0
