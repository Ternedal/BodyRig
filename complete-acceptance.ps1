param(
    [Parameter(Mandatory = $true)][string]$AcceptanceReport,
    [Parameter(Mandatory = $true)][string]$WindowsRendererReport,
    [Parameter(Mandatory = $true)][string]$WindowsProbeReport,
    [Parameter(Mandatory = $true)][string]$WindowsDeformationReport,
    [Parameter(Mandatory = $true)][string]$QuestRendererReport,
    [Parameter(Mandatory = $true)][string]$QuestProbeReport,
    [Parameter(Mandatory = $true)][string]$QuestDeformationReport,
    [string]$Output = ""
)
$ErrorActionPreference = "Stop"; Set-StrictMode -Version Latest

function Read-Json([string]$Path,[string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    $p=(Resolve-Path -LiteralPath $Path).Path; try{$v=Get-Content -LiteralPath $p -Raw|ConvertFrom-Json}catch{throw "$Label is not valid JSON: $p"}
    [pscustomobject]@{Path=$p;Hash=(Get-FileHash $p -Algorithm SHA256).Hash.ToLowerInvariant();Value=$v}
}
function Need-Sha([string]$v,[string]$f){$n=$v.ToLowerInvariant();if($n -notmatch '^[0-9a-f]{64}$'){throw "$f is not canonical SHA-256."};$n}
function Need-Revision([string]$v,[string]$f){$n=$v.ToLowerInvariant();if($n -notmatch '^[0-9a-f]{40}$'){throw "$f is not a canonical Git revision."};$n}
function Read-PackageJson([string]$Path,[string]$EntryName,[string]$Label){
    Add-Type -AssemblyName System.IO.Compression.FileSystem;$z=[IO.Compression.ZipFile]::OpenRead($Path)
    try{$e=$z.GetEntry($EntryName);if($null-eq$e){throw "Accepted .mrbody has no $EntryName."};$s=$e.Open();$r=[IO.StreamReader]::new($s,[Text.Encoding]::UTF8,$true,4096,$false);try{$t=$r.ReadToEnd()}finally{$r.Dispose()};try{$t|ConvertFrom-Json}catch{throw "Accepted .mrbody $Label is invalid JSON."}}finally{$z.Dispose()}
}
function Assert-QualityReview($Attestation,[string]$Label){
    $review=$Attestation.quality_review
    if($null-eq$review){throw "$Label human quality review is missing."}
    $fields=@('revision','full_deformation_sequence_reviewed','source_identity_texture_acceptable','geometry_proportions_acceptable','upper_body_deformation_acceptable','lower_body_deformation_acceptable','cross_limb_leakage_absent','skin_qa_considered')
    if(@(Compare-Object $fields @($review.PSObject.Properties.Name)).Count-ne0){throw "$Label human quality review fields are not canonical."}
    if([string]$review.revision-ne'bodyrig-human-quality-v1'){throw "$Label human quality review revision mismatch."}
    foreach($field in $fields|Where-Object{$_-ne'revision'}){if($review.$field-ne$true){throw "$Label human quality review did not explicitly pass '$field'."}}
}

$auto=Read-Json $AcceptanceReport 'Acceptance report';$AcceptanceReport=$auto.Path;$a=$auto.Value;$dir=Split-Path -Parent $AcceptanceReport
if([string]$a.format-ne'bodyrig-rig-acceptance'-or[int]$a.version-ne1-or$a.automated_pass-ne$true-or$a.bodyrig_checkout_clean-ne$true-or[string]$a.physical_renderer_acceptance-ne'pending'-or$a.production_activation-ne$false){throw 'Automated acceptance is not a valid pending-renderer PASS.'}
foreach($n in @('bodyrig_checkout_clean','preflight_ok','recovery_adapter_pinned','observed_frames_ge_2','source_derived_shape_present','source_derived_motion_present','bodyprint_matches_package','source_count_matches_package','recovery_provenance_matches','avatar_fitting_provenance_present','avatar_is_vrm_1_0','runtime_materialized_from_package')){$p=$a.checks.PSObject.Properties[$n];if($null-eq$p-or$p.Value-ne$true){throw "Automated acceptance check missing/false: $n"}}
if([int]$a.recovery.observed_frames-lt2-or[string]$a.package.vrm_spec_version-ne'1.0'-or$a.package.placeholder_avatar-ne$false-or[string]$a.runtime.manifest-ne'runtime/runtime-manifest.json'-or$a.runtime.materialized_from_package-ne$true){throw 'Automated acceptance structural/high-fidelity checks failed.'}
if([string]$a.physical_clone.mode-ne'stash-sith-high-fidelity'){throw 'Production activation requires Stash/SiTH physical-clone lineage.'}
if($a.skin_qa.structural_pass-ne$true-or$a.skin_qa.manual_review_required-ne$true-or[string]$a.skin_qa.automated_assessment-notin@('low-risk','review','high-risk')){throw 'Production activation requires valid anatomical skin QA evidence.'}
$sessionHash=Need-Sha ([string]$a.physical_clone.session_sha256) 'physical_clone.session_sha256';$readinessHash=Need-Sha ([string]$a.physical_clone.readiness_sha256) 'physical_clone.readiness_sha256';$skinQaHash=Need-Sha ([string]$a.skin_qa.report_sha256) 'skin_qa.report_sha256'
$sessionEvidence=Join-Path $dir 'bodyrig-physical-clone-session.json';$readinessEvidence=Join-Path $dir 'bodyrig-rig-readiness.json';$skinQaEvidence=Join-Path $dir 'bodyrig-skin-qa.json'
if(-not(Test-Path $sessionEvidence -PathType Leaf)-or(Get-FileHash $sessionEvidence -Algorithm SHA256).Hash.ToLowerInvariant()-ne$sessionHash){throw 'Physical clone session evidence is missing or changed.'}
if(-not(Test-Path $readinessEvidence -PathType Leaf)-or(Get-FileHash $readinessEvidence -Algorithm SHA256).Hash.ToLowerInvariant()-ne$readinessHash){throw 'Physical clone readiness evidence is missing or changed.'}
if(-not(Test-Path $skinQaEvidence -PathType Leaf)-or(Get-FileHash $skinQaEvidence -Algorithm SHA256).Hash.ToLowerInvariant()-ne$skinQaHash){throw 'Anatomical skin QA evidence is missing or changed.'}
$skinQa=Read-Json $skinQaEvidence 'Anatomical skin QA report';$runtimeHash=Need-Sha ([string]$a.runtime.manifest_sha256) 'runtime.manifest_sha256'

$root=(Resolve-Path $PSScriptRoot).Path;$head=(&git -C $root rev-parse HEAD).Trim().ToLowerInvariant();if($LASTEXITCODE-ne0-or$head-notmatch'^[0-9a-f]{40}$'-or$head-ne([string]$a.bodyrig_revision).ToLowerInvariant()){throw 'BodyRig HEAD does not match accepted revision.'};if(@(&git -C $root status --porcelain).Count-gt0){throw 'BodyRig checkout is dirty.'}
$bodyId=[string]$a.package.body_id;if($bodyId-notmatch'^[a-z0-9æøå_-]{1,160}$'){throw 'Invalid body id.'};$package=Join-Path $dir "$bodyId.mrbody";if(-not(Test-Path $package -PathType Leaf)){throw 'Accepted .mrbody missing.'};$package=(Resolve-Path $package).Path;$packageHash=(Get-FileHash $package -Algorithm SHA256).Hash.ToLowerInvariant();if($packageHash-ne(Need-Sha ([string]$a.package.package_sha256) 'package hash')){throw 'Accepted package hash changed.'}
$c=Read-PackageJson $package 'checksums.json' 'checksums.json';$avatarHash=Need-Sha ([string]$c.PSObject.Properties['avatar.vrm'].Value) 'avatar checksum';$bodyprintHash=Need-Sha ([string]$c.PSObject.Properties['bodyprint.json'].Value) 'bodyprint checksum'
if([string]$skinQa.Value.format-ne'bodyrig-skin-qa'-or[int]$skinQa.Value.version-ne1-or[string]$skinQa.Value.body_id-ne$bodyId-or(Need-Sha ([string]$skinQa.Value.package_sha256) 'skin QA package')-ne$packageHash-or(Need-Sha ([string]$skinQa.Value.avatar_sha256) 'skin QA avatar')-ne$avatarHash-or$skinQa.Value.structural_pass-ne$true-or$skinQa.Value.manual_review_required-ne$true-or[string]$skinQa.Value.automated_assessment-ne[string]$a.skin_qa.automated_assessment){throw 'Anatomical skin QA no longer matches accepted package/avatar or Gate A.'}
$provenance=Read-PackageJson $package 'provenance.json' 'provenance.json';$visual=@($provenance.pipeline|Where-Object{[string]$_.stage-eq'visual-identity-capture'});$fitting=@($provenance.pipeline|Where-Object{[string]$_.stage-eq'avatar-fitting'})
if($visual.Count-ne1){throw 'Accepted package lacks exactly one visual-identity-capture provenance stage.'};if($fitting.Count-ne1-or[string]$fitting[0].adapter-ne'sith-smplx-vrm'-or[string]$fitting[0].revision-ne'1'){throw 'Accepted package was not produced by built-in sith-smplx-vrm v1.'}

function Read-Probe([string]$Path,[string]$Platform){
    $f=Read-Json $Path 'Renderer machine probe';$v=$f.Value;$fields=@('format','version','observed_at','bodyrig_revision','platform','unity_platform','unity_version','build_guid','device_model','graphics_device','body_id','package_sha256','runtime_manifest_sha256','avatar_sha256','bodyprint_sha256','vrm10_loaded','humanoid_valid','required_bones_valid','active_renderer')
    if(@(Compare-Object $fields @($v.PSObject.Properties.Name)).Count-ne0-or[string]$v.format-ne'bodyrig-renderer-probe'-or[int]$v.version-ne1-or[string]$v.platform-ne$Platform){throw "Invalid renderer probe: $($f.Path)"}
    if((Need-Revision ([string]$v.bodyrig_revision) 'probe build revision')-ne$head){throw "Renderer probe was produced by a different BodyRig build revision: $($f.Path)"}
    if($v.vrm10_loaded-ne$true-or$v.humanoid_valid-ne$true-or$v.required_bones_valid-ne$true){throw "Probe did not prove VRM/Humanoid/bones: $($f.Path)"}
    if([string]$v.body_id-ne$bodyId-or(Need-Sha ([string]$v.package_sha256) 'probe package')-ne$packageHash-or(Need-Sha ([string]$v.runtime_manifest_sha256) 'probe runtime')-ne$runtimeHash-or(Need-Sha ([string]$v.avatar_sha256) 'probe avatar')-ne$avatarHash-or(Need-Sha ([string]$v.bodyprint_sha256) 'probe bodyprint')-ne$bodyprintHash){throw "Probe byte identity mismatch: $($f.Path)"}
    foreach($n in @('observed_at','unity_platform','unity_version','build_guid','device_model','graphics_device')){if([string]::IsNullOrWhiteSpace([string]$v.$n)){throw "Probe missing ${n}: $($f.Path)"}}
    if($Platform-eq'windows-unity-univrm'-and[string]$v.unity_platform-ne'WindowsPlayer'){throw 'Windows release evidence must come from Unity WindowsPlayer.'}
    if($Platform-eq'android-quest-class'){if([string]$v.unity_platform-ne'Android'){throw 'Quest probe must come from Unity Android.'};if([string]$v.device_model-notmatch'(?i)(quest|oculus)'){throw "Quest probe device model is not Quest/Oculus: $($v.device_model)"}}
    if([string]::IsNullOrWhiteSpace([string]$v.active_renderer.name)-or[string]::IsNullOrWhiteSpace([string]$v.active_renderer.version)){throw 'Probe renderer identity missing.'};$f
}
function Read-Deformation([string]$Path,[string]$Platform,$Probe){
    $f=Read-Json $Path 'Deformation machine probe';$v=$f.Value
    $fields=@('format','version','observed_at','bodyrig_revision','platform','unity_platform','unity_version','build_guid','device_model','body_id','package_sha256','runtime_manifest_sha256','avatar_sha256','bodyprint_sha256','sequence_revision','pose_count','poses','required_muscles_resolved','restored_neutral','complete','manual_review_required')
    if(@(Compare-Object $fields @($v.PSObject.Properties.Name)).Count-ne0-or[string]$v.format-ne'bodyrig-deformation-probe'-or[int]$v.version-ne1-or[string]$v.platform-ne$Platform){throw "Invalid deformation probe: $($f.Path)"}
    $deformationRevision=Need-Revision ([string]$v.bodyrig_revision) 'deformation build revision';if($deformationRevision-ne$head-or$deformationRevision-ne[string]$Probe.Value.bodyrig_revision){throw "Deformation probe was produced by a different BodyRig build revision: $($f.Path)"}
    if([string]$v.sequence_revision-ne'humanoid-muscle-sweep-v1'-or[int]$v.pose_count-ne6-or$v.required_muscles_resolved-ne$true-or$v.restored_neutral-ne$true-or$v.complete-ne$true-or$v.manual_review_required-ne$true){throw "Deformation probe did not complete the fixed sequence: $($f.Path)"}
    $poseIds=@($v.poses|ForEach-Object{[string]$_.id});if(($poseIds-join',')-ne'neutral,arms_abduction,elbows_flexed,arms_forward,left_leg_lift,knee_flexion'){throw "Deformation probe pose sequence/order mismatch: $($f.Path)"}
    if([string]$v.body_id-ne$bodyId-or(Need-Sha ([string]$v.package_sha256) 'deformation package')-ne$packageHash-or(Need-Sha ([string]$v.runtime_manifest_sha256) 'deformation runtime')-ne$runtimeHash-or(Need-Sha ([string]$v.avatar_sha256) 'deformation avatar')-ne$avatarHash-or(Need-Sha ([string]$v.bodyprint_sha256) 'deformation bodyprint')-ne$bodyprintHash){throw "Deformation byte identity mismatch: $($f.Path)"}
    if([string]$v.build_guid-ne[string]$Probe.Value.build_guid-or[string]$v.unity_platform-ne[string]$Probe.Value.unity_platform-or[string]$v.unity_version-ne[string]$Probe.Value.unity_version-or[string]$v.device_model-ne[string]$Probe.Value.device_model){throw "Deformation probe does not come from the same physical build/device as renderer probe: $($f.Path)"}
    $f
}
function Read-Att([string]$Path,[string]$Platform,$Probe,$Deformation){
    $f=Read-Json $Path 'Renderer acceptance';$v=$f.Value
    if([string]$v.format-ne'bodyrig-renderer-acceptance'-or[int]$v.version-ne1-or[string]$v.platform-ne$Platform-or[string]$v.result-ne'pass'-or[string]$v.attestation-ne'operator-supplied'-or$v.machine_probe-ne$true-or$v.deformation_probe-ne$true-or$v.production_activation-ne$false){throw "Invalid renderer attestation: $($f.Path)"}
    if(([string]$v.bodyrig_revision).ToLowerInvariant()-ne$head-or[string]$Probe.Value.bodyrig_revision-ne$head-or[string]$Deformation.Value.bodyrig_revision-ne$head-or(Need-Sha ([string]$v.automated_report_sha256) 'att automated')-ne$auto.Hash-or(Need-Sha ([string]$v.probe_report_sha256) 'att probe')-ne$Probe.Hash-or(Need-Sha ([string]$v.deformation_report_sha256) 'att deformation')-ne$Deformation.Hash-or[string]$v.deformation_sequence_revision-ne[string]$Deformation.Value.sequence_revision-or(Need-Sha ([string]$v.package_sha256) 'att package')-ne$packageHash-or(Need-Sha ([string]$v.runtime_manifest_sha256) 'att runtime')-ne$runtimeHash-or(Need-Sha ([string]$v.avatar_sha256) 'att avatar')-ne$avatarHash-or(Need-Sha ([string]$v.bodyprint_sha256) 'att bodyprint')-ne$bodyprintHash-or[string]$v.body_id-ne$bodyId){throw "Renderer attestation binding mismatch: $($f.Path)"}
    if([string]$v.renderer_name-ne[string]$Probe.Value.active_renderer.name-or[string]$v.renderer_version-ne[string]$Probe.Value.active_renderer.version-or[string]$v.unity_platform-ne[string]$Probe.Value.unity_platform-or[string]$v.unity_version-ne[string]$Probe.Value.unity_version-or[string]$v.graphics_device-ne[string]$Probe.Value.graphics_device){throw "Renderer attestation does not match machine probe: $($f.Path)"}
    Assert-QualityReview $v ([string]$Platform)
    if([string]::IsNullOrWhiteSpace([string]$v.quality_note)){throw 'Renderer quality note missing.'};$f
}

$wp=Read-Probe $WindowsProbeReport 'windows-unity-univrm';$qp=Read-Probe $QuestProbeReport 'android-quest-class';if([string]::Equals($wp.Path,$qp.Path,[StringComparison]::OrdinalIgnoreCase)){throw 'Windows and Quest probes must be distinct.'}
$wd=Read-Deformation $WindowsDeformationReport 'windows-unity-univrm' $wp;$qd=Read-Deformation $QuestDeformationReport 'android-quest-class' $qp;if([string]::Equals($wd.Path,$qd.Path,[StringComparison]::OrdinalIgnoreCase)){throw 'Windows and Quest deformation probes must be distinct.'}
$wa=Read-Att $WindowsRendererReport 'windows-unity-univrm' $wp $wd;$qa=Read-Att $QuestRendererReport 'android-quest-class' $qp $qd;if([string]::Equals($wa.Path,$qa.Path,[StringComparison]::OrdinalIgnoreCase)){throw 'Windows and Quest attestations must be distinct.'}
if([string]::IsNullOrWhiteSpace($Output)){$Output=Join-Path $dir 'bodyrig-release-acceptance.json'};$Output=[IO.Path]::GetFullPath($Output);foreach($p in @($AcceptanceReport,$package,$sessionEvidence,$readinessEvidence,$skinQaEvidence,$wp.Path,$qp.Path,$wd.Path,$qd.Path,$wa.Path,$qa.Path)){if([string]::Equals($Output,$p,[StringComparison]::OrdinalIgnoreCase)){throw 'Release output must not overwrite evidence.'}};if(Test-Path $Output){throw 'Release acceptance output already exists.'};$od=Split-Path -Parent $Output;if(-not(Test-Path $od -PathType Container)){New-Item -ItemType Directory $od -Force|Out-Null}
function Summary($Att,$Probe,$Deformation){[ordered]@{bodyrig_revision=$head;report_sha256=$Att.Hash;probe_report_sha256=$Probe.Hash;deformation_report_sha256=$Deformation.Hash;deformation_sequence_revision=[string]$Deformation.Value.sequence_revision;deformation_observed_at=[string]$Deformation.Value.observed_at;runtime_manifest_sha256=$runtimeHash;avatar_sha256=$avatarHash;bodyprint_sha256=$bodyprintHash;machine_probe=$true;result='pass';renderer_name=[string]$Att.Value.renderer_name;renderer_version=[string]$Att.Value.renderer_version;unity_platform=[string]$Probe.Value.unity_platform;unity_version=[string]$Probe.Value.unity_version;build_guid=[string]$Probe.Value.build_guid;device_model=[string]$Probe.Value.device_model;graphics_device=[string]$Probe.Value.graphics_device;quality_review_revision=[string]$Att.Value.quality_review.revision;quality_review_pass=$true;quality_note=[string]$Att.Value.quality_note;observed_at=[string]$Probe.Value.observed_at;attested_at=[string]$Att.Value.attested_at}}
$out=[ordered]@{format='bodyrig-release-acceptance';version=1;completed_at=[DateTime]::UtcNow.ToString('o');bodyrig_revision=$head;automated_acceptance=[ordered]@{report_sha256=$auto.Hash;package_sha256=$packageHash;body_id=$bodyId;automated_pass=$true;physical_clone_mode='stash-sith-high-fidelity';physical_clone_session_sha256=$sessionHash;physical_clone_readiness_sha256=$readinessHash;skin_qa_report_sha256=$skinQaHash;skin_qa_assessment=[string]$a.skin_qa.automated_assessment;skin_qa_manual_review_required=$true};renderer_acceptance=[ordered]@{windows_unity_univrm=Summary $wa $wp $wd;android_quest_class=Summary $qa $qp $qd};release_gate_pass=$true;production_activation=$true}
$tmp=Join-Path $od ('.'+[IO.Path]::GetFileName($Output)+'.'+[Guid]::NewGuid().ToString('N')+'.tmp');try{$out|ConvertTo-Json -Depth 12|Set-Content $tmp -Encoding UTF8;Move-Item $tmp $Output}finally{if(Test-Path $tmp){Remove-Item $tmp -Force}}
Write-Host "BodyRig release acceptance: PASS | revision=$head | skin=$($a.skin_qa.automated_assessment) | quality=bodyrig-human-quality-v1 | deformation=humanoid-muscle-sweep-v1 | Windows=$($wp.Value.device_model) | Quest=$($qp.Value.device_model)";Write-Host "Release report: $Output";exit 0
