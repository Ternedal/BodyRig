$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Add-Type -AssemblyName System.IO.Compression.FileSystem

$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$SourceGate = (Resolve-Path (Join-Path $PSScriptRoot "../complete-acceptance.ps1")).Path
$SourceRecorder = (Resolve-Path (Join-Path $PSScriptRoot "../record-renderer-acceptance.ps1")).Path
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("bodyrig-release-gate-tests-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string]$Repo, [Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = @(& git -C $Repo @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)" }
    return $output
}
function Get-ByteHash {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([System.BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant() } finally { $sha.Dispose() }
}
function Add-ZipEntry {
    param([Parameter(Mandatory = $true)]$Archive, [Parameter(Mandatory = $true)][string]$Name, [Parameter(Mandatory = $true)][byte[]]$Bytes)
    $entry = $Archive.CreateEntry($Name, [System.IO.Compression.CompressionLevel]::Optimal); $stream = $entry.Open()
    try { $stream.Write($Bytes, 0, $Bytes.Length) } finally { $stream.Dispose() }
}
function Assert-Success { param($Result,[string]$Case); if ($Result.ExitCode -ne 0) { throw "$Case expected PASS, got exit $($Result.ExitCode): $($Result.Output)" } }
function Assert-Failure { param($Result,[string]$Case); if ($Result.ExitCode -eq 0) { throw "$Case expected FAIL, but gate returned success. Output: $($Result.Output)" } }

function New-Fixture {
    param([Parameter(Mandatory = $true)][string]$Name)
    $repo = Join-Path $TempRoot "$Name-repo"; $artifacts = Join-Path $TempRoot "$Name-artifacts"; $runtimeDir = Join-Path $artifacts "runtime"
    New-Item -ItemType Directory -Path $repo, $artifacts, $runtimeDir -Force | Out-Null
    Copy-Item $SourceGate (Join-Path $repo "complete-acceptance.ps1"); Copy-Item $SourceRecorder (Join-Path $repo "record-renderer-acceptance.ps1")
    & git -C $repo init --quiet; if ($LASTEXITCODE -ne 0) { throw "git init failed" }
    Invoke-Git $repo @("config","user.email","bodyrig-ci@example.invalid") | Out-Null; Invoke-Git $repo @("config","user.name","BodyRig CI") | Out-Null
    Invoke-Git $repo @("add","complete-acceptance.ps1","record-renderer-acceptance.ps1") | Out-Null; Invoke-Git $repo @("commit","--quiet","-m","fixture") | Out-Null
    $head = ([string]@(Invoke-Git $repo @("rev-parse","HEAD"))[0]).Trim().ToLowerInvariant(); if ($head -notmatch '^[0-9a-f]{40}$') { throw "invalid fixture head" }

    $bodyId="fixture-body"; $utf8=[Text.UTF8Encoding]::new($false)
    $avatarBytes=$utf8.GetBytes("fixture-avatar-vrm-bytes-$Name")
    $bodyprintBytes=$utf8.GetBytes('{"format":"modelrig-bodyprint","version":1,"shape":{"shoulder_to_height":0.24}}')
    $provenance=[ordered]@{format="modelrig-body-provenance";version=1;created_at="2026-08-24T00:00:00Z";source=[ordered]@{kind="user-supplied-local-media";count=1};synthetic_avatar=$true;pipeline=@([ordered]@{stage="body-recovery";adapter="4dhumans-hmr2-phalp";revision="fixture-pinned"},[ordered]@{stage="visual-identity-capture";adapter="opencv-identity-rgba";revision="1"},[ordered]@{stage="avatar-fitting";adapter="sith-smplx-vrm";revision="1"})}
    $provenanceBytes=$utf8.GetBytes(($provenance|ConvertTo-Json -Depth 8 -Compress))
    $thumbnailBytes=[byte[]](0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,0x66,0x69,0x78)
    $avatarHash=Get-ByteHash $avatarBytes; $bodyprintHash=Get-ByteHash $bodyprintBytes
    $checksums=[ordered]@{"avatar.vrm"=$avatarHash;"bodyprint.json"=$bodyprintHash;"provenance.json"=Get-ByteHash $provenanceBytes;"thumbnail.png"=Get-ByteHash $thumbnailBytes}
    $manifestBytes=$utf8.GetBytes('{"format":"modelrig-body","format_version":1,"id":"fixture-body"}'); $checksumsBytes=$utf8.GetBytes(($checksums|ConvertTo-Json -Compress))
    $packagePath=Join-Path $artifacts "$bodyId.mrbody"; $archive=[IO.Compression.ZipFile]::Open($packagePath,[IO.Compression.ZipArchiveMode]::Create)
    try { Add-ZipEntry $archive "manifest.json" $manifestBytes; Add-ZipEntry $archive "checksums.json" $checksumsBytes; Add-ZipEntry $archive "avatar.vrm" $avatarBytes; Add-ZipEntry $archive "bodyprint.json" $bodyprintBytes; Add-ZipEntry $archive "provenance.json" $provenanceBytes; Add-ZipEntry $archive "thumbnail.png" $thumbnailBytes } finally { $archive.Dispose() }
    $packageHash=(Get-FileHash $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllBytes((Join-Path $runtimeDir "avatar.vrm"),$avatarBytes);[IO.File]::WriteAllBytes((Join-Path $runtimeDir "bodyprint.json"),$bodyprintBytes);[IO.File]::WriteAllBytes((Join-Path $runtimeDir "provenance.json"),$provenanceBytes);[IO.File]::WriteAllBytes((Join-Path $runtimeDir "thumbnail.png"),$thumbnailBytes)
    $runtimeManifest=[ordered]@{format="bodyrig-runtime-assets";version=1;body_id=$bodyId;body_name="Fixture Body";package_sha256=$packageHash;avatar="avatar.vrm";bodyprint="bodyprint.json";payloads=@("avatar.vrm","bodyprint.json","provenance.json","thumbnail.png")}
    $runtimeManifestPath=Join-Path $runtimeDir "runtime-manifest.json"; $runtimeManifest|ConvertTo-Json -Depth 8 -Compress|Set-Content $runtimeManifestPath -Encoding UTF8; $runtimeManifestHash=(Get-FileHash $runtimeManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()

    $sessionEvidencePath=Join-Path $artifacts "bodyrig-physical-clone-session.json";'{"format":"bodyrig-physical-clone-session-fixture"}'|Set-Content $sessionEvidencePath -Encoding UTF8
    $readinessEvidencePath=Join-Path $artifacts "bodyrig-rig-readiness.json";'{"format":"bodyrig-rig-readiness-fixture"}'|Set-Content $readinessEvidencePath -Encoding UTF8
    $skinQaEvidencePath=Join-Path $artifacts "bodyrig-skin-qa.json"
    $skinQa=[ordered]@{format="bodyrig-skin-qa";version=1;body_id=$bodyId;package_sha256=$packageHash;avatar_sha256=$avatarHash;structural_pass=$true;manual_review_required=$true;automated_assessment="low-risk"}
    $skinQa|ConvertTo-Json -Depth 8 -Compress|Set-Content $skinQaEvidencePath -Encoding UTF8
    $sessionHash=(Get-FileHash $sessionEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant();$readinessHash=(Get-FileHash $readinessEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant();$skinQaHash=(Get-FileHash $skinQaEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant()

    $checks=[ordered]@{bodyrig_checkout_clean=$true;preflight_ok=$true;recovery_adapter_pinned=$true;observed_frames_ge_2=$true;source_derived_shape_present=$true;source_derived_motion_present=$true;bodyprint_matches_package=$true;source_count_matches_package=$true;recovery_provenance_matches=$true;avatar_fitting_provenance_present=$true;avatar_is_vrm_1_0=$true;runtime_materialized_from_package=$true}
    $report=[ordered]@{format="bodyrig-rig-acceptance";version=1;created_at=[DateTime]::UtcNow.ToString("o");bodyrig_revision=$head;bodyrig_checkout_clean=$true;source_count=1;physical_clone=[ordered]@{session_sha256=$sessionHash;readiness_sha256=$readinessHash;mode="stash-sith-high-fidelity"};skin_qa=[ordered]@{report_sha256=$skinQaHash;structural_pass=$true;automated_assessment="low-risk";manual_review_required=$true};recovery=[ordered]@{adapter="4dhumans-hmr2-phalp";revision="fixture-pinned";track_id="track-1";observed_frames=120};package=[ordered]@{package_sha256=$packageHash;body_id=$bodyId;body_name="Fixture Body";payload_names=@("avatar.vrm","bodyprint.json","provenance.json","thumbnail.png");bodyprint_matches_proof=$true;source_count_matches=$true;recovery_provenance_matches=$true;avatar_fitting_provenance_present=$true;vrm_spec_version="1.0";placeholder_avatar=$false};runtime=[ordered]@{manifest="runtime/runtime-manifest.json";manifest_sha256=$runtimeManifestHash;materialized_from_package=$true};checks=$checks;automated_pass=$true;physical_renderer_acceptance="pending";production_activation=$false}
    $reportPath=Join-Path $artifacts "bodyrig-acceptance.json";$report|ConvertTo-Json -Depth 12|Set-Content $reportPath -Encoding UTF8
    [pscustomobject]@{Repo=$repo;GateScript=Join-Path $repo "complete-acceptance.ps1";RecorderScript=Join-Path $repo "record-renderer-acceptance.ps1";Artifacts=$artifacts;RuntimeDir=$runtimeDir;RuntimeManifestPath=$runtimeManifestPath;RuntimeManifestHash=$runtimeManifestHash;ReportPath=$reportPath;Report=$report;PackagePath=$packagePath;PackageHash=$packageHash;AvatarHash=$avatarHash;BodyprintHash=$bodyprintHash;BodyId=$bodyId;Head=$head;SessionEvidencePath=$sessionEvidencePath;ReadinessEvidencePath=$readinessEvidencePath;SkinQaEvidencePath=$skinQaEvidencePath}
}
function Save-Report { param($Fixture);$Fixture.Report|ConvertTo-Json -Depth 12|Set-Content $Fixture.ReportPath -Encoding UTF8 }
function New-Probe {
    param($Fixture,[ValidateSet("windows-unity-univrm","android-quest-class")][string]$Platform,[string]$Path,[string]$RendererVersion="fixture-renderer-1",[string]$UnityPlatform="",[string]$DeviceModel="")
    if ([string]::IsNullOrWhiteSpace($UnityPlatform)) { $UnityPlatform=if($Platform-eq"windows-unity-univrm"){"WindowsPlayer"}else{"Android"} }
    if ([string]::IsNullOrWhiteSpace($DeviceModel)) { $DeviceModel=if($Platform-eq"windows-unity-univrm"){"Fixture Windows PC"}else{"Meta Quest 2"} }
    $probe=[ordered]@{format="bodyrig-renderer-probe";version=1;observed_at=[DateTime]::UtcNow.ToString("o");platform=$Platform;unity_platform=$UnityPlatform;unity_version="2022.3-fixture";build_guid="fixture-build-$($Platform.Replace('-','_'))";device_model=$DeviceModel;graphics_device="Fixture GPU";body_id=$Fixture.BodyId;package_sha256=$Fixture.PackageHash;runtime_manifest_sha256=$Fixture.RuntimeManifestHash;avatar_sha256=$Fixture.AvatarHash;bodyprint_sha256=$Fixture.BodyprintHash;vrm10_loaded=$true;humanoid_valid=$true;required_bones_valid=$true;active_renderer=[ordered]@{name="BodyRig Reference Renderer";version=$RendererVersion}}
    $probe|ConvertTo-Json -Depth 8|Set-Content $Path -Encoding UTF8;return $Path
}
function New-Deformation {
    param($Fixture,[ValidateSet("windows-unity-univrm","android-quest-class")][string]$Platform,[string]$ProbePath,[string]$Path)
    $probe=Get-Content $ProbePath -Raw|ConvertFrom-Json
    $poses=@("neutral","arms_abduction","elbows_flexed","arms_forward","left_leg_lift","knee_flexion")|ForEach-Object{[ordered]@{id=$_;hold_seconds=1.5;applied=$true}}
    $report=[ordered]@{format="bodyrig-deformation-probe";version=1;observed_at=[DateTime]::UtcNow.ToString("o");platform=$Platform;unity_platform=[string]$probe.unity_platform;unity_version=[string]$probe.unity_version;build_guid=[string]$probe.build_guid;device_model=[string]$probe.device_model;body_id=$Fixture.BodyId;package_sha256=$Fixture.PackageHash;runtime_manifest_sha256=$Fixture.RuntimeManifestHash;avatar_sha256=$Fixture.AvatarHash;bodyprint_sha256=$Fixture.BodyprintHash;sequence_revision="humanoid-muscle-sweep-v1";pose_count=6;poses=@($poses);required_muscles_resolved=$true;restored_neutral=$true;complete=$true;manual_review_required=$true}
    $report|ConvertTo-Json -Depth 8|Set-Content $Path -Encoding UTF8;return $Path
}
function Invoke-RendererRecord {
    param($Fixture,[ValidateSet("windows-unity-univrm","android-quest-class")][string]$Platform,[string]$ProbePath,[string]$Output,[string]$QualityNote="Avatar loads correctly and fixed deformation sweep looked visually plausible.",[string]$RendererVersion="fixture-renderer-1",[string]$DeformationPath="")
    if([string]::IsNullOrWhiteSpace($DeformationPath)){$DeformationPath=New-Deformation $Fixture $Platform $ProbePath ($Output+".deformation.json")}
    $args=@("-NoLogo","-NoProfile","-NonInteractive","-File",$Fixture.RecorderScript,"-AcceptanceReport",$Fixture.ReportPath,"-RuntimeManifest",$Fixture.RuntimeManifestPath,"-ProbeReport",$ProbePath,"-DeformationReport",$DeformationPath,"-Platform",$Platform,"-Pass","-RendererName","BodyRig Reference Renderer","-RendererVersion",$RendererVersion,"-QualityNote",$QualityNote,"-Output",$Output)
    $lines=@(&$Pwsh @args 2>&1);[pscustomobject]@{ExitCode=$LASTEXITCODE;Output=$lines-join[Environment]::NewLine}
}
function New-RendererPair {
    param($Fixture)
    $wp=New-Probe $Fixture "windows-unity-univrm" (Join-Path $Fixture.Artifacts "windows-probe.json");$qp=New-Probe $Fixture "android-quest-class" (Join-Path $Fixture.Artifacts "quest-probe.json")
    $wd=New-Deformation $Fixture "windows-unity-univrm" $wp (Join-Path $Fixture.Artifacts "windows-deformation.json");$qd=New-Deformation $Fixture "android-quest-class" $qp (Join-Path $Fixture.Artifacts "quest-deformation.json")
    $wr=Join-Path $Fixture.Artifacts "windows-renderer.json";$qr=Join-Path $Fixture.Artifacts "quest-renderer.json";Assert-Success (Invoke-RendererRecord $Fixture "windows-unity-univrm" $wp $wr -DeformationPath $wd) "record Windows";Assert-Success (Invoke-RendererRecord $Fixture "android-quest-class" $qp $qr -DeformationPath $qd) "record Quest"
    [pscustomobject]@{Windows=$wr;WindowsProbe=$wp;WindowsDeformation=$wd;Quest=$qr;QuestProbe=$qp;QuestDeformation=$qd}
}
function Invoke-Gate {
    param($Fixture,[string]$WindowsReport,[string]$WindowsProbe,[string]$WindowsDeformation,[string]$QuestReport,[string]$QuestProbe,[string]$QuestDeformation,[string]$Output="")
    $args=@("-NoLogo","-NoProfile","-NonInteractive","-File",$Fixture.GateScript,"-AcceptanceReport",$Fixture.ReportPath,"-WindowsRendererReport",$WindowsReport,"-WindowsProbeReport",$WindowsProbe,"-WindowsDeformationReport",$WindowsDeformation,"-QuestRendererReport",$QuestReport,"-QuestProbeReport",$QuestProbe,"-QuestDeformationReport",$QuestDeformation);if(-not[string]::IsNullOrWhiteSpace($Output)){$args+=@("-Output",$Output)};$lines=@(&$Pwsh @args 2>&1);[pscustomobject]@{ExitCode=$LASTEXITCODE;Output=$lines-join[Environment]::NewLine}
}
function Invoke-PairGate { param($Fixture,$Pair,[string]$Output=""); Invoke-Gate $Fixture $Pair.Windows $Pair.WindowsProbe $Pair.WindowsDeformation $Pair.Quest $Pair.QuestProbe $Pair.QuestDeformation $Output }

try {
    $f=New-Fixture "pass";$r=New-RendererPair $f
    $wAtt=Get-Content $r.Windows -Raw|ConvertFrom-Json;$wDefHash=(Get-FileHash $r.WindowsDeformation -Algorithm SHA256).Hash.ToLowerInvariant();if([string]$wAtt.deformation_report_sha256-ne$wDefHash-or[string]$wAtt.deformation_sequence_revision-ne"humanoid-muscle-sweep-v1"-or$wAtt.deformation_probe-ne$true){throw "renderer attestation did not bind deformation evidence"}
    $release=Join-Path $f.Artifacts "release.json";Assert-Success (Invoke-PairGate $f $r $release) "valid physical evidence chain";$v=Get-Content $release -Raw|ConvertFrom-Json
    if($v.release_gate_pass-ne$true-or$v.production_activation-ne$true-or[string]$v.automated_acceptance.physical_clone_mode-ne"stash-sith-high-fidelity"-or[string]$v.automated_acceptance.skin_qa_assessment-ne"low-risk"-or$v.automated_acceptance.skin_qa_manual_review_required-ne$true-or[string]$v.renderer_acceptance.windows_unity_univrm.deformation_sequence_revision-ne"humanoid-muscle-sweep-v1"-or[string]$v.renderer_acceptance.android_quest_class.deformation_sequence_revision-ne"humanoid-muscle-sweep-v1"-or[string]$v.renderer_acceptance.windows_unity_univrm.deformation_report_sha256-notmatch'^[0-9a-f]{64}$'-or[string]$v.renderer_acceptance.windows_unity_univrm.unity_platform-ne"WindowsPlayer"-or[string]$v.renderer_acceptance.android_quest_class.device_model-notmatch"(?i)quest"){throw "release physical identity round-trip failed"};Write-Host "PASS: high-fidelity skin-QA + deformation-bound operator attestations reach release gate"

    $f=New-Fixture "placeholder";$f.Report.package.placeholder_avatar=$true;Save-Report $f;$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "placeholder package";Write-Host "PASS: placeholder Gate A cannot enter renderer acceptance"
    $f=New-Fixture "lineage-tamper";Add-Content $f.SessionEvidencePath "tamper";$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "physical lineage tamper";Write-Host "PASS: physical clone lineage tamper rejected"
    $f=New-Fixture "skin-qa-tamper";Add-Content $f.SkinQaEvidencePath "tamper";$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "skin QA tamper";Write-Host "PASS: anatomical skin QA tamper rejected"
    $f=New-Fixture "windows-editor";$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json") -UnityPlatform "WindowsEditor";Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "Windows Editor";Write-Host "PASS: Windows Editor cannot satisfy physical player gate"
    $f=New-Fixture "android-phone";$p=New-Probe $f "android-quest-class" (Join-Path $f.Artifacts "probe.json") -DeviceModel "Pixel 10 Pro";Assert-Failure (Invoke-RendererRecord $f "android-quest-class" $p (Join-Path $f.Artifacts "att.json")) "Android phone";Write-Host "PASS: generic Android phone cannot satisfy Quest gate"
    $f=New-Fixture "missing-build-guid";$p=New-Probe $f "android-quest-class" (Join-Path $f.Artifacts "probe.json");$j=Get-Content $p -Raw|ConvertFrom-Json;$j.build_guid="";$j|ConvertTo-Json -Depth 8|Set-Content $p -Encoding UTF8;Assert-Failure (Invoke-RendererRecord $f "android-quest-class" $p (Join-Path $f.Artifacts "att.json")) "blank build GUID";Write-Host "PASS: blank build identity rejected"
    $f=New-Fixture "blank-note";$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json") -QualityNote "   ") "blank note"
    $f=New-Fixture "probe-platform";$p=New-Probe $f "android-quest-class" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "platform relabel"
    $f=New-Fixture "probe-avatar";$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");$j=Get-Content $p -Raw|ConvertFrom-Json;$j.avatar_sha256="0"*64;$j|ConvertTo-Json -Depth 8|Set-Content $p -Encoding UTF8;Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "probe avatar mismatch"
    $f=New-Fixture "runtime-avatar";$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Add-Content (Join-Path $f.RuntimeDir "avatar.vrm") "tamper";Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "runtime avatar tamper"
    $f=New-Fixture "deformation-package";$r=New-RendererPair $f;$j=Get-Content $r.WindowsDeformation -Raw|ConvertFrom-Json;$j.package_sha256="0"*64;$j|ConvertTo-Json -Depth 10|Set-Content $r.WindowsDeformation -Encoding UTF8;Assert-Failure (Invoke-PairGate $f $r) "deformation package tamper";Write-Host "PASS: deformation package identity tamper rejected"
    $f=New-Fixture "deformation-sequence";$r=New-RendererPair $f;$j=Get-Content $r.QuestDeformation -Raw|ConvertFrom-Json;$j.poses[3].id="neutral";$j|ConvertTo-Json -Depth 10|Set-Content $r.QuestDeformation -Encoding UTF8;Assert-Failure (Invoke-PairGate $f $r) "deformation pose sequence tamper";Write-Host "PASS: deformation pose sequence tamper rejected"
    $f=New-Fixture "deformation-build";$r=New-RendererPair $f;$j=Get-Content $r.WindowsDeformation -Raw|ConvertFrom-Json;$j.build_guid="different-build";$j|ConvertTo-Json -Depth 10|Set-Content $r.WindowsDeformation -Encoding UTF8;Assert-Failure (Invoke-PairGate $f $r) "deformation build mismatch";Write-Host "PASS: deformation evidence must come from same build as machine probe"
    $f=New-Fixture "attestation-deformation-hash";$r=New-RendererPair $f;$j=Get-Content $r.Windows -Raw|ConvertFrom-Json;$j.deformation_report_sha256="0"*64;$j|ConvertTo-Json -Depth 10|Set-Content $r.Windows -Encoding UTF8;Assert-Failure (Invoke-PairGate $f $r) "attestation deformation hash substitution";Write-Host "PASS: operator attestation must bind exact deformation evidence"
    $f=New-Fixture "probe-after";$r=New-RendererPair $f;$j=Get-Content $r.QuestProbe -Raw|ConvertFrom-Json;$j.graphics_device="Substituted GPU";$j|ConvertTo-Json -Depth 8|Set-Content $r.QuestProbe -Encoding UTF8;Assert-Failure (Invoke-PairGate $f $r) "probe post-attestation tamper"
    $f=New-Fixture "renderer-package";$r=New-RendererPair $f;$j=Get-Content $r.Quest -Raw|ConvertFrom-Json;$j.package_sha256="0"*64;$j|ConvertTo-Json -Depth 10|Set-Content $r.Quest -Encoding UTF8;Assert-Failure (Invoke-PairGate $f $r) "renderer package tamper"
    $f=New-Fixture "platform-swap";$r=New-RendererPair $f;Assert-Failure (Invoke-Gate $f $r.Quest $r.QuestProbe $r.QuestDeformation $r.Windows $r.WindowsProbe $r.WindowsDeformation) "platform swap"
    $f=New-Fixture "same-report";$r=New-RendererPair $f;Assert-Failure (Invoke-Gate $f $r.Windows $r.WindowsProbe $r.WindowsDeformation $r.Windows $r.WindowsProbe $r.WindowsDeformation) "same evidence"
    $f=New-Fixture "package-tamper";$r=New-RendererPair $f;Add-Content $f.PackagePath "tamper";Assert-Failure (Invoke-PairGate $f $r) "package tamper"
    $f=New-Fixture "failed-check";$r=New-RendererPair $f;$f.Report.checks.preflight_ok=$false;Save-Report $f;Assert-Failure (Invoke-PairGate $f $r) "failed automated check"
    $f=New-Fixture "revision";$r=New-RendererPair $f;$f.Report.bodyrig_revision="0"*40;Save-Report $f;Assert-Failure (Invoke-PairGate $f $r) "revision mismatch"
    $f=New-Fixture "dirty";$r=New-RendererPair $f;Set-Content (Join-Path $f.Repo "dirty.txt") "dirty";Assert-Failure (Invoke-PairGate $f $r) "dirty repo"
    Write-Host "BodyRig high-fidelity skin-QA + directly deformation-bound physical-device release gate tests: PASS";exit 0
} finally { Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue }