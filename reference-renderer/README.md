# BodyRig Unity reference renderer

This is the thin reference client for proving that a completed BodyRig `.mrbody` can be materialized and loaded by a normal Unity/UniVRM runtime without HMR2, PHALP, SMPL or Python build dependencies in the renderer.

It is intentionally **not** the final Kaliv or Quest UI.

## Supported baseline

- Unity 2022.3 LTS or later.
- UniVRM VRM 1.0 package (`com.vrmc.vrm`) plus UniGLTF (`com.vrmc.gltf`).
- VRM 1.0 only: the loader sets `canLoadVrm0X: false`, so a V0 avatar cannot satisfy the BodyRig acceptance path through migration.

The dependency snippet pins the documented UniVRM v0.131.0 UPM layout. That pin can advance independently after renderer acceptance; `.mrbody` remains VRM 1.0 and does not depend on a specific UniVRM release.

## Materialize the accepted package first

The reference renderer must **not** be pointed at an arbitrary loose `.vrm`. Materialize the already accepted `.mrbody` instead:

```powershell
bodyrig-materialize `
  "C:\acceptance\person-a.mrbody" `
  --out "C:\acceptance\runtime"
```

`validate-rig.ps1` already performs this step automatically and leaves:

```text
runtime/
  runtime-manifest.json
  avatar.vrm
  bodyprint.json
  provenance.json
  thumbnail.png
  ... optional validated motions
```

The runtime manifest records the exact `.mrbody` SHA-256. Only payload names that passed `.mrbody` validation are materialized.

## Install the dependencies

Merge `Packages/bodyrig-univrm-manifest.snippet.json` into the Unity project's `Packages/manifest.json`.

## Add the loader

Copy the scripts in `Assets/BodyRig/` into the Unity project. `BodyRigAvatarLoader` is the narrow runtime loader:

```csharp
await loader.LoadRuntimeAsync(pathToRuntimeManifest);
```

The loader intentionally exposes no public loose-VRM load method. It:

1. requires `runtime-manifest.json`;
2. validates BodyRig runtime format/version, body identity, package SHA-256 and fixed `avatar.vrm` / `bodyprint.json` paths;
3. requires both materialized payloads beside the manifest;
4. imports the manifest-selected avatar through `UniVRM10.Vrm10.LoadPathAsync`;
5. disables VRM 0.x migration;
6. requires a generated Unity `Animator` with a valid Humanoid avatar;
7. verifies all BodyRig-required Humanoid bones are addressable through Unity's Humanoid mapping;
8. only swaps the active avatar/runtime identity after the replacement has passed those checks.

A failed load leaves the previous known-good avatar and runtime identity alive.

## Machine probe: prove what Unity actually loaded

Physical acceptance now requires `BodyRigRendererProbe.cs` as well as the loader. The probe runs the same manifest-bound loader and writes immutable JSON evidence only after the VRM 1.0 instance, Unity Humanoid avatar and required bones are valid.

Configure these fields on the probe component:

- `loader`: the `BodyRigAvatarLoader` component;
- `runtimeManifestPath`: the exact `runtime/runtime-manifest.json` produced by Gate A;
- `outputPath`: a new evidence path, for example `C:\acceptance\windows-probe.json`;
- `rendererName` / `rendererVersion`: the identity of the reference build;
- `runOnStart`: optional automatic execution.

Or call it explicitly:

```csharp
await probe.RunProbeAsync(pathToRuntimeManifest, pathToProbeJson);
```

The machine report records and binds:

- BodyRig body id;
- `.mrbody` SHA-256 from the runtime manifest;
- runtime-manifest SHA-256;
- `avatar.vrm` SHA-256;
- `bodyprint.json` SHA-256;
- VRM 1.0 load success;
- valid Unity Humanoid result;
- required-bones result;
- Unity runtime platform/version;
- graphics-device name;
- renderer name/version.

Windows evidence is accepted only from Unity `WindowsEditor`/`WindowsPlayer`. Quest-class evidence is accepted only from Unity `Android`. That does not replace the human check that the Android build was actually exercised on the intended Quest-class device; it prevents a Windows probe from being relabelled as Android or vice versa.

## Record the human visual attestation

The operator attestation is deliberately a **second step**. It cannot create a PASS from a quality note alone; it requires the original machine probe and independently re-hashes the package/runtime bytes:

```powershell
.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\acceptance\runtime\runtime-manifest.json" `
  -ProbeReport "C:\acceptance\windows-probe.json" `
  -Platform "windows-unity-univrm" `
  -Pass `
  -RendererName "BodyRig Reference Renderer" `
  -RendererVersion "reference-v1" `
  -QualityNote "Avatar loaded, proportions are plausible, no visible rig collapse or severe clipping."
```

Repeat with the Android/Quest-class probe and `-Platform "android-quest-class"`.

The recorder refuses the attestation unless the machine probe, automated Gate A report, `.mrbody`, materialized runtime manifest, avatar and bodyprint all identify the same bytes. Renderer name/version must also match the machine-produced probe.

## Final release gate

`complete-acceptance.ps1` receives both operator reports **and both original machine probes**. It re-parses and re-hashes all four files independently before allowing `production_activation=true`:

```powershell
.\complete-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -WindowsRendererReport "C:\acceptance\bodyrig-renderer-acceptance-windows.json" `
  -WindowsProbeReport "C:\acceptance\windows-probe.json" `
  -QuestRendererReport "C:\acceptance\bodyrig-renderer-acceptance-quest.json" `
  -QuestProbeReport "C:\acceptance\quest-probe.json"
```

Changing a probe after operator attestation, substituting an avatar/runtime/package, swapping platform evidence or trying to reuse one evidence file for both platforms makes the final gate fail closed.

## Physical acceptance still required

Repository/unit tests prove the package/runtime/evidence mechanics, not visual quality. Issue #3 remains open until a source-derived `.mrbody` from the physical recovery gate is loaded on the Windows target and an Android/Quest-class build, produces the corresponding machine probes, and receives explicit human visual PASS attestations on both platforms.
