param(
    [Parameter(Mandatory = $true)][string]$AcceptanceReport,
    [Parameter(Mandatory = $true)][string]$WindowsRendererReport,
    [Parameter(Mandatory = $true)][string]$WindowsProbeReport,
    [Parameter(Mandatory = $true)][string]$QuestRendererReport,
    [Parameter(Mandatory = $true)][string]$QuestProbeReport,
    [string]$Output = ""
)
$ErrorActionPreference = "Stop"; Set-StrictMode -Version Latest

function Read-Json([string]$Path,[string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    $p=(Resolve-Path -LiteralPath $Path).Path; try{$v=Get-Content -LiteralPath $p -Raw|ConvertFrom-Json}catch{throw "$Label is not valid JSON: $p"}
    [pscustomobject]@{Path=$p;Hash=(Get-FileHash $p -Algorithm SHA256).Hash.ToLowerInvariant();Value=$v}
}
function Need-Sha([string]$v,[string]$f){$n=$v.ToLowerInvariant();if($n -notmatch '^[0-9a-f]{64}$'){throw "$f is not canonical SHA-256."};$n}
function Read-Checksums([string]$Path){
    Add-Type -AssemblyName System.IO.Compression.FileSystem;$z=[IO.Compression.ZipFile]::OpenRead($Path)
    try{$e=$z.GetEntry('checksums.json');if($null-eq$e){throw 'Accepted .mrbody has no checksums.json.'};$s=$e.Open();$r=[IO.StreamReader]::new($s,[Text.Encoding]::UTF8,$true,4096,$false);try{$t=$r.ReadToEnd()}finally{$r.Dispose()};$t|ConvertFrom-Json}finally{$z.Dispose()}
}

$auto=Read-Json $AcceptanceReport 'Acceptance report';$AcceptanceReport=$auto.Path;$a=$auto.Value;$dir=Split-Path -Parent $AcceptanceReport
if([string]$a.format-ne'bodyrig-rig-acceptance'-or[int]$a.version-ne1-or$a.automated_pass-ne$true-or$a.bodyrig_checkout_clean-ne$true-or[string]$a.physical_renderer_acceptance-ne'pending'-or$a.production_activation-ne$false){throw 'Automated acceptance is not a valid pending-renderer PASS.'}
foreach($n in @('bodyrig_checkout_clean','preflight_ok','recovery_adapter_pinned','observed_frames_ge_2','source_derived_shape_present','source_derived_motion_present','bodyprint_matches_package','source_count_matches_package','recovery_provenance_matches','avatar_fitting_provenance_present','avatar_is_vrm_1_0','runtime_materialized_from_package')){$p=$a.checks.PSObject.Properties[$n];if($null-eq$p-or$p.Value-ne$true){throw "Automated acceptance check missing/false: $n"}}
if([int]$a.recovery.observed_frames-lt2-or[string]$a.package.vrm_spec_version-ne'1.0'-or[string]$a.runtime.manifest-ne'runtime/runtime-manifest.json'-or$a.runtime.materialized_from_package-ne$true){throw 'Automated acceptance structural checks failed.'}
$runtimeHash=Need-Sha ([string]$a.runtime.manifest_sha256) 'runtime.manifest_sha256'

$root=(Resolve-Path $PSScriptRoot).Path;$head=(&git -C $root rev-parse HEAD).Trim().ToLowerInvariant();if($LASTEXITCODE-ne0-or$head-notmatch'^[0-9a-f]{40}$'-or$head-ne([string]$a.bodyrig_revision).ToLowerInvariant()){throw 'BodyRig HEAD does not match accepted revision.'};if(@(&git -C $root status --porcelain).Count-gt0){throw 'BodyRig checkout is dirty.'}
$bodyId=[string]$a.package.body_id;if($bodyId-notmatch'^[a-z0-9æøå_-]{1,160}$'){throw 'Invalid body id.'};$package=Join-Path $dir "$bodyId.mrbody";if(-not(Test-Path $package -PathType Leaf)){throw 'Accepted .mrbody missing.'};$package=(Resolve-Path $package).Path;$packageHash=(Get-FileHash $package -Algorithm SHA256).Hash.ToLowerInvariant();if($packageHash-ne(Need-Sha ([string]$a.package.package_sha256) 'package hash')){throw 'Accepted package hash changed.'}
$c=Read-Checksums $package;$avatarHash=Need-Sha ([string]$c.PSObject.Properties['avatar.vrm'].Value) 'avatar checksum';$bodyprintHash=Need-Sha ([string]$c.PSObject.Properties['bodyprint.json'].Value) 'bodyprint checksum'

function Read-Probe([string]$Path,[string]$Platform){
    $f=Read-Json $Path 'Renderer machine probe';$v=$f.Value;$fields=@('format','version','observed_at','platform','unity_platform','unity_version','build_guid','device_model','graphics_device','body_id','package_sha256','runtime_manifest_sha256','avatar_sha256','bodyprint_sha256','vrm10_loaded','humanoid_valid','required_bones_valid','active_renderer')
    if(@(Compare-Object $fields @($v.PSObject.Properties.Name)).Count-ne0-or[string]$v.format-ne'bodyrig-renderer-probe'-or[int]$v.version-ne1-or[string]$v.platform-ne$Platform){throw "Invalid renderer probe: $($f.Path)"}
    if($v.vrm10_loaded-ne$true-or$v.humanoid_valid-ne$true-or$v.required_bones_valid-ne$true){throw "Probe did not prove VRM/Humanoid/bones: $($f.Path)"}
    if([string]$v.body_id-ne$bodyId-or(Need-Sha ([string]$v.package_sha256) 'probe package')-ne$packageHash-or(Need-Sha ([string]$v.runtime_manifest_sha256) 'probe runtime')-ne$runtimeHash-or(Need-Sha ([string]$v.avatar_sha256) 'probe avatar')-ne$avatarHash-or(Need-Sha ([string]$v.bodyprint_sha256) 'probe bodyprint')-ne$bodyprintHash){throw "Probe byte identity mismatch: $($f.Path)"}
    foreach($n in @('observed_at','unity_platform','unity_version','build_guid','device_model','graphics_device')){if([string]::IsNullOrWhiteSpace([string]$v.$n)){throw "Probe missing ${n}: $($f.Path)"}}
    if($Platform-eq'windows-unity-univrm'-and[string]$v.unity_platform-ne'WindowsPlayer'){throw 'Windows release evidence must come from Unity WindowsPlayer.'}
    if($Platform-eq'android-quest-class'){if([string]$v.unity_platform-ne'Android'){throw 'Quest probe must come from Unity Android.'};if([string]$v.device_model-notmatch'(?i)(quest|oculus)'){throw "Quest probe device model is not Quest/Oculus: $($v.device_model)"}}
    if([string]::IsNullOrWhiteSpace([string]$v.active_renderer.name)-or[string]::IsNullOrWhiteSpace([string]$v.active_renderer.version)){throw 'Probe renderer identity missing.'};$f
}
function Read-Att([string]$Path,[string]$Platform,$Probe){
    $f=Read-Json $Path 'Renderer acceptance';$v=$f.Value
    if([string]$v.format-ne'bodyrig-renderer-acceptance'-or[int]$v.version-ne1-or[string]$v.platform-ne$Platform-or[string]$v.result-ne'pass'-or[string]$v.attestation-ne'operator-supplied'-or$v.machine_probe-ne$true-or$v.production_activation-ne$false){throw "Invalid renderer attestation: $($f.Path)"}
    if(([string]$v.bodyrig_revision).ToLowerInvariant()-ne$head-or(Need-Sha ([string]$v.automated_report_sha256) 'att automated')-ne$auto.Hash-or(Need-Sha ([string]$v.probe_report_sha256) 'att probe')-ne$Probe.Hash-or(Need-Sha ([string]$v.package_sha256) 'att package')-ne$packageHash-or(Need-Sha ([string]$v.runtime_manifest_sha256) 'att runtime')-ne$runtimeHash-or(Need-Sha ([string]$v.avatar_sha256) 'att avatar')-ne$avatarHash-or(Need-Sha ([string]$v.bodyprint_sha256) 'att bodyprint')-ne$bodyprintHash-or[string]$v.body_id-ne$bodyId){throw "Renderer attestation binding mismatch: $($f.Path)"}
    if([string]$v.renderer_name-ne[string]$Probe.Value.active_renderer.name-or[string]$v.renderer_version-ne[string]$Probe.Value.active_renderer.version-or[string]$v.unity_platform-ne[string]$Probe.Value.unity_platform-or[string]$v.unity_version-ne[string]$Probe.Value.unity_version-or[string]$v.graphics_device-ne[string]$Probe.Value.graphics_device){throw "Renderer attestation does not match machine probe: $($f.Path)"}
    if([string]::IsNullOrWhiteSpace([string]$v.quality_note)){throw 'Renderer quality note missing.'};$f
}

$wp=Read-Probe $WindowsProbeReport 'windows-unity-univrm';$qp=Read-Probe $QuestProbeReport 'android-quest-class';if([string]::Equals($wp.Path,$qp.Path,[StringComparison]::OrdinalIgnoreCase)){throw 'Windows and Quest probes must be distinct.'}
$wa=Read-Att $WindowsRendererReport 'windows-unity-univrm' $wp;$qa=Read-Att $QuestRendererReport 'android-quest-class' $qp;if([string]::Equals($wa.Path,$qa.Path,[StringComparison]::OrdinalIgnoreCase)){throw 'Windows and Quest attestations must be distinct.'}
if([string]::IsNullOrWhiteSpace($Output)){$Output=Join-Path $dir 'bodyrig-release-acceptance.json'};$Output=[IO.Path]::GetFullPath($Output);foreach($p in @($AcceptanceReport,$package,$wp.Path,$qp.Path,$wa.Path,$qa.Path)){if([string]::Equals($Output,$p,[StringComparison]::OrdinalIgnoreCase)){throw 'Release output must not overwrite evidence.'}};if(Test-Path $Output){throw 'Release acceptance output already exists.'};$od=Split-Path -Parent $Output;if(-not(Test-Path $od -PathType Container)){New-Item -ItemType Directory $od -Force|Out-Null}
function Summary($Att,$Probe){[ordered]@{report_sha256=$Att.Hash;probe_report_sha256=$Probe.Hash;runtime_manifest_sha256=$runtimeHash;avatar_sha256=$avatarHash;bodyprint_sha256=$bodyprintHash;machine_probe=$true;result='pass';renderer_name=[string]$Att.Value.renderer_name;renderer_version=[string]$Att.Value.renderer_version;unity_platform=[string]$Probe.Value.unity_platform;unity_version=[string]$Probe.Value.unity_version;build_guid=[string]$Probe.Value.build_guid;device_model=[string]$Probe.Value.device_model;graphics_device=[string]$Probe.Value.graphics_device;quality_note=[string]$Att.Value.quality_note;observed_at=[string]$Probe.Value.observed_at;attested_at=[string]$Att.Value.attested_at}}
$out=[ordered]@{format='bodyrig-release-acceptance';version=1;completed_at=[DateTime]::UtcNow.ToString('o');bodyrig_revision=$head;automated_acceptance=[ordered]@{report_sha256=$auto.Hash;package_sha256=$packageHash;body_id=$bodyId;automated_pass=$true};renderer_acceptance=[ordered]@{windows_unity_univrm=Summary $wa $wp;android_quest_class=Summary $qa $qp};release_gate_pass=$true;production_activation=$true}
$tmp=Join-Path $od ('.'+[IO.Path]::GetFileName($Output)+'.'+[Guid]::NewGuid().ToString('N')+'.tmp');try{$out|ConvertTo-Json -Depth 12|Set-Content $tmp -Encoding UTF8;Move-Item $tmp $Output}finally{if(Test-Path $tmp){Remove-Item $tmp -Force}}
Write-Host "BodyRig release acceptance: PASS | Windows=$($wp.Value.device_model) | Quest=$($qp.Value.device_model)";Write-Host "Release report: $Output";exit 0
