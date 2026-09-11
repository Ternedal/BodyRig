from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    effective_old = old.replace("\n", newline)
    effective_new = new.replace("\n", newline)
    count = text.count(effective_old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, found {count}")
    target.write_bytes(text.replace(effective_old, effective_new, 1).encode("utf-8"))


replace_once(
    "record-renderer-acceptance.ps1",
    '$expectedRuntimeFields = @("format","version","body_id","body_name","package_sha256","avatar","bodyprint","payloads")',
    '$expectedRuntimeFields = @("format","version","body_id","body_name","package_sha256","avatar","avatar_sha256","bodyprint","bodyprint_sha256","payloads")',
)

replace_once(
    "record-renderer-acceptance.ps1",
    'if ([string]$runtime.avatar -ne "avatar.vrm" -or [string]$runtime.bodyprint -ne "bodyprint.json") { throw "Runtime manifest contains unexpected avatar/bodyprint paths." }\nif (@($runtime.payloads) -notcontains "avatar.vrm" -or @($runtime.payloads) -notcontains "bodyprint.json") { throw "Runtime manifest does not include required avatar/bodyprint payloads." }',
    'if ([string]$runtime.avatar -ne "avatar.vrm" -or [string]$runtime.bodyprint -ne "bodyprint.json") { throw "Runtime manifest contains unexpected avatar/bodyprint paths." }\n$runtimeAvatarManifestHash = Require-Sha ([string]$runtime.avatar_sha256) "runtime.avatar_sha256"\n$runtimeBodyprintManifestHash = Require-Sha ([string]$runtime.bodyprint_sha256) "runtime.bodyprint_sha256"\nif ([string]$runtime.avatar_sha256 -cne $runtimeAvatarManifestHash -or [string]$runtime.bodyprint_sha256 -cne $runtimeBodyprintManifestHash) { throw "Runtime manifest payload SHA-256 fields must be canonical lower-case." }\nif (@($runtime.payloads) -notcontains "avatar.vrm" -or @($runtime.payloads) -notcontains "bodyprint.json") { throw "Runtime manifest does not include required avatar/bodyprint payloads." }',
)

replace_once(
    "record-renderer-acceptance.ps1",
    'if ($avatarHash -ne $expectedAvatarHash -or $bodyprintHash -ne $expectedBodyprintHash) { throw "Materialized runtime payload hashes do not match the accepted .mrbody." }\nif ((Require-Sha ([string]$skinQa.avatar_sha256) "skin QA avatar hash") -ne $avatarHash) { throw "Anatomical skin QA was not run on the accepted avatar bytes." }',
    'if ($avatarHash -ne $expectedAvatarHash -or $bodyprintHash -ne $expectedBodyprintHash) { throw "Materialized runtime payload hashes do not match the accepted .mrbody." }\nif ($runtimeAvatarManifestHash -ne $avatarHash -or $runtimeBodyprintManifestHash -ne $bodyprintHash) { throw "Runtime manifest payload SHA-256 bindings do not match materialized runtime bytes." }\nif ((Require-Sha ([string]$skinQa.avatar_sha256) "skin QA avatar hash") -ne $avatarHash) { throw "Anatomical skin QA was not run on the accepted avatar bytes." }',
)

replace_once(
    "tests/test-complete-acceptance.ps1",
    '$runtimeManifest=[ordered]@{format="bodyrig-runtime-assets";version=1;body_id=$bodyId;body_name="Fixture Body";package_sha256=$packageHash;avatar="avatar.vrm";bodyprint="bodyprint.json";payloads=@("avatar.vrm","bodyprint.json","provenance.json","thumbnail.png")}',
    '$runtimeManifest=[ordered]@{format="bodyrig-runtime-assets";version=1;body_id=$bodyId;body_name="Fixture Body";package_sha256=$packageHash;avatar="avatar.vrm";avatar_sha256=$avatarHash;bodyprint="bodyprint.json";bodyprint_sha256=$bodyprintHash;payloads=@("avatar.vrm","bodyprint.json","provenance.json","thumbnail.png")}',
)

replace_once(
    "tests/test-complete-acceptance.ps1",
    '    $f=New-Fixture "runtime-avatar";$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Add-Content (Join-Path $f.RuntimeDir "avatar.vrm") "tamper";Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "runtime avatar tamper"',
    '    $f=New-Fixture "runtime-manifest-avatar-hash";$j=Get-Content $f.RuntimeManifestPath -Raw|ConvertFrom-Json;$j.avatar_sha256="0"*64;$j|ConvertTo-Json -Depth 8 -Compress|Set-Content $f.RuntimeManifestPath -Encoding UTF8;$f.RuntimeManifestHash=(Get-FileHash $f.RuntimeManifestPath -Algorithm SHA256).Hash.ToLowerInvariant();$f.Report.runtime.manifest_sha256=$f.RuntimeManifestHash;Save-Report $f;$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "runtime manifest avatar hash tamper";Write-Host "PASS: runtime manifest avatar hash binding tamper rejected"\n    $f=New-Fixture "runtime-manifest-bodyprint-hash";$j=Get-Content $f.RuntimeManifestPath -Raw|ConvertFrom-Json;$j.bodyprint_sha256="0"*64;$j|ConvertTo-Json -Depth 8 -Compress|Set-Content $f.RuntimeManifestPath -Encoding UTF8;$f.RuntimeManifestHash=(Get-FileHash $f.RuntimeManifestPath -Algorithm SHA256).Hash.ToLowerInvariant();$f.Report.runtime.manifest_sha256=$f.RuntimeManifestHash;Save-Report $f;$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "runtime manifest bodyprint hash tamper";Write-Host "PASS: runtime manifest bodyprint hash binding tamper rejected"\n    $f=New-Fixture "runtime-avatar";$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Add-Content (Join-Path $f.RuntimeDir "avatar.vrm") "tamper";Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "runtime avatar tamper"',
)
