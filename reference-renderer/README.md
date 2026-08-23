# BodyRig Unity reference renderer

This is the thin physical-acceptance client for proving that a completed BodyRig `.mrbody` can be materialized and loaded by a normal Unity/UniVRM runtime without HMR2, PHALP, SMPL or Python dependencies in the renderer.

It is intentionally **not** the final Kaliv or immersive Quest UI. Its job is narrower: prove the same accepted runtime bytes on a built WindowsPlayer and on Quest-class Android hardware.

## Reproducible project baseline

`reference-renderer/` is now a directly openable Unity project rather than a bag of scripts.

Pinned baseline:

- Unity **6000.3.13f1** (Unity 6.3 LTS project version);
- UniVRM **v0.131.2**;
- `com.vrmc.gltf` from `/Packages/UniGLTF`;
- `com.vrmc.vrm` from `/Packages/VRM10`;
- VRM 1.0 only: `canLoadVrm0X: false`.

`Packages/manifest.json` already contains the required UniVRM Git dependencies. `Packages/bodyrig-univrm-manifest.snippet.json` is retained only as a portable dependency reference.

## Gate A runtime is the only renderer input

The reference renderer must **not** be pointed at an arbitrary loose `.vrm`. Gate A already leaves a validated materialized runtime:

```text
C:\acceptance\
  bodyrig-acceptance.json
  person-a.mrbody
  runtime\
    runtime-manifest.json
    avatar.vrm
    bodyprint.json
    provenance.json
    thumbnail.png
    ... optional validated motions
```

The renderer starts from `runtime-manifest.json`. `BodyRigAvatarLoader` verifies the fixed payload names and package identity, loads only the manifest-selected `avatar.vrm`, disables VRM 0.x migration, and requires a valid Unity Humanoid plus all BodyRig-required bones before the active runtime identity changes.

## Build the physical probe players

From the BodyRig repository:

```powershell
cd .\reference-renderer

.\build-reference-renderer.ps1 -Platform Windows
.\build-reference-renderer.ps1 -Platform Quest
```

The wrapper prefers the pinned Unity `6000.3.13f1` installation and otherwise selects an installed Unity 6.3 LTS editor. `-UnityExe` can override detection.

Default outputs:

```text
reference-renderer\Builds\Windows\BodyRigReferenceProbe.exe
reference-renderer\Builds\Quest\BodyRigReferenceProbe.apk
```

The Unity build entry points create the otherwise-empty probe scene programmatically, so there is no scene/prefab wiring step. The runtime bootstrap creates the loader, probe, camera and light at startup.

The Quest build is ARM64 and a Unity Development build. Android Build Support must be installed for the selected Unity editor.

## Windows physical probe

Run the **built player**, never Unity Editor:

```powershell
.\Builds\Windows\BodyRigReferenceProbe.exe `
  --bodyrig-runtime-manifest "C:\acceptance\runtime\runtime-manifest.json" `
  --bodyrig-probe-output "C:\acceptance\windows-probe.json" `
  --bodyrig-renderer-name "BodyRig Reference Renderer" `
  --bodyrig-renderer-version "reference-v1/univrm-0.131.2"
```

The app loads the avatar, frames it with a simple acceptance camera/light rig and leaves the window open for human visual inspection. A successful machine check writes `windows-probe.json` before showing `BodyRig physical probe: PASS`.

The evidence path is immutable: an existing probe file is not overwritten.

For non-visual automation, add:

```text
--bodyrig-quit-after-probe
```

That is useful for machine validation, but it does **not** replace the later human visual-quality attestation.

## Quest-class physical probe

The reference Quest gate is intentionally a minimal Android renderer proof on actual Quest/Oculus hardware; immersive XR interaction is a separate client concern. The machine gate still requires Unity `Android` plus a Quest/Oculus-identifying `SystemInfo.deviceModel`.

Install the APK:

```powershell
adb install -r .\Builds\Quest\BodyRigReferenceProbe.apk
```

The bootstrap defaults to this runtime location inside Unity's persistent-data root:

```text
BodyRig/runtime/runtime-manifest.json
```

For the fixed application id `dk.ternedal.bodyrig.reference`, a practical ADB staging path on Quest is:

```powershell
$deviceRoot = "/sdcard/Android/data/dk.ternedal.bodyrig.reference/files/BodyRig"

adb shell "mkdir -p $deviceRoot/runtime"
adb push "C:\acceptance\runtime\." "$deviceRoot/runtime/"
adb shell "rm -f $deviceRoot/bodyrig-renderer-probe.json"
adb shell monkey -p dk.ternedal.bodyrig.reference 1
```

After the app shows a machine PASS on the headset, retrieve the probe:

```powershell
adb pull "$deviceRoot/bodyrig-renderer-probe.json" "C:\acceptance\quest-probe.json"
```

If a specific Quest/Android version exposes Unity persistent storage differently, use the path printed by the app/log rather than relabelling evidence. The probe itself will still refuse a generic Android phone.

## What the machine probe proves

`BodyRigRendererProbe` writes evidence only after all of these are true:

- the accepted runtime manifest was loaded;
- `avatar.vrm` loaded as VRM 1.0;
- Unity generated a valid Humanoid avatar;
- required humanoid bones are available;
- package/runtime/avatar/bodyprint hashes are recorded;
- Unity platform/version and a non-empty build GUID are recorded;
- device model and graphics device are recorded;
- renderer name/version are recorded.

The probe itself rejects:

- `WindowsEditor` — Windows acceptance requires `WindowsPlayer`;
- generic Android hardware — Quest acceptance requires Quest/Oculus device identity;
- an empty Unity build GUID;
- overwriting existing evidence.

`record-renderer-acceptance.ps1` repeats the critical byte/platform/device checks, so the recorder remains defense-in-depth against modified or hand-crafted probe JSON.

## Human visual attestation

After inspecting the Windows result:

```powershell
.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\acceptance\runtime\runtime-manifest.json" `
  -ProbeReport "C:\acceptance\windows-probe.json" `
  -Platform "windows-unity-univrm" `
  -Pass `
  -RendererName "BodyRig Reference Renderer" `
  -RendererVersion "reference-v1/univrm-0.131.2" `
  -QualityNote "Avatar loaded as Humanoid; proportions and reference motion path are visually plausible."
```

Repeat with `quest-probe.json` and `-Platform "android-quest-class"` after inspecting the same accepted runtime on Quest hardware.

The operator report cannot activate production and cannot be created from a quality note alone; it is hash-bound to the machine probe and Gate A bytes.

## Final release gate

Only after both machine probes and both human attestations exist:

```powershell
.\complete-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -WindowsRendererReport "C:\acceptance\bodyrig-renderer-acceptance-windows.json" `
  -WindowsProbeReport "C:\acceptance\windows-probe.json" `
  -QuestRendererReport "C:\acceptance\bodyrig-renderer-acceptance-quest.json" `
  -QuestProbeReport "C:\acceptance\quest-probe.json"
```

Changing a probe after attestation, substituting runtime/package bytes, swapping platform evidence or reusing one evidence file for both platforms makes the final gate fail closed.

## Still not proven by repository CI

Repository CI now proves the project structure, pinned dependency contract, bootstrap/build source contracts and the complete non-physical evidence chain. It still does **not** prove that Unity actually compiles this project on the target machine, that Quest deployment succeeds, or that the avatar looks correct.

Those remain physical issue #3 evidence and must be produced from the same source-derived profile that passed issue #2.
