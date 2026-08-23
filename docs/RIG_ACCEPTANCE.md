# BodyRig rig acceptance

BodyRig separates **automated physical recovery acceptance**, **platform renderer acceptance**, and **final release acceptance** so CI, a successful ML run, or a single operator switch cannot silently declare the product ready.

## Gate A — automated target-rig acceptance

Run on the target machine with real, user-supplied full-body video:

```powershell
.\validate-rig.ps1 `
  -Source "C:\video\person-1.mp4","C:\video\person-2.mp4" `
  -ExternalPython "C:\Users\you\AppData\Local\BodyRig\recovery\conda-env\python.exe" `
  -FourDHumansRepo "C:\Users\you\AppData\Local\BodyRig\recovery\4D-Humans" `
  -BodyId "person-a" `
  -Name "Person A"
```

The harness creates one write-once artifact directory containing:

```text
bodyrig-recovery-preflight.json
bodyrig-recovery-proof.json
person-a.mrbody
runtime/
  runtime-manifest.json
  avatar.vrm
  bodyprint.json
  provenance.json
  thumbnail.png
  ... optional validated motions
bodyrig-acceptance.json
```

The runtime directory is materialized from the already validated `.mrbody`; the renderer is never expected to choose or extract a loose VRM itself.

The final automated report is bound to:

- exact BodyRig Git revision;
- clean/dirty state;
- recovery adapter + revision;
- selected track and observed-frame count;
- package SHA-256;
- proof/package BodyPrint identity;
- recovery and avatar-fitting provenance;
- VRM 1.0 validation result;
- exact materialized `runtime/runtime-manifest.json` SHA-256.

The report stores the source count but not source filenames. Gate A refuses to reuse a non-empty output directory so previous evidence cannot silently be overwritten.

### Automated PASS is deliberately incomplete

A valid Gate A report always leaves:

```json
{
  "automated_pass": true,
  "physical_renderer_acceptance": "pending",
  "production_activation": false
}
```

That is intentional. A generated package has not yet proved that Unity/UniVRM can load and render it correctly on the supported clients.

## Gate B — physical renderer evidence

Use the **same `runtime/runtime-manifest.json` from Gate A** on both supported platforms. The reference renderer enters through that manifest rather than a loose `avatar.vrm` path.

Each platform produces its own immutable renderer-attestation file.

### Windows acceptance

Required checks:

- load Gate A's `runtime-manifest.json` through the BodyRig Unity/UniVRM reference path;
- the manifest-selected `avatar.vrm` imports successfully with VRM0 migration disabled;
- Unity reports a valid Humanoid avatar;
- required humanoid bones are present;
- source-derived proportions are visibly plausible;
- BodyRig Motor State can drive at least the reference shrug/head/gaze path without corruption.

After those checks pass, record the evidence:

```powershell
.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\path\to\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\path\to\runtime\runtime-manifest.json" `
  -Platform "windows-unity-univrm" `
  -Pass `
  -RendererName "BodyRig Unity/UniVRM reference renderer" `
  -RendererVersion "Unity 2022.3 LTS / UniVRM <exact version>" `
  -QualityNote "Avatar loaded as Humanoid; proportions and reference Motor State looked correct" `
  -Output "C:\path\to\bodyrig-renderer-acceptance-windows.json"
```

### Android / Quest-class acceptance

Required checks:

- load the same Gate A runtime manifest and materialized avatar in an Android/Quest-class build;
- avatar appears with the same identity/proportions contract;
- no build-time HMR2/PHALP/SMPL dependency is required;
- Motor State can be consumed without platform-specific changes to the semantic contract.

After those checks pass:

```powershell
.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\path\to\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\path\to\runtime\runtime-manifest.json" `
  -Platform "android-quest-class" `
  -Pass `
  -RendererName "BodyRig Unity/UniVRM Quest renderer" `
  -RendererVersion "Unity 2022.3 LTS / UniVRM <exact version> / Quest build <id>" `
  -QualityNote "Same accepted runtime loaded on Quest-class runtime and reference Motor State executed correctly" `
  -Output "C:\path\to\bodyrig-renderer-acceptance-quest.json"
```

Before writing either renderer attestation, `record-renderer-acceptance.ps1` independently:

- re-hashes Gate A's automated acceptance report;
- re-hashes the accepted `.mrbody`;
- requires the exact Gate A runtime-manifest hash;
- opens `.mrbody/checksums.json` without extracting the archive;
- hashes materialized `avatar.vrm` and `bodyprint.json`;
- requires those materialized bytes to match the package payload checksums.

Each renderer-attestation is therefore bound to:

- exact BodyRig Git revision;
- exact Gate A report SHA-256;
- exact accepted `.mrbody` SHA-256;
- exact runtime-manifest SHA-256;
- exact `avatar.vrm` SHA-256;
- exact `bodyprint.json` SHA-256;
- exact body id;
- one explicit platform;
- renderer name/version;
- a non-empty operator quality observation.

A renderer-attestation always contains `production_activation=false`. One platform can never activate production by itself.

## Gate C — final release acceptance

Only after both Gate B files exist:

```powershell
.\complete-acceptance.ps1 `
  -AcceptanceReport "C:\path\to\bodyrig-acceptance.json" `
  -WindowsRendererReport "C:\path\to\bodyrig-renderer-acceptance-windows.json" `
  -QuestRendererReport "C:\path\to\bodyrig-renderer-acceptance-quest.json" `
  -Output "C:\path\to\bodyrig-release-acceptance.json"
```

## Final integrity rules

`complete-acceptance.ps1` independently opens the accepted package checksums again and refuses to complete if:

- Gate A did not report `automated_pass=true`;
- any required Gate A check, including runtime materialization, is missing or false;
- Gate A is not still `physical_renderer_acceptance=pending`;
- the current BodyRig Git revision differs from Gate A;
- the BodyRig checkout is dirty;
- the accepted `.mrbody` is missing or its SHA-256 differs;
- Gate A's runtime-manifest hash is missing/invalid;
- either renderer evidence file is missing;
- Windows and Quest evidence are not two distinct files with the correct platform ids;
- either renderer report references a different Gate A hash, package hash, runtime-manifest hash, body id, or Git revision;
- either renderer report's avatar/bodyprint hashes differ from the accepted package payload checksums;
- either renderer report is not an explicit non-activating PASS;
- renderer name/version/quality evidence is blank;
- any input evidence file would be overwritten.

The final `bodyrig-release-acceptance.json` records hashes of Gate A, the accepted package, the materialized runtime payloads, and both renderer evidence files. Only this Gate C artifact sets:

```json
{
  "release_gate_pass": true,
  "production_activation": true
}
```

The scripts do **not** inspect the operator's eyes or pretend visual quality can be established by CI. The physical observations remain human attestations, but they are separately recorded and cryptographically bound to the exact package/runtime/revision they describe.

## What is not proven by V1 acceptance

A V1 PASS does not claim:

- photorealistic face identity;
- high-fidelity hair/clothing reconstruction;
- perfect anthropometric accuracy;
- emotional understanding or consciousness;
- legal rights/consent verification for the source person.

The current `procedural-vrm1` fitter is explicitly marked as a placeholder visual identity. V1 acceptance proves the source-derived body/motion pipeline and portable embodiment contract, not a final photorealistic digital human.
