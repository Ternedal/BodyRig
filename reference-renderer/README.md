# BodyRig Unity reference renderer

This is the first thin reference client for proving that a completed BodyRig `avatar.vrm` can be loaded by a normal Unity/UniVRM runtime without any HMR2, PHALP, SMPL or Python build dependency.

It is intentionally **not** the final Kaliv or Quest UI.

## Supported baseline

- Unity 2022.3 LTS or later.
- UniVRM VRM 1.0 package (`com.vrmc.vrm`) plus UniGLTF (`com.vrmc.gltf`).
- VRM 1.0 only: the loader sets `canLoadVrm0X: false` so a V0 avatar cannot accidentally satisfy the BodyRig acceptance path through migration.

The example dependency snippet pins the documented UniVRM v0.131.0 UPM layout. The pin can be advanced independently after renderer acceptance; `.mrbody` remains VRM 1.0 and does not depend on a specific UniVRM release.

## Install the dependencies

Merge `Packages/bodyrig-univrm-manifest.snippet.json` into the Unity project's `Packages/manifest.json`.

## Add the loader

Copy `Assets/BodyRig/BodyRigAvatarLoader.cs` into the project, place it on a GameObject, and call:

```csharp
await loader.LoadAsync(pathToAvatarVrm);
```

The loader:

1. requires an existing local `.vrm` path;
2. imports through `UniVRM10.Vrm10.LoadPathAsync`;
3. disables VRM 0.x migration;
4. requires a generated Unity `Animator` with a valid humanoid avatar;
5. verifies all BodyRig-required humanoid bones are addressable through Unity's humanoid mapping;
6. only swaps the active avatar after the replacement has passed those checks.

A failed load leaves the previous known-good avatar alive.

## Physical acceptance still required

Repository/unit tests can prove BodyRig's GLB/VRM structure and source-derived proportion mapping, but issue #3 is not complete until the generated `.mrbody` is extracted and loaded in a real Unity/UniVRM player on the Windows target and an Android/Quest-class build.
