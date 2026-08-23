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
  -> VRM 1.0
  -> .mrbody
  -> validated runtime materialization
  -> renderer
```

The completed `.mrbody` and materialized runtime must not require HMR2, PHALP, SMPL-family assets or the original source video at runtime.

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

The resulting provenance chain records both stages:

```text
body-recovery -> avatar-fitting
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

## Next fidelity adapter

After the physical V1 chain is proven, visual identity should advance through a separate high-fidelity fitter adapter rather than by weakening or replacing the existing package/runtime boundaries.

A future adapter should independently demonstrate at least:

1. silhouette/proportion similarity on held-out source frames;
2. face/head similarity when sufficient face evidence exists;
3. texture/skin consistency across viewpoints;
4. explicit hair/clothing coverage or confidence/fallback state;
5. VRM 1.0 portability through the same materialization/renderer path;
6. no hidden recovery/fitting-model dependency at runtime.

Any model or body-representation licensing constraints remain build-time concerns and must not be silently redistributed inside `.mrbody`.
