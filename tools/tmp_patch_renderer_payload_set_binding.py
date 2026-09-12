from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    with path.open("r", encoding="utf-8", newline="") as stream:
        text = stream.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    old_native = old.replace("\n", newline)
    new_native = new.replace("\n", newline)
    count = text.count(old_native)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one patch anchor, found {count}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(text.replace(old_native, new_native, 1))


recorder = Path("record-renderer-acceptance.ps1")
replace_once(
    recorder,
    '''$reportHash = Sha256 $AcceptanceReport

$runtimeFile = Read-JsonFile $RuntimeManifest "Runtime manifest"; $RuntimeManifest = $runtimeFile.Path; $runtime = $runtimeFile.Value
''',
    '''$reportHash = Sha256 $AcceptanceReport
$checksums = Read-PackageJson $packagePath "checksums.json" "checksums.json"
$packagePayloadNames = @($checksums.PSObject.Properties | ForEach-Object { [string]$_.Name })
$gatePayloadNames = @($report.package.payload_names | ForEach-Object { [string]$_ })
$gatePayloadSeen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($payloadName in $gatePayloadNames) {
    if (-not $gatePayloadSeen.Add($payloadName) -or $packagePayloadNames -cnotcontains $payloadName) { throw "Gate A package payload set does not match the accepted .mrbody checksums." }
}
if ($gatePayloadSeen.Count -ne $packagePayloadNames.Count) { throw "Gate A package payload set does not match the accepted .mrbody checksums." }

$runtimeFile = Read-JsonFile $RuntimeManifest "Runtime manifest"; $RuntimeManifest = $runtimeFile.Path; $runtime = $runtimeFile.Value
''',
)
replace_once(
    recorder,
    '''if (@($runtime.payloads) -notcontains "avatar.vrm" -or @($runtime.payloads) -notcontains "bodyprint.json") { throw "Runtime manifest does not include required avatar/bodyprint payloads." }
$runtimeManifestHash = Sha256 $RuntimeManifest; if ($runtimeManifestHash -ne $acceptedRuntimeManifestHash) { throw "Runtime manifest SHA-256 no longer matches Gate A." }
''',
    '''if (@($runtime.payloads) -notcontains "avatar.vrm" -or @($runtime.payloads) -notcontains "bodyprint.json") { throw "Runtime manifest does not include required avatar/bodyprint payloads." }
$runtimePayloadNames = @($runtime.payloads | ForEach-Object { [string]$_ })
$runtimePayloadSeen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($payloadName in $runtimePayloadNames) {
    if (-not $runtimePayloadSeen.Add($payloadName) -or $packagePayloadNames -cnotcontains $payloadName) { throw "Runtime manifest payload set does not match the accepted .mrbody checksums." }
}
if ($runtimePayloadSeen.Count -ne $packagePayloadNames.Count) { throw "Runtime manifest payload set does not match the accepted .mrbody checksums." }
$runtimeManifestHash = Sha256 $RuntimeManifest; if ($runtimeManifestHash -ne $acceptedRuntimeManifestHash) { throw "Runtime manifest SHA-256 no longer matches Gate A." }
''',
)
replace_once(
    recorder,
    '''$runtimeDir = Split-Path -Parent $RuntimeManifest; $avatarPath = Join-Path $runtimeDir "avatar.vrm"; $bodyprintPath = Join-Path $runtimeDir "bodyprint.json"
if (-not (Test-Path $avatarPath -PathType Leaf) -or -not (Test-Path $bodyprintPath -PathType Leaf)) { throw "Materialized runtime is missing avatar.vrm or bodyprint.json." }
$avatarHash = Sha256 $avatarPath; $bodyprintHash = Sha256 $bodyprintPath; $checksums = Read-PackageJson $packagePath "checksums.json" "checksums.json"
''',
    '''$runtimeDir = Split-Path -Parent $RuntimeManifest; $avatarPath = Join-Path $runtimeDir "avatar.vrm"; $bodyprintPath = Join-Path $runtimeDir "bodyprint.json"
if (-not (Test-Path $avatarPath -PathType Leaf) -or -not (Test-Path $bodyprintPath -PathType Leaf)) { throw "Materialized runtime is missing avatar.vrm or bodyprint.json." }
foreach ($payloadName in $packagePayloadNames) {
    $payloadPath = Join-Path $runtimeDir $payloadName
    if (-not (Test-Path -LiteralPath $payloadPath -PathType Leaf)) { throw "Materialized runtime is missing accepted package payload: $payloadName" }
    $expectedPayloadHash = Require-Sha ([string]$checksums.PSObject.Properties[$payloadName].Value) "checksums.$payloadName"
    if ((Sha256 $payloadPath) -ne $expectedPayloadHash) { throw "Materialized runtime payload hash does not match the accepted .mrbody: $payloadName" }
}
$avatarHash = Sha256 $avatarPath; $bodyprintHash = Sha256 $bodyprintPath
''',
)

test = Path("tests/test-complete-acceptance.ps1")
replace_once(
    test,
    '''    $f=New-Fixture "runtime-manifest-bodyprint-hash";$j=Get-Content $f.RuntimeManifestPath -Raw|ConvertFrom-Json;$j.bodyprint_sha256="0"*64;$j|ConvertTo-Json -Depth 8 -Compress|Set-Content $f.RuntimeManifestPath -Encoding UTF8;$f.RuntimeManifestHash=(Get-FileHash $f.RuntimeManifestPath -Algorithm SHA256).Hash.ToLowerInvariant();$f.Report.runtime.manifest_sha256=$f.RuntimeManifestHash;Save-Report $f;$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "runtime manifest bodyprint hash tamper";Write-Host "PASS: runtime manifest bodyprint hash binding tamper rejected"
''',
    '''    $f=New-Fixture "runtime-manifest-bodyprint-hash";$j=Get-Content $f.RuntimeManifestPath -Raw|ConvertFrom-Json;$j.bodyprint_sha256="0"*64;$j|ConvertTo-Json -Depth 8 -Compress|Set-Content $f.RuntimeManifestPath -Encoding UTF8;$f.RuntimeManifestHash=(Get-FileHash $f.RuntimeManifestPath -Algorithm SHA256).Hash.ToLowerInvariant();$f.Report.runtime.manifest_sha256=$f.RuntimeManifestHash;Save-Report $f;$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "runtime manifest bodyprint hash tamper";Write-Host "PASS: runtime manifest bodyprint hash binding tamper rejected"
    $f=New-Fixture "runtime-payload-set-co-tamper";$tamperedPayloads=@("avatar.vrm","bodyprint.json","thumbnail.png","motions/idle.vrma");$j=Get-Content $f.RuntimeManifestPath -Raw|ConvertFrom-Json;$j.payloads=$tamperedPayloads;$j|ConvertTo-Json -Depth 8 -Compress|Set-Content $f.RuntimeManifestPath -Encoding UTF8;$f.RuntimeManifestHash=(Get-FileHash $f.RuntimeManifestPath -Algorithm SHA256).Hash.ToLowerInvariant();$f.Report.runtime.manifest_sha256=$f.RuntimeManifestHash;$f.Report.package.payload_names=$tamperedPayloads;Save-Report $f;$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "co-tampered runtime and Gate A payload set";Write-Host "PASS: package checksums remain independent payload-set authority"
    $f=New-Fixture "runtime-provenance-tamper";$p=New-Probe $f "windows-unity-univrm" (Join-Path $f.Artifacts "probe.json");Add-Content (Join-Path $f.RuntimeDir "provenance.json") "tamper";Assert-Failure (Invoke-RendererRecord $f "windows-unity-univrm" $p (Join-Path $f.Artifacts "att.json")) "runtime provenance byte tamper";Write-Host "PASS: every materialized runtime payload remains package-checksum-bound"
''',
)
