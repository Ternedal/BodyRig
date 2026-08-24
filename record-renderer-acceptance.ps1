param(
    [Parameter(Mandatory = $true)][string]$AcceptanceReport,
    [Parameter(Mandatory = $true)][string]$RuntimeManifest,
    [Parameter(Mandatory = $true)][string]$ProbeReport,
    [Parameter(Mandatory = $true)][string]$DeformationReport,
    [Parameter(Mandatory = $true)][ValidateSet("windows-unity-univrm", "android-quest-class")][string]$Platform,
    [Parameter(Mandatory = $true)][switch]$Pass,
    [Parameter(Mandatory = $true)][ValidateLength(1, 160)][string]$RendererName,
    [Parameter(Mandatory = $true)][ValidateLength(1, 160)][string]$RendererVersion,
    [Parameter(Mandatory = $true)][ValidateLength(1, 2000)][string]$QualityNote,
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Read-JsonFile {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    try { $value = Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $resolved" }
    return [pscustomobject]@{ Path = $resolved; Value = $value }
}
function Sha256([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Require-Sha([string]$Value, [string]$Field) {
    $v = $Value.ToLowerInvariant(); if ($v -notmatch '^[0-9a-f]{64}$') { throw "$Field is not a canonical SHA-256." }; return $v
}
function Read-PackageJson([string]$PackagePath,[string]$EntryName,[string]$Label) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($PackagePath)
    try {
        $entry = $archive.GetEntry($EntryName); if ($null -eq $entry) { throw "Accepted .mrbody has no $EntryName." }
        $stream = $entry.Open(); $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true, 4096, $false)
        try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
        try { return $text | ConvertFrom-Json } catch { throw "Accepted .mrbody $Label is invalid JSON." }
    } finally { $archive.Dispose() }
}

foreach ($value in @($RendererName, $RendererVersion, $QualityNote)) { if ([string]::IsNullOrWhiteSpace($value)) { throw "RendererName, RendererVersion and QualityNote must contain non-whitespace text." } }
$RendererName = $RendererName.Trim(); $RendererVersion = $RendererVersion.Trim(); $QualityNote = $QualityNote.Trim()
if (-not $Pass) { throw "Renderer acceptance requires an explicit -Pass attestation." }

$acceptanceFile = Read-JsonFile $AcceptanceReport "Acceptance report"; $AcceptanceReport = $acceptanceFile.Path; $report = $acceptanceFile.Value; $reportDir = Split-Path -Parent $AcceptanceReport
if ([string]$report.format -ne "bodyrig-rig-acceptance" -or [int]$report.version -ne 1) { throw "Unsupported BodyRig acceptance report format/version." }
if ($report.automated_pass -ne $true -or $report.production_activation -ne $false -or [string]$report.physical_renderer_acceptance -ne "pending") { throw "Automated rig acceptance is not in a valid pending-renderer PASS state." }
if ([string]$report.runtime.manifest -ne "runtime/runtime-manifest.json" -or $report.runtime.materialized_from_package -ne $true) { throw "Automated acceptance does not contain valid materialized runtime evidence." }
if ($report.package.placeholder_avatar -ne $false) { throw "Renderer acceptance requires a non-placeholder high-fidelity package." }
if ([string]$report.physical_clone.mode -ne "stash-sith-high-fidelity") { throw "Renderer acceptance requires Stash/SiTH physical-clone lineage." }
$acceptedSessionHash = Require-Sha ([string]$report.physical_clone.session_sha256) "physical_clone.session_sha256"
$acceptedReadinessHash = Require-Sha ([string]$report.physical_clone.readiness_sha256) "physical_clone.readiness_sha256"
$acceptedSkinQaHash = Require-Sha ([string]$report.skin_qa.report_sha256) "skin_qa.report_sha256"
if ($report.skin_qa.structural_pass -ne $true -or $report.skin_qa.manual_review_required -ne $true -or [string]$report.skin_qa.automated_assessment -notin @("low-risk","review","high-risk")) { throw "Gate A skin QA state is invalid." }
$sessionEvidencePath = Join-Path $reportDir "bodyrig-physical-clone-session.json"
$readinessEvidencePath = Join-Path $reportDir "bodyrig-rig-readiness.json"
$skinQaEvidencePath = Join-Path $reportDir "bodyrig-skin-qa.json"
if (-not (Test-Path -LiteralPath $sessionEvidencePath -PathType Leaf) -or (Sha256 $sessionEvidencePath) -ne $acceptedSessionHash) { throw "Physical clone session evidence is missing or changed." }
if (-not (Test-Path -LiteralPath $readinessEvidencePath -PathType Leaf) -or (Sha256 $readinessEvidencePath) -ne $acceptedReadinessHash) { throw "Physical clone readiness evidence is missing or changed." }
if (-not (Test-Path -LiteralPath $skinQaEvidencePath -PathType Leaf) -or (Sha256 $skinQaEvidencePath) -ne $acceptedSkinQaHash) { throw "Anatomical skin QA evidence is missing or changed." }
$acceptedRuntimeManifestHash = Require-Sha ([string]$report.runtime.manifest_sha256) "runtime.manifest_sha256"

$repoRoot = (Resolve-Path $PSScriptRoot).Path; $head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Could not read BodyRig Git HEAD." }
if (([string]$report.bodyrig_revision).ToLowerInvariant() -ne $head) { throw "BodyRig HEAD does not match the automated acceptance revision." }
if (@(& git -C $repoRoot status --porcelain).Count -gt 0) { throw "BodyRig checkout is dirty; renderer attestation requires the exact clean accepted revision." }

$bodyId = [string]$report.package.body_id; if ([string]::IsNullOrWhiteSpace($bodyId) -or $bodyId -notmatch '^[a-z0-9æøå_-]{1,160}$') { throw "Acceptance report contains an invalid body id." }
$packagePath = Join-Path $reportDir "$bodyId.mrbody"; if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) { throw "Accepted .mrbody package not found beside report: $packagePath" }; $packagePath = (Resolve-Path $packagePath).Path
$actualPackageHash = Sha256 $packagePath; if ($actualPackageHash -ne (Require-Sha ([string]$report.package.package_sha256) "package.package_sha256")) { throw "Accepted .mrbody SHA-256 no longer matches automated acceptance." }
$skinQaFile = Read-JsonFile $skinQaEvidencePath "Anatomical skin QA report"; $skinQa = $skinQaFile.Value
if ([string]$skinQa.format -ne "bodyrig-skin-qa" -or [int]$skinQa.version -ne 1 -or [string]$skinQa.body_id -ne $bodyId -or (Require-Sha ([string]$skinQa.package_sha256) "skin QA package hash") -ne $actualPackageHash) { throw "Anatomical skin QA identity does not match the accepted package." }
if ($skinQa.structural_pass -ne $true -or $skinQa.manual_review_required -ne $true -or [string]$skinQa.automated_assessment -ne [string]$report.skin_qa.automated_assessment) { throw "Anatomical skin QA report no longer matches Gate A." }

$provenance = Read-PackageJson $packagePath "provenance.json" "provenance.json"
$visualStages = @($provenance.pipeline | Where-Object { [string]$_.stage -eq "visual-identity-capture" })
$fittingStages = @($provenance.pipeline | Where-Object { [string]$_.stage -eq "avatar-fitting" })
if ($visualStages.Count -ne 1) { throw "Accepted .mrbody does not contain exactly one visual-identity-capture provenance stage." }
if ($fittingStages.Count -ne 1 -or [string]$fittingStages[0].adapter -ne "sith-smplx-vrm" -or [string]$fittingStages[0].revision -ne "1") { throw "Accepted .mrbody was not produced by the built-in sith-smplx-vrm v1 fitter." }
$reportHash = Sha256 $AcceptanceReport

$runtimeFile = Read-JsonFile $RuntimeManifest "Runtime manifest"; $RuntimeManifest = $runtimeFile.Path; $runtime = $runtimeFile.Value
$expectedRuntimeFields = @("format","version","body_id","body_name","package_sha256","avatar","bodyprint","payloads")
if (@(Compare-Object -ReferenceObject $expectedRuntimeFields -DifferenceObject @($runtime.PSObject.Properties.Name)).Count -ne 0) { throw "Runtime manifest fields do not match BodyRig runtime assets v1." }
if ([string]$runtime.format -ne "bodyrig-runtime-assets" -or [int]$runtime.version -ne 1 -or [string]$runtime.body_id -ne $bodyId -or ([string]$runtime.package_sha256).ToLowerInvariant() -ne $actualPackageHash) { throw "Runtime manifest identity does not match automated acceptance." }
if ([string]$runtime.avatar -ne "avatar.vrm" -or [string]$runtime.bodyprint -ne "bodyprint.json") { throw "Runtime manifest contains unexpected avatar/bodyprint paths." }
if (@($runtime.payloads) -notcontains "avatar.vrm" -or @($runtime.payloads) -notcontains "bodyprint.json") { throw "Runtime manifest does not include required avatar/bodyprint payloads." }
$runtimeManifestHash = Sha256 $RuntimeManifest; if ($runtimeManifestHash -ne $acceptedRuntimeManifestHash) { throw "Runtime manifest SHA-256 no longer matches Gate A." }

$runtimeDir = Split-Path -Parent $RuntimeManifest; $avatarPath = Join-Path $runtimeDir "avatar.vrm"; $bodyprintPath = Join-Path $runtimeDir "bodyprint.json"
if (-not (Test-Path $avatarPath -PathType Leaf) -or -not (Test-Path $bodyprintPath -PathType Leaf)) { throw "Materialized runtime is missing avatar.vrm or bodyprint.json." }
$avatarHash = Sha256 $avatarPath; $bodyprintHash = Sha256 $bodyprintPath; $checksums = Read-PackageJson $packagePath "checksums.json" "checksums.json"
$expectedAvatarHash = Require-Sha ([string]$checksums.PSObject.Properties["avatar.vrm"].Value) "checksums.avatar.vrm"; $expectedBodyprintHash = Require-Sha ([string]$checksums.PSObject.Properties["bodyprint.json"].Value) "checksums.bodyprint.json"
if ($avatarHash -ne $expectedAvatarHash -or $bodyprintHash -ne $expectedBodyprintHash) { throw "Materialized runtime payload hashes do not match the accepted .mrbody." }
if ((Require-Sha ([string]$skinQa.avatar_sha256) "skin QA avatar hash") -ne $avatarHash) { throw "Anatomical skin QA was not run on the accepted avatar bytes." }

$probeFile = Read-JsonFile $ProbeReport "Renderer machine probe"; $ProbeReport = $probeFile.Path; $probe = $probeFile.Value
$expectedProbeFields = @("format","version","observed_at","bodyrig_revision","platform","unity_platform","unity_version","build_guid","device_model","graphics_device","body_id","package_sha256","runtime_manifest_sha256","avatar_sha256","bodyprint_sha256","vrm10_loaded","humanoid_valid","required_bones_valid","active_renderer")
if (@(Compare-Object -ReferenceObject $expectedProbeFields -DifferenceObject @($probe.PSObject.Properties.Name)).Count -ne 0) { throw "Renderer machine probe fields do not match BodyRig renderer probe v1." }
if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne $Platform) { throw "Renderer machine probe format/platform mismatch." }
if ([string]$probe.bodyrig_revision -notmatch '^[0-9a-f]{40}$' -or [string]$probe.bodyrig_revision -ne $head) { throw "Renderer machine probe was not produced by a player built from the exact accepted BodyRig revision." }
if ($probe.vrm10_loaded -ne $true -or $probe.humanoid_valid -ne $true -or $probe.required_bones_valid -ne $true) { throw "Renderer machine probe did not prove VRM/Humanoid/bones success." }
if ([string]$probe.body_id -ne $bodyId -or (Require-Sha ([string]$probe.package_sha256) "probe.package_sha256") -ne $actualPackageHash -or (Require-Sha ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $runtimeManifestHash -or (Require-Sha ([string]$probe.avatar_sha256) "probe.avatar_sha256") -ne $avatarHash -or (Require-Sha ([string]$probe.bodyprint_sha256) "probe.bodyprint_sha256") -ne $bodyprintHash) { throw "Renderer machine probe byte identity does not match accepted runtime." }
if ([string]$probe.active_renderer.name -ne $RendererName -or [string]$probe.active_renderer.version -ne $RendererVersion) { throw "Renderer name/version do not match the machine probe." }
foreach ($field in @("observed_at","unity_platform","unity_version","build_guid","device_model","graphics_device")) { if ([string]::IsNullOrWhiteSpace([string]$probe.$field)) { throw "Renderer machine probe is missing '$field'." } }
if ($Platform -eq "windows-unity-univrm" -and [string]$probe.unity_platform -ne "WindowsPlayer") { throw "Windows physical acceptance requires a built Unity WindowsPlayer, not the Editor." }
if ($Platform -eq "android-quest-class") {
    if ([string]$probe.unity_platform -ne "Android") { throw "Quest-class renderer probe was not produced by an Android Unity runtime." }
    if ([string]$probe.device_model -notmatch '(?i)(quest|oculus)') { throw "Android renderer probe does not identify a Quest/Oculus device model." }
}
$probeHash = Sha256 $ProbeReport

$deformationFile = Read-JsonFile $DeformationReport "Deformation machine probe"; $DeformationReport = $deformationFile.Path; $deformation = $deformationFile.Value
$expectedDeformationFields = @("format","version","observed_at","bodyrig_revision","platform","unity_platform","unity_version","build_guid","device_model","body_id","package_sha256","runtime_manifest_sha256","avatar_sha256","bodyprint_sha256","sequence_revision","pose_count","poses","required_muscles_resolved","restored_neutral","complete","manual_review_required")
if (@(Compare-Object -ReferenceObject $expectedDeformationFields -DifferenceObject @($deformation.PSObject.Properties.Name)).Count -ne 0) { throw "Deformation machine probe fields do not match BodyRig deformation probe v1." }
if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or [string]$deformation.platform -ne $Platform) { throw "Deformation machine probe format/platform mismatch." }
if ([string]$deformation.bodyrig_revision -notmatch '^[0-9a-f]{40}$' -or [string]$deformation.bodyrig_revision -ne $head -or [string]$deformation.bodyrig_revision -ne [string]$probe.bodyrig_revision) { throw "Deformation machine probe was not produced by the same exact accepted BodyRig build revision." }
if ([string]$deformation.sequence_revision -ne "humanoid-muscle-sweep-v1" -or [int]$deformation.pose_count -ne 6 -or $deformation.required_muscles_resolved -ne $true -or $deformation.restored_neutral -ne $true -or $deformation.complete -ne $true -or $deformation.manual_review_required -ne $true) { throw "Deformation machine probe did not complete the fixed review sequence." }
$poseIds = @($deformation.poses | ForEach-Object { [string]$_.id })
if (($poseIds -join ",") -ne "neutral,arms_abduction,elbows_flexed,arms_forward,left_leg_lift,knee_flexion") { throw "Deformation machine probe pose sequence/order mismatch." }
if ([string]$deformation.body_id -ne $bodyId -or (Require-Sha ([string]$deformation.package_sha256) "deformation.package_sha256") -ne $actualPackageHash -or (Require-Sha ([string]$deformation.runtime_manifest_sha256) "deformation.runtime_manifest_sha256") -ne $runtimeManifestHash -or (Require-Sha ([string]$deformation.avatar_sha256) "deformation.avatar_sha256") -ne $avatarHash -or (Require-Sha ([string]$deformation.bodyprint_sha256) "deformation.bodyprint_sha256") -ne $bodyprintHash) { throw "Deformation machine probe byte identity does not match accepted runtime." }
if ([string]$deformation.build_guid -ne [string]$probe.build_guid -or [string]$deformation.unity_platform -ne [string]$probe.unity_platform -or [string]$deformation.unity_version -ne [string]$probe.unity_version -or [string]$deformation.device_model -ne [string]$probe.device_model) { throw "Deformation machine probe does not come from the same physical build/device as renderer probe." }
$deformationHash = Sha256 $DeformationReport

if ([string]::IsNullOrWhiteSpace($Output)) { $Output = Join-Path $reportDir (if ($Platform -eq "windows-unity-univrm") { "bodyrig-renderer-acceptance-windows.json" } else { "bodyrig-renderer-acceptance-quest.json" }) }
$Output = [System.IO.Path]::GetFullPath($Output)
foreach ($p in @($AcceptanceReport,$packagePath,$RuntimeManifest,$avatarPath,$bodyprintPath,$ProbeReport,$DeformationReport,$sessionEvidencePath,$readinessEvidencePath,$skinQaEvidencePath)) { if ([string]::Equals($Output,$p,[System.StringComparison]::OrdinalIgnoreCase)) { throw "Renderer acceptance output must not overwrite input evidence." } }
if (Test-Path $Output) { throw "Renderer acceptance output already exists; refusing to overwrite evidence: $Output" }
$outputDir = Split-Path -Parent $Output; if (-not (Test-Path $outputDir -PathType Container)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }

$attestation = [ordered]@{ format="bodyrig-renderer-acceptance"; version=1; attested_at=[DateTime]::UtcNow.ToString("o"); bodyrig_revision=$head; automated_report_sha256=$reportHash; probe_report_sha256=$probeHash; deformation_report_sha256=$deformationHash; deformation_sequence_revision=[string]$deformation.sequence_revision; package_sha256=$actualPackageHash; runtime_manifest_sha256=$runtimeManifestHash; avatar_sha256=$avatarHash; bodyprint_sha256=$bodyprintHash; body_id=$bodyId; platform=$Platform; renderer_name=$RendererName; renderer_version=$RendererVersion; unity_platform=[string]$probe.unity_platform; unity_version=[string]$probe.unity_version; graphics_device=[string]$probe.graphics_device; machine_probe=$true; deformation_probe=$true; result="pass"; quality_note=$QualityNote; attestation="operator-supplied"; production_activation=$false }
$temp = Join-Path $outputDir ("."+[IO.Path]::GetFileName($Output)+"."+[Guid]::NewGuid().ToString("N")+".tmp")
try { $attestation | ConvertTo-Json -Depth 8 | Set-Content $temp -Encoding UTF8; Move-Item $temp $Output } finally { if (Test-Path $temp) { Remove-Item $temp -Force } }
Write-Host "BodyRig renderer acceptance: PASS | $Platform | revision $head | $($probe.device_model) | skin=$($skinQa.automated_assessment) | probe $probeHash | deformation $deformationHash"; Write-Host "Report: $Output"; exit 0