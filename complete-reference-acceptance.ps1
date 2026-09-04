param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
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
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    try { $value = Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $resolved" }
    return [pscustomobject]@{ Path = $resolved; Value = $value }
}

function Assert-CheckoutAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$ExpectedHead = ""
    )
    $headLines = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
    $head = ([string]$headLines[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "Current BodyRig Git revision is not canonical." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout revision changed while final release evidence was being written; expected $ExpectedHead, got $head."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
    if ($dirty.Count -gt 0) { throw "BodyRig checkout changed while final release evidence was being written; checkout is dirty." }
    return $head
}

function Assert-QualityReview {
    param([Parameter(Mandatory = $true)]$Attestation,[Parameter(Mandatory = $true)][string]$Label)
    $review = $Attestation.quality_review
    if ($null -eq $review) { throw "$Label human quality review is missing." }
    $expectedFields = @(
        "revision",
        "full_deformation_sequence_reviewed",
        "source_identity_texture_acceptable",
        "geometry_proportions_acceptable",
        "upper_body_deformation_acceptable",
        "lower_body_deformation_acceptable",
        "cross_limb_leakage_absent",
        "skin_qa_considered"
    )
    if (@(Compare-Object -ReferenceObject $expectedFields -DifferenceObject @($review.PSObject.Properties.Name)).Count -ne 0) {
        throw "$Label human quality review fields are not canonical."
    }
    if ([string]$review.revision -ne "bodyrig-human-quality-v1") { throw "$Label human quality review revision mismatch." }
    foreach ($field in $expectedFields | Where-Object { $_ -ne "revision" }) {
        if ($review.$field -ne $true) { throw "$Label human quality review did not explicitly pass '$field'." }
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }
$initialHead = Assert-CheckoutAuthority -RepoRoot $repoRoot

$contract = (Read-JsonFile (Join-Path $repoRoot "reference-renderer\renderer-contract.json") "Reference renderer contract").Value
$expectedContractFields = @("format","version","renderer_name","renderer_version","unity_editor_version","univrm_version","univrm_revision","application_id","deformation_sequence_revision")
if (@(Compare-Object -ReferenceObject $expectedContractFields -DifferenceObject @($contract.PSObject.Properties.Name)).Count -ne 0) { throw "Reference renderer contract fields are not canonical." }
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) { throw "Unsupported reference renderer contract format/version." }
foreach ($field in @("renderer_name","renderer_version","unity_editor_version","univrm_version","univrm_revision","application_id","deformation_sequence_revision")) {
    if ([string]::IsNullOrWhiteSpace([string]$contract.$field)) { throw "Reference renderer contract is missing '$field'." }
}
if ([string]$contract.univrm_revision -notmatch '^[0-9a-f]{40}$') { throw "Reference renderer contract contains an invalid UniVRM revision." }
if ([string]$contract.deformation_sequence_revision -ne "humanoid-muscle-sweep-v1") { throw "Reference renderer contract uses an unsupported deformation sequence." }

$acceptanceReport = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
$windowsProbe = Join-Path $AcceptanceDir "windows-evidence\windows-probe.json"
$windowsDeformation = Join-Path $AcceptanceDir "windows-evidence\windows-deformation-probe.json"
$windowsAttestation = Join-Path $AcceptanceDir "bodyrig-renderer-acceptance-windows.json"
$questProbe = Join-Path $AcceptanceDir "quest-evidence\quest-probe.json"
$questDeformation = Join-Path $AcceptanceDir "quest-evidence\quest-deformation-probe.json"
$questAttestation = Join-Path $AcceptanceDir "bodyrig-renderer-acceptance-quest.json"

$legacyPaths = @(
    (Join-Path $AcceptanceDir "windows-probe.json"),
    (Join-Path $AcceptanceDir "windows-deformation-probe.json"),
    (Join-Path $AcceptanceDir "quest-probe.json"),
    (Join-Path $AcceptanceDir "quest-deformation-probe.json")
)
foreach ($legacy in $legacyPaths) {
    if (Test-Path -LiteralPath $legacy -PathType Leaf) { throw "Canonical reference release refuses legacy root renderer evidence: $legacy" }
}

$platforms = @(
    [pscustomobject]@{ Name="Windows"; Platform="windows-unity-univrm"; Probe=$windowsProbe; Deformation=$windowsDeformation; Attestation=$windowsAttestation },
    [pscustomobject]@{ Name="Quest"; Platform="android-quest-class"; Probe=$questProbe; Deformation=$questDeformation; Attestation=$questAttestation }
)

foreach ($entry in $platforms) {
    $probe = (Read-JsonFile $entry.Probe "$($entry.Name) renderer machine probe").Value
    $deformation = (Read-JsonFile $entry.Deformation "$($entry.Name) deformation probe").Value
    $attestation = (Read-JsonFile $entry.Attestation "$($entry.Name) renderer attestation").Value

    if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne $entry.Platform) { throw "$($entry.Name) renderer probe format/platform mismatch." }
    if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or [string]$deformation.platform -ne $entry.Platform) { throw "$($entry.Name) deformation probe format/platform mismatch." }
    if ([string]$attestation.format -ne "bodyrig-renderer-acceptance" -or [int]$attestation.version -ne 1 -or [string]$attestation.platform -ne $entry.Platform -or [string]$attestation.result -ne "pass") { throw "$($entry.Name) renderer attestation is not a PASS for the expected platform." }

    if ([string]$probe.active_renderer.name -ne [string]$contract.renderer_name -or [string]$probe.active_renderer.version -ne [string]$contract.renderer_version) { throw "$($entry.Name) machine probe renderer identity does not match renderer-contract.json." }
    if ([string]$attestation.renderer_name -ne [string]$contract.renderer_name -or [string]$attestation.renderer_version -ne [string]$contract.renderer_version) { throw "$($entry.Name) human attestation renderer identity does not match renderer-contract.json." }
    if ([string]$probe.unity_version -ne [string]$contract.unity_editor_version -or [string]$deformation.unity_version -ne [string]$contract.unity_editor_version -or [string]$attestation.unity_version -ne [string]$contract.unity_editor_version) { throw "$($entry.Name) renderer evidence does not use the exact contract-pinned Unity version." }
    if ([string]$deformation.sequence_revision -ne [string]$contract.deformation_sequence_revision -or [string]$attestation.deformation_sequence_revision -ne [string]$contract.deformation_sequence_revision) { throw "$($entry.Name) renderer evidence does not use the contract-pinned deformation sequence." }
    Assert-QualityReview -Attestation $attestation -Label $entry.Name
}

$core = Join-Path $repoRoot "complete-acceptance.ps1"
if (-not (Test-Path -LiteralPath $core -PathType Leaf)) { throw "Core final acceptance script not found: $core" }
$args = @{
    AcceptanceReport = $acceptanceReport
    WindowsRendererReport = $windowsAttestation
    WindowsProbeReport = $windowsProbe
    WindowsDeformationReport = $windowsDeformation
    QuestRendererReport = $questAttestation
    QuestProbeReport = $questProbe
    QuestDeformationReport = $questDeformation
}
if ([string]::IsNullOrWhiteSpace($Output)) {
    $authoritativeOutput = Join-Path $AcceptanceDir "bodyrig-release-acceptance.json"
} else {
    $authoritativeOutput = [IO.Path]::GetFullPath($Output)
    $args.Output = $authoritativeOutput
}
& $core @args
if ($LASTEXITCODE -ne 0) { throw "Core final acceptance failed with exit code $LASTEXITCODE." }

try {
    [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)
} catch {
    if (Test-Path -LiteralPath $authoritativeOutput -PathType Leaf) {
        Remove-Item -LiteralPath $authoritativeOutput -Force
    }
    throw "BodyRig checkout authority changed after final release evidence write; removed non-authoritative output '$authoritativeOutput'. $($_.Exception.Message)"
}

Write-Host "BodyRig reference release acceptance: PASS | renderer $($contract.renderer_version) | Unity $($contract.unity_editor_version) | UniVRM $($contract.univrm_revision) | quality=bodyrig-human-quality-v1"
exit 0
