# BodyRig avatar fitting V1

This slice turns a validated `bodyrig-recovery-proof.json` into a portable VRM 1.0 avatar and `.mrbody` package.

## Why this stage is separate

Recovery and avatar fitting are deliberately independent:

```text
video
  -> pinned recovery adapter
  -> canonical tracks
  -> BodyPrint
  -> avatar fitter
  -> body-only appearance policy
  -> VRM 1.0
  -> .mrbody
  -> validated runtime materialization
  -> renderer
```

The completed `.mrbody` and materialized runtime must not require HMR2, PHALP, SMPL-family assets or the original source video at runtime.

## Body versus outfit

BodyRig owns the persistent body identity, not the person's wardrobe. Garments, shoes-as-outfit-items and accessories are external appearance state and must be replaceable without producing a new body identity.

Source video may of course contain clothing. Recovery/identity/reconstruction may observe it as context and occlusion, but a package-producing fitter must declare `capabilities.clothing=false`. BodyRig adds the machine-readable provenance stage:

```text
appearance-boundary / bodyrig.garment-policy / external-outfit-v1
```

The historical `visual_identity.coverage.clothing` value is observation metadata only; it is not a portable garment asset.

SiTH reconstructs the visible surface, so source clothing can still affect an intermediate reconstruction. Physical V1 review must therefore reject a candidate where the source outfit is visibly baked into the persistent body geometry/texture. See `APPEARANCE_BOUNDARY.md`.

## Current fitter

V1 includes `procedural-vrm1` as a deterministic reference fitter.

It is **not** a photorealistic identity reconstruction engine. Its purpose is to prove that source-derived BodyPrint proportions can produce a real, portable VRM 1.0 humanoid that can later be replaced by a higher-fidelity fitting adapter without changing the package/runtime contract.

The reference fitter currently consumes these source-derived shape observations:

- `shoulder_to_height`
- `hip_to_height`
- `arm_to_height`
- `leg_to_height`
- optional `height_scale`

Missing required shape observations fail closed instead of being silently invented.

The resulting avatar embeds `extras.bodyrig.placeholder=true`, making it machine-readable that the visual identity is only a placeholder.

## VRM validation

`avatar.vrm` is not accepted merely because it is a GLB 2.0 file.

BodyRig now validates at least:

- GLB 2.0 container and declared length;
- `extensionsUsed` contains `VRMC_vrm`;
- `extensions.VRMC_vrm.specVersion == "1.0"`;
- required VRM meta (`name`, `authors`, `licenseUrl`);
- VRM humanoid block exists;
- all required humanoid bones exist;
- each required humanoid bone references a unique valid glTF node;
- humanoid-bone scale, when explicitly present, is finite and positive.

A plain `.glb` renamed to `.vrm` is rejected during both package build and import.

## CLI

After `bodyrig-recover` has produced a proof:

```powershell
bodyrig-fit-avatar `
  .\bodyrig-recovery-proof.json `
  --body-id "fixture-person" `
  --name "Fixture Person" `
  --out ".\fixture-person.mrbody"
```

The CLI validates the proof before fitting. It never needs the original source filenames.

The high-fidelity provenance chain records the body/outfit boundary explicitly:

```text
body-recovery -> visual-identity-capture -> [identity_content] -> appearance-boundary -> avatar-fitting
```

For rendering, the package is then materialized through BodyRig rather than manually extracted:

```powershell
bodyrig-materialize `
  .\fixture-person.mrbody `
  --out .\runtime
```

The materialized runtime is bound to the package SHA-256 through `runtime-manifest.json`. The reference Unity acceptance loader enters through that manifest and exposes no public loose-VRM acceptance path.

## Current acceptance level

The interface and package/runtime path may be validated using fixture BodyPrint/recovery proofs before the physical recovery gate is complete.

This does **not** satisfy the physical V1 gate. The first source-derived avatar acceptance remains dependent on issue #2 producing a real video recovery proof on the target rig, followed by issue #3 validation of the **same hash-bound materialized runtime** in a Windows Unity/UniVRM renderer and an Android/Quest-class renderer.

The physical visual/reconstruction review must additionally prove that the persistent BodyRig body does not inherit the source video's outfit as identity geometry/texture. CI cannot truthfully infer hidden body surface under arbitrary clothing from fixtures.

## Next fidelity adapter

A high-fidelity fitter must independently demonstrate at least:

1. silhouette/proportion similarity on held-out source frames;
2. face/head similarity when sufficient face evidence exists;
3. skin/body-surface consistency across viewpoints;
4. explicit treatment of clothing as source occlusion/context rather than portable outfit ownership;
5. garment-neutral persistent body output, with outfits handled outside `.mrbody`;
6. VRM 1.0 portability through the same materialization/renderer path;
7. no hidden recovery/fitting-model dependency at runtime.

Any model or body-representation licensing constraints remain build-time concerns and must not be silently redistributed inside `.mrbody`.
