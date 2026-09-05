param(
    [ValidateSet("Windows", "Quest")]
    [string]$Platform = "Windows",
    [string]$UnityExe = "",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-UnityEditor {
    param(
        [string]$Requested,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion
    )
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        if (-not (Test-Path -LiteralPath $Requested -PathType Leaf)) { throw "Unity.exe not found: $Requested" }
        return (Resolve-Path -LiteralPath $Requested).Path
    }

    $hubRoot = "C:\Program Files\Unity\Hub\Editor"
    $pinned = Join-Path $hubRoot "$ExpectedVersion\Editor\Unity.exe"
    if (Test-Path -LiteralPath $pinned -PathType Leaf) { return $pinned }
    throw "Pinned Unity editor $ExpectedVersion not found at $pinned. Install the exact renderer-contract version or pass -UnityExe for that exact version."
}

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $Path" }
}

function Need-Property {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { throw "$Label is missing '$Name'." }
    return $property.Value
}

function Assert-ResolvedPackageLock {
    param(
        [Parameter(Mandatory = $true)][string]$LockPath,
        [Parameter(Mandatory = $true)][string]$ExpectedUniVrmRevision
    )
    $lock = Read-JsonFile -Path $LockPath -Label "Resolved Unity packages lock"
    $dependencies = Need-Property -Object $lock -Name "dependencies" -Label "Resolved Unity packages lock"

    foreach ($name in @("com.vrmc.gltf", "com.vrmc.vrm")) {
        $entry = Need-Property -Object $dependencies -Name $name -Label "Resolved Unity packages lock dependencies"
        if ([string]$entry.source -ne "git") { throw "Resolved $name is not a Git dependency." }
        if ([string]$entry.hash -ne $ExpectedUniVrmRevision) { throw "Resolved $name Git hash does not match renderer-contract UniVRM revision." }
    }

    $expectedRegistry = [ordered]@{
        "com.unity.test-framework" = "1.6.0"
        "com.unity.mathematics" = "1.2.6"
        "com.unity.timeline" = "1.7.6"
    }
    foreach ($pair in $expectedRegistry.GetEnumerator()) {
        $entry = Need-Property -Object $dependencies -Name ([string]$pair.Key) -Label "Resolved Unity packages lock dependencies"
        if ([string]$entry.version -ne [string]$pair.Value) {
            throw "Resolved $($pair.Key) version '$($entry.version)' does not match the renderer package contract '$($pair.Value)'."
        }
    }

    return (Get-FileHash -LiteralPath $LockPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Copy-ReferenceProject {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($directory in @("Assets", "Packages", "ProjectSettings")) {
        $sourcePath = Join-Path $Source $directory
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) { throw "Reference renderer project is missing $directory/." }
        Copy-Item -LiteralPath $sourcePath -Destination $Destination -Recurse -Force
    }
}

function Invoke-UnityBatch {
    param(
        [Parameter(Mandatory = $true)][string]$UnityExe,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $UnityExe
    $startInfo.UseShellExecute = $false
    foreach ($argument in $Arguments) {
        [void]$startInfo.ArgumentList.Add([string]$argument)
    }

    $process = [System.Diagnostics.Process]::Start($startInfo)
    if ($null -eq $process) { throw "Unity batch process could not be started." }
    try {
        $process.WaitForExit()
        return [int]$process.ExitCode
    } finally {
        $process.Dispose()
    }
}

$projectRoot = (Resolve-Path $PSScriptRoot).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot "..")).Path
$contractPath = Join-Path $projectRoot "renderer-contract.json"
$contract = Read-JsonFile -Path $contractPath -Label "Reference renderer contract"
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) { throw "Unsupported reference renderer contract format/version." }
$expectedUnityVersion = ([string]$contract.unity_editor_version).Trim()
if ($expectedUnityVersion -notmatch '^6000\.3\.\d+f\d+$') { throw "Reference renderer contract contains an invalid Unity editor version." }
$expectedUniVrmVersion = ([string]$contract.univrm_version).Trim()
if ($expectedUniVrmVersion -notmatch '^\d+\.\d+\.\d+$') { throw "Reference renderer contract contains an invalid UniVRM version." }
$expectedUniVrmRevision = ([string]$contract.univrm_revision).Trim().ToLowerInvariant()
if ($expectedUniVrmRevision -notmatch '^[0-9a-f]{40}$') { throw "Reference renderer contract contains an invalid UniVRM revision." }
if ([string]$contract.renderer_version -notmatch [regex]::Escape("univrm-$expectedUniVrmVersion")) { throw "Renderer version does not identify the contracted UniVRM version." }
if ([string]$contract.application_id -ne "dk.ternedal.bodyrig.reference") { throw "Reference renderer contract contains an unsupported application id." }
if ([string]$contract.deformation_sequence_revision -ne "humanoid-muscle-sweep-v1") { throw "Reference renderer contract contains an unsupported deformation sequence revision." }

$projectVersionPath = Join-Path $projectRoot "ProjectSettings\ProjectVersion.txt"
if (-not (Test-Path -LiteralPath $projectVersionPath -PathType Leaf)) { throw "Reference renderer ProjectVersion.txt not found: $projectVersionPath" }
$projectVersionText = Get-Content -LiteralPath $projectVersionPath -Raw -Encoding UTF8
if ($projectVersionText -notmatch [regex]::Escape("m_EditorVersion: $expectedUnityVersion")) {
    throw "Reference renderer project version does not match renderer-contract Unity version $expectedUnityVersion."
}

$manifestPath = Join-Path $projectRoot "Packages\manifest.json"
$manifest = Read-JsonFile -Path $manifestPath -Label "Unity package manifest"
$expectedGltf = "https://github.com/vrm-c/UniVRM.git?path=/Packages/UniGLTF#$expectedUniVrmRevision"
$expectedVrm = "https://github.com/vrm-c/UniVRM.git?path=/Packages/VRM10#$expectedUniVrmRevision"
$gltfDependency = [string](Need-Property -Object $manifest.dependencies -Name "com.vrmc.gltf" -Label "Unity package manifest dependencies")
$vrmDependency = [string](Need-Property -Object $manifest.dependencies -Name "com.vrmc.vrm" -Label "Unity package manifest dependencies")
if ($gltfDependency -ne $expectedGltf -or $vrmDependency -ne $expectedVrm) {
    throw "Unity package manifest does not pin both UniVRM packages to renderer-contract revision $expectedUniVrmRevision."
}

$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve exact BodyRig Git HEAD before renderer build." }
$bodyRigRevision = ([string]$headLines[0]).Trim().ToLowerInvariant()
if ($bodyRigRevision -notmatch '^[0-9a-f]{40}$') { throw "BodyRig Git HEAD is not a canonical 40-character SHA." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness before renderer build." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; physical reference renderer must be built from an exact clean revision." }

$UnityExe = Resolve-UnityEditor -Requested $UnityExe -ExpectedVersion $expectedUnityVersion
$method = if ($Platform -eq "Windows") { "BodyRig.ReferenceRenderer.Editor.BodyRigReferenceBuild.BuildWindowsBatch" } else { "BodyRig.ReferenceRenderer.Editor.BodyRigReferenceBuild.BuildQuestBatch" }
$unityBuildTarget = if ($Platform -eq "Windows") { "StandaloneWindows64" } else { "Android" }
if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = if ($Platform -eq "Windows") {
        Join-Path $projectRoot "Builds\Windows\BodyRigReferenceProbe.exe"
    } else {
        Join-Path $projectRoot "Builds\Quest\BodyRigReferenceProbe.apk"
    }
}
$Output = [System.IO.Path]::GetFullPath($Output)

$tempBase = if (-not [string]::IsNullOrWhiteSpace($env:TEMP)) { $env:TEMP } else { [System.IO.Path]::GetTempPath() }
$tempRoot = Join-Path $tempBase ("BodyRig-reference-build-" + [Guid]::NewGuid().ToString("N"))
$tempProject = Join-Path $tempRoot "reference-renderer"
$packageLockHash = ""

Write-Host "BodyRig reference renderer build"
Write-Host "Unity:     $UnityExe"
Write-Host "Unity pin: $expectedUnityVersion"
Write-Host "UniVRM:    $expectedUniVrmVersion | $expectedUniVrmRevision"
Write-Host "Source:    $projectRoot"
Write-Host "Revision:  $bodyRigRevision"
Write-Host "Platform:  $Platform"
Write-Host "Unity target: $unityBuildTarget"
Write-Host "Output:    $Output"
Write-Host "Build workspace: ephemeral"

try {
    Copy-ReferenceProject -Source $projectRoot -Destination $tempProject

    $unityArguments = @(
        "-batchmode",
        "-quit",
        "-buildTarget", $unityBuildTarget,
        "-projectPath", $tempProject,
        "-executeMethod", $method,
        "-bodyrigOutput", $Output,
        "-bodyrigRevision", $bodyRigRevision,
        "-bodyrigUnityVersion", $expectedUnityVersion,
        "-logFile", "-"
    )
    $exitCode = Invoke-UnityBatch -UnityExe $UnityExe -Arguments $unityArguments
    if ($exitCode -ne 0) { throw "Unity BodyRig reference renderer build failed with exit code $exitCode" }
    if (-not (Test-Path -LiteralPath $Output -PathType Leaf)) { throw "Unity returned success but expected build output is missing: $Output" }

    $resolvedLock = Join-Path $tempProject "Packages\packages-lock.json"
    $packageLockHash = Assert-ResolvedPackageLock -LockPath $resolvedLock -ExpectedUniVrmRevision $expectedUniVrmRevision

    $dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not re-check BodyRig checkout after renderer build." }
    if ($dirtyAfter.Count -gt 0) { throw "Renderer build changed tracked/unignored BodyRig checkout state; refusing physical build evidence." }
    $currentHeadLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $currentHeadLines.Count -ne 1) { throw "Could not re-resolve BodyRig Git HEAD after renderer build." }
    $currentHead = ([string]$currentHeadLines[0]).Trim().ToLowerInvariant()
    if ($currentHead -ne $bodyRigRevision) { throw "BodyRig Git HEAD changed during renderer build." }
} finally {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ([string]::IsNullOrWhiteSpace($packageLockHash)) { throw "Unity package resolution was not validated." }
Write-Host "BodyRig reference renderer build: PASS | revision $bodyRigRevision | Unity $expectedUnityVersion | UniVRM $expectedUniVrmRevision | packages-lock $packageLockHash"
Write-Host $Output
exit 0
