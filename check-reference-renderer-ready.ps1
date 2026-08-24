param(
    [string]$UnityExe = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $Path" }
}

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Reference renderer physical readiness must be checked on the target Windows rig."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for reference renderer physical readiness."
}

$contractPath = Join-Path $repoRoot "reference-renderer\renderer-contract.json"
$contract = Read-JsonFile -Path $contractPath -Label "Reference renderer contract"
$expectedFields = @("format","version","renderer_name","renderer_version","unity_editor_version","univrm_version","univrm_revision","application_id","deformation_sequence_revision")
if (@(Compare-Object -ReferenceObject $expectedFields -DifferenceObject @($contract.PSObject.Properties.Name)).Count -ne 0) { throw "Reference renderer contract fields are not canonical." }
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) { throw "Unsupported reference renderer contract format/version." }
$unityVersion = ([string]$contract.unity_editor_version).Trim()
$univrmRevision = ([string]$contract.univrm_revision).Trim().ToLowerInvariant()
if ($unityVersion -notmatch '^6000\.3\.\d+f\d+$') { throw "Reference renderer contract has an invalid Unity version." }
if ($univrmRevision -notmatch '^[0-9a-f]{40}$') { throw "Reference renderer contract has an invalid UniVRM revision." }
if ([string]$contract.application_id -ne "dk.ternedal.bodyrig.reference") { throw "Reference renderer contract has an unsupported application id." }

$projectVersionPath = Need-File -Path (Join-Path $repoRoot "reference-renderer\ProjectSettings\ProjectVersion.txt") -Label "Reference renderer ProjectVersion.txt"
$projectVersionText = Get-Content -LiteralPath $projectVersionPath -Raw -Encoding UTF8
if ($projectVersionText -notmatch [regex]::Escape("m_EditorVersion: $unityVersion")) { throw "Reference renderer project version does not match renderer-contract Unity version $unityVersion." }

if ([string]::IsNullOrWhiteSpace($UnityExe)) {
    $UnityExe = "C:\Program Files\Unity\Hub\Editor\$unityVersion\Editor\Unity.exe"
}
$UnityExe = Need-File -Path $UnityExe -Label "Pinned Unity editor"
$editorDir = Split-Path -Parent $UnityExe
$dataDir = Need-Directory -Path (Join-Path $editorDir "Data") -Label "Unity editor Data directory"
$androidPlayer = Need-Directory -Path (Join-Path $dataDir "PlaybackEngines\AndroidPlayer") -Label "Unity Android Build Support"
$sdk = Need-Directory -Path (Join-Path $androidPlayer "SDK") -Label "Unity Android SDK"
$ndk = Need-Directory -Path (Join-Path $androidPlayer "NDK") -Label "Unity Android NDK"
$openJdk = Need-Directory -Path (Join-Path $androidPlayer "OpenJDK") -Label "Unity Android OpenJDK"
$adb = Need-File -Path (Join-Path $sdk "platform-tools\adb.exe") -Label "Unity Android adb"

$git = Get-Command git -ErrorAction SilentlyContinue
if ($null -eq $git -or [string]::IsNullOrWhiteSpace([string]$git.Source)) {
    throw "Git executable is required because the pinned UniVRM packages are resolved through Unity Package Manager Git dependencies."
}

$manifestPath = Join-Path $repoRoot "reference-renderer\Packages\manifest.json"
$manifest = Read-JsonFile -Path $manifestPath -Label "Reference renderer package manifest"
$expectedDependencies = [ordered]@{
    "com.unity.mathematics" = "1.2.6"
    "com.unity.test-framework" = "1.4.6"
    "com.unity.timeline" = "1.7.6"
    "com.vrmc.gltf" = "https://github.com/vrm-c/UniVRM.git?path=/Packages/UniGLTF#$univrmRevision"
    "com.vrmc.vrm" = "https://github.com/vrm-c/UniVRM.git?path=/Packages/VRM10#$univrmRevision"
}
if (@(Compare-Object -ReferenceObject @($expectedDependencies.Keys) -DifferenceObject @($manifest.dependencies.PSObject.Properties.Name)).Count -ne 0) {
    throw "Reference renderer package manifest dependency set is not canonical."
}
foreach ($pair in $expectedDependencies.GetEnumerator()) {
    $actual = [string]$manifest.dependencies.PSObject.Properties[[string]$pair.Key].Value
    if ($actual -ne [string]$pair.Value) { throw "Reference renderer dependency $($pair.Key) is not pinned to '$($pair.Value)'." }
}

Write-Host "BodyRig reference renderer toolchain: READY"
Write-Host "Unity:   $unityVersion | $UnityExe"
Write-Host "UniVRM:  $($contract.univrm_version) | $univrmRevision"
Write-Host "Android: SDK=$sdk | NDK=$ndk | OpenJDK=$openJdk | adb=$adb"
Write-Host "Git:     $($git.Source)"
Write-Host "No Unity project was opened and no physical evidence was created."
exit 0
