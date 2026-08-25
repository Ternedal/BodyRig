param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [Parameter(Mandatory = $true)][ValidateSet("windows-unity-univrm", "android-quest-class")][string]$Platform,
    [Parameter(Mandatory = $true)][switch]$ConfirmQualityChecklist,
    [Parameter(Mandatory = $true)][ValidateLength(1, 2000)][string]$QualityNote,
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig physical acceptance path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical BodyRig physical acceptance path."
}
$pwshAuthority = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwshAuthority) {
    throw "PowerShell 7 executable (pwsh) was not found for the canonical BodyRig physical acceptance path."
}

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    try { $value = Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $resolved" }
    return [pscustomobject]@{ Path = $resolved; Value = $value }
}

function Resolve-EvidencePair {
    param(
        [Parameter(Mandatory = $true)][string]$AcceptanceRoot,
        [Parameter(Mandatory = $true)][string]$Prefix
    )
    $canonicalDir = Join-Path $AcceptanceRoot "$Prefix-evidence"
    $canonicalProbe = Join-Path $canonicalDir "$Prefix-probe.json"
    $canonicalDeformation = Join-Path $canonicalDir "$Prefix-deformation-probe.json"
    $legacyProbe = Join-Path $AcceptanceRoot "$Prefix-probe.json"
    $legacyDeformation = Join-Path $AcceptanceRoot "$Prefix-deformation-probe.json"

    $canonicalExists = Test-Path -LiteralPath $canonicalDir -PathType Container
    $legacyAny = (Test-Path -LiteralPath $legacyProbe -PathType Leaf) -or (Test-Path -LiteralPath $legacyDeformation -PathType Leaf)

    if ($canonicalExists) {
        if ($legacyAny) { throw "$Prefix evidence is ambiguous: canonical and legacy layouts both exist." }
        if (-not (Test-Path -LiteralPath $canonicalProbe -PathType Leaf) -or -not (Test-Path -LiteralPath $canonicalDeformation -PathType Leaf)) {
            throw "$Prefix canonical evidence directory is incomplete; both machine and deformation reports are required."
        }
        return [pscustomobject]@{ Probe = $canonicalProbe; Deformation = $canonicalDeformation }
    }

    if (-not (Test-Path -LiteralPath $legacyProbe -PathType Leaf) -or -not (Test-Path -LiteralPath $legacyDeformation -PathType Leaf)) {
        throw "$Prefix physical evidence pair not found. Run the corresponding renderer probe first."
    }
    return [pscustomobject]@{ Probe = $legacyProbe; Deformation = $legacyDeformation }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [System.IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }
if (-not $ConfirmQualityChecklist) { throw "Reference renderer attestation requires explicit -ConfirmQualityChecklist after the full physical quality review." }
if ([string]::IsNullOrWhiteSpace($QualityNote)) { throw "QualityNote must contain the operator's physical review." }
$QualityNote = $QualityNote.Trim()

$contractFile = Read-JsonFile (Join-Path $repoRoot "reference-renderer\renderer-contract.json") "Reference renderer contract"
$contract = $contractFile.Value
$expectedContractFields = @("format","version","renderer_name","renderer_version","unity_editor_version","univrm_version","univrm_revision","application_id","deformation_sequence_revision")
if (@(Compare-Object -ReferenceObject $expectedContractFields -DifferenceObject @($contract.PSObject.Properties.Name)).Count -ne 0) { throw "Reference renderer contract fields are not canonical." }
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) { throw "Unsupported reference renderer contract format/version." }
foreach ($field in @("renderer_name","renderer_version","unity_editor_version","univrm_version","univrm_revision","application_id","deformation_sequence_revision")) {
    if ([string]::IsNullOrWhiteSpace([string]$contract.$field)) { throw "Reference renderer contract is missing '$field'." }
}
if ([string]$contract.univrm_revision -notmatch '^[0-9a-f]{40}$') { throw "Reference renderer contract contains an invalid UniVRM revision." }
if ([string]$contract.deformation_sequence_revision -ne "humanoid-muscle-sweep-v1") { throw "Reference renderer contract uses an unsupported deformation sequence." }

if ($Platform -eq "windows-unity-univrm") {
    $prefix = "windows"
    $defaultOutput = Join-Path $AcceptanceDir "bodyrig-renderer-acceptance-windows.json"
} else {
    $prefix = "quest"
    $defaultOutput = Join-Path $AcceptanceDir "bodyrig-renderer-acceptance-quest.json"
}
$pair = Resolve-EvidencePair -AcceptanceRoot $AcceptanceDir -Prefix $prefix
$probeFile = Read-JsonFile $pair.Probe "$prefix renderer machine probe"
$probe = $probeFile.Value
if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne $Platform) { throw "$prefix renderer machine probe format/platform mismatch." }
if ([string]$probe.active_renderer.name -ne [string]$contract.renderer_name -or [string]$probe.active_renderer.version -ne [string]$contract.renderer_version) {
    throw "$prefix renderer machine probe identity does not match reference-renderer/renderer-contract.json."
}
if ([string]$probe.unity_version -ne [string]$contract.unity_editor_version) {
    throw "$prefix renderer machine probe Unity version does not match the pinned reference renderer contract."
}

$deformationFile = Read-JsonFile $pair.Deformation "$prefix deformation probe"
$deformation = $deformationFile.Value
if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or [string]$deformation.platform -ne $Platform) { throw "$prefix deformation probe format/platform mismatch." }
if ([string]$deformation.sequence_revision -ne [string]$contract.deformation_sequence_revision) { throw "$prefix deformation sequence does not match the reference renderer contract." }
if ([string]$deformation.unity_version -ne [string]$contract.unity_editor_version) {
    throw "$prefix deformation probe Unity version does not match the pinned reference renderer contract."
}

$recordScript = Join-Path $repoRoot "record-renderer-acceptance.ps1"
if (-not (Test-Path -LiteralPath $recordScript -PathType Leaf)) { throw "Core renderer acceptance script not found: $recordScript" }
$acceptanceReport = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
$runtimeManifest = Join-Path (Join-Path $AcceptanceDir "runtime") "runtime-manifest.json"
if ([string]::IsNullOrWhiteSpace($Output)) { $Output = $defaultOutput }

$args = @{
    AcceptanceReport = $acceptanceReport
    RuntimeManifest = $runtimeManifest
    ProbeReport = $probeFile.Path
    DeformationReport = $deformationFile.Path
    Platform = $Platform
    Pass = $true
    ConfirmQualityChecklist = $true
    RendererName = [string]$contract.renderer_name
    RendererVersion = [string]$contract.renderer_version
    QualityNote = $QualityNote
    Output = $Output
}
& $recordScript @args
if ($LASTEXITCODE -ne 0) { throw "Core renderer acceptance failed with exit code $LASTEXITCODE." }

Write-Host "BodyRig reference renderer attestation: PASS | $Platform | quality=bodyrig-human-quality-v1"
Write-Host "Renderer: $($contract.renderer_name) | $($contract.renderer_version) | Unity $($contract.unity_editor_version) | UniVRM $($contract.univrm_revision)"
Write-Host "Evidence: $($probeFile.Path) + $($deformationFile.Path)"
exit 0
