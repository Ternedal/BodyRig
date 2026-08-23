# BodyRig Unity reference renderer

This is the first thin reference client for proving that a completed BodyRig `.mrbody` can be materialized and loaded by a normal Unity/UniVRM runtime without any HMR2, PHALP, SMPL or Python build dependency in the renderer.

It is intentionally **not** the final Kaliv or Quest UI.

## Supported baseline

- Unity 2022.3 LTS or later.
- UniVRM VRM 1.0 package (`com.vrmc.vrm`) plus UniGLTF (`com.vrmc.gltf`).
- VRM 1.0 only: the loader sets `canLoadVrm0X: false` so a V0 avatar cannot accidentally satisfy the BodyRig acceptance path through migration.

The example dependency snippet pins the documented UniVRM v0.131.0 UPM layout. The pin can be advanced independently after renderer acceptance; `.mrbody` remains VRM 1.0 and does not depend on a specific UniVRM release.

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

Copy `Assets/BodyRig/BodyRigAvatarLoader.cs` into the project, place it on a GameObject, and call:

```csharp
await loader.LoadRuntimeAsync(pathToRuntimeManifest);
```

The acceptance loader intentionally exposes no public loose-VRM load method. It:

1. requires `runtime-manifest.json`;
2. validates BodyRig runtime format/version, body identity, package SHA-256 and fixed `avatar.vrm` / `bodyprint.json` paths;
3. requires both materialized payloads beside the manifest;
4. imports that manifest-selected avatar through `UniVRM10.Vrm10.LoadPathAsync`;
5. disables VRM 0.x migration;
6. requires a generated Unity `Animator` with a valid humanoid avatar;
7. verifies all BodyRig-required humanoid bones are addressable through Unity's humanoid mapping;
8. only swaps the active avatar/runtime identity after the replacement has passed those checks.

A failed load leaves the previous known-good avatar and runtime identity alive.

For physical acceptance, `record-renderer-acceptance.ps1` independently re-hashes the same runtime manifest, `avatar.vrm` and `bodyprint.json`, then compares the payload hashes with the accepted `.mrbody` `checksums.json`. That keeps the human visual observation bound to the exact bytes Unity was instructed to load.

## Physical acceptance still required

Repository/unit tests can prove BodyRig's package/runtime structure and source-derived proportion mapping, but issue #3 is not complete until the generated source-derived runtime is loaded in a real Unity/UniVRM player on the Windows target and an Android/Quest-class build, with one hash-bound renderer attestation recorded per platform.
