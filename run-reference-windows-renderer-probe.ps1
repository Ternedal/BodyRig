param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
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

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }

$contractPath = Join-Path $repoRoot "reference-renderer\renderer-contract.json"
$contract = Read-JsonFile $contractPath "Reference renderer contract"
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) { throw "Unsupported reference renderer contract format/version." }
foreach ($field in @("renderer_name","renderer_version","unity_editor_version","deformation_sequence_revision")) {
    if ([string]::IsNullOrWhiteSpace([string]$contract.$field)) { throw "Reference renderer contract is missing '$field'." }
}
if ([string]$contract.deformation_sequence_revision -ne "humanoid-muscle-sweep-v1") { throw "Reference renderer contract has an unsupported deformation sequence." }

$canonicalDir = Join-Path $AcceptanceDir "windows-evidence"
if (Test-Path -LiteralPath $canonicalDir) { throw "Windows canonical evidence directory already exists; refusing cross-attempt reuse: $canonicalDir" }
$stageDir = Join-Path $AcceptanceDir (".bodyrig-windows-contract-stage-" + [Guid]::NewGuid().ToString("N"))
$stagedProbe = Join-Path $stageDir "windows-probe.json"
$stagedDeformation = Join-Path $stageDir "windows-deformation-probe.json"
$committed = $false

try {
    $inner = Join-Path $repoRoot "run-windows-renderer-probe.ps1"
    if (-not (Test-Path -LiteralPath $inner -PathType Leaf)) { throw "Windows renderer probe wrapper not found: $inner" }
    $args = @{
        AcceptanceDir = $AcceptanceDir
        ProbeOutput = $stagedProbe
        DeformationOutput = $stagedDeformation
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $args.UnityExe = $UnityExe }
    & $inner @args
    if ($LASTEXITCODE -ne 0) { throw "Windows physical probe failed with exit code $LASTEXITCODE." }

    $probe = Read-JsonFile $stagedProbe "Windows staged machine probe"
    $deformation = Read-JsonFile $stagedDeformation "Windows staged deformation probe"
    if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne "windows-unity-univrm" -or [string]$probe.unity_platform -ne "WindowsPlayer") { throw "Windows staged machine probe format/platform mismatch." }
    if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or [string]$deformation.platform -ne "windows-unity-univrm" -or [string]$deformation.unity_platform -ne "WindowsPlayer") { throw "Windows staged deformation probe format/platform mismatch." }
    if ([string]$probe.active_renderer.name -ne [string]$contract.renderer_name -or [string]$probe.active_renderer.version -ne [string]$contract.renderer_version) { throw "Windows staged renderer identity does not match renderer-contract.json." }
    if ([string]$probe.unity_version -ne [string]$contract.unity_editor_version -or [string]$deformation.unity_version -ne [string]$contract.unity_editor_version) { throw "Windows staged evidence was not produced by the pinned Unity version." }
    if ([string]$deformation.sequence_revision -ne [string]$contract.deformation_sequence_revision) { throw "Windows staged deformation sequence does not match renderer-contract.json." }
    if ([string]$probe.bodyrig_revision -ne [string]$deformation.bodyrig_revision -or [string]$probe.build_guid -ne [string]$deformation.build_guid) { throw "Windows staged evidence pair does not share build revision/GUID." }

    Move-Item -LiteralPath $stageDir -Destination $canonicalDir
    $committed = $true
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $stageDir -PathType Container)) {
        Remove-Item -LiteralPath $stageDir -Recurse -Force
    }
}

Write-Host "BodyRig contract-bound Windows evidence: PASS | Unity $($contract.unity_editor_version)"
Write-Host "Evidence directory: $canonicalDir"
Write-Host "Human visual attestation is still required with record-reference-renderer-acceptance.ps1."
exit 0
