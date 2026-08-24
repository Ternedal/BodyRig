param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$AdbExe = "adb",
    [string]$Serial = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $Path" }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }

$contractPath = Join-Path $repoRoot "reference-renderer\renderer-contract.json"
$contract = Read-JsonFile $contractPath "Reference renderer contract"
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) { throw "Unsupported reference renderer contract format/version." }
foreach ($field in @("renderer_name","renderer_version","unity_editor_version","application_id","deformation_sequence_revision")) {
    if ([string]::IsNullOrWhiteSpace([string]$contract.$field)) { throw "Reference renderer contract is missing '$field'." }
}
if ([string]$contract.application_id -ne "dk.ternedal.bodyrig.reference") { throw "Reference renderer contract has an unsupported Quest application id." }
if ([string]$contract.deformation_sequence_revision -ne "humanoid-muscle-sweep-v1") { throw "Reference renderer contract has an unsupported deformation sequence." }

$canonicalDir = Join-Path $AcceptanceDir "quest-evidence"
if (Test-Path -LiteralPath $canonicalDir) { throw "Quest canonical evidence directory already exists; refusing cross-attempt reuse: $canonicalDir" }
$stageDir = Join-Path $AcceptanceDir (".bodyrig-quest-contract-stage-" + [Guid]::NewGuid().ToString("N"))
$stagedProbe = Join-Path $stageDir "quest-probe.json"
$stagedDeformation = Join-Path $stageDir "quest-deformation-probe.json"
$committed = $false

try {
    $inner = Join-Path $repoRoot "run-quest-renderer-probe.ps1"
    if (-not (Test-Path -LiteralPath $inner -PathType Leaf)) { throw "Quest renderer probe wrapper not found: $inner" }
    $args = @{
        AcceptanceDir = $AcceptanceDir
        AdbExe = $AdbExe
        ProbeOutput = $stagedProbe
        DeformationOutput = $stagedDeformation
        SkipBuild = $SkipBuild
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $args.UnityExe = $UnityExe }
    if (-not [string]::IsNullOrWhiteSpace($Serial)) { $args.Serial = $Serial }
    & $inner @args
    if ($LASTEXITCODE -ne 0) { throw "Quest physical probe failed with exit code $LASTEXITCODE." }

    $probe = Read-JsonFile $stagedProbe "Quest staged machine probe"
    $deformation = Read-JsonFile $stagedDeformation "Quest staged deformation probe"
    if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne "android-quest-class") { throw "Quest staged machine probe format/platform mismatch." }
    if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or [string]$deformation.platform -ne "android-quest-class") { throw "Quest staged deformation probe format/platform mismatch." }
    if ([string]$probe.active_renderer.name -ne [string]$contract.renderer_name -or [string]$probe.active_renderer.version -ne [string]$contract.renderer_version) { throw "Quest staged renderer identity does not match renderer-contract.json." }
    if ([string]$probe.unity_version -ne [string]$contract.unity_editor_version -or [string]$deformation.unity_version -ne [string]$contract.unity_editor_version) { throw "Quest staged evidence was not produced by the pinned Unity version." }
    if ([string]$deformation.sequence_revision -ne [string]$contract.deformation_sequence_revision) { throw "Quest staged deformation sequence does not match renderer-contract.json." }
    if ([string]$probe.bodyrig_revision -ne [string]$deformation.bodyrig_revision -or [string]$probe.build_guid -ne [string]$deformation.build_guid) { throw "Quest staged evidence pair does not share build revision/GUID." }

    Move-Item -LiteralPath $stageDir -Destination $canonicalDir
    $committed = $true
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $stageDir -PathType Container)) {
        Remove-Item -LiteralPath $stageDir -Recurse -Force
    }
}

Write-Host "BodyRig contract-bound Quest evidence: PASS | Unity $($contract.unity_editor_version)"
Write-Host "Evidence directory: $canonicalDir"
Write-Host "Human visual attestation is still required with record-reference-renderer-acceptance.ps1."
exit 0
