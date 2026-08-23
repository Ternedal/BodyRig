# BodyRig rig acceptance

BodyRig separates **automated physical recovery acceptance** from **human renderer acceptance** so CI or a successful ML run cannot silently declare the product ready.

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

The harness creates one bounded artifact directory containing:

```text
bodyrig-recovery-preflight.json
bodyrig-recovery-proof.json
person-a.mrbody
bodyrig-acceptance.json
```

The final automated report is bound to:

- exact BodyRig Git revision;
- clean/dirty state;
- recovery adapter + revision;
- selected track and observed-frame count;
- package SHA-256;
- proof/package BodyPrint identity;
- recovery and avatar-fitting provenance;
- VRM 1.0 validation result.

The report stores the source count but not source filenames.

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

## Gate B — renderer acceptance

Use the **same `.mrbody`** whose SHA-256 appears in Gate A.

Required checks:

### Windows

- extract/load `avatar.vrm` through the BodyRig Unity/UniVRM reference path;
- UniVRM import succeeds with VRM0 migration disabled;
- Unity reports a valid Humanoid avatar;
- required humanoid bones are present;
- source-derived proportions are visibly plausible;
- BodyRig Motor State can drive at least the reference shrug/head/gaze path without corruption.

### Android / Quest-class

- load the same accepted `.mrbody` / `avatar.vrm` in an Android/Quest-class build;
- avatar appears with the same identity/proportions contract;
- no build-time HMR2/PHALP/SMPL dependency is required;
- Motor State can be consumed without platform-specific changes to the semantic contract.

Record the operator result only after both checks pass:

```powershell
.\complete-acceptance.ps1 `
  -AcceptanceReport "C:\path\to\bodyrig-acceptance.json" `
  -WindowsRendererPass `
  -QuestRendererPass `
  -QualityNote "VRM loaded on Windows and Quest-class build; proportions and reference motion looked correct"
```

## Gate B integrity rules

`complete-acceptance.ps1` refuses to complete if:

- Gate A did not report `automated_pass=true`;
- Gate A is not still `physical_renderer_acceptance=pending`;
- the current BodyRig Git revision differs from Gate A;
- the BodyRig checkout is dirty;
- the accepted `.mrbody` is missing;
- the package SHA-256 differs from Gate A;
- either renderer pass is omitted.

The output `bodyrig-release-acceptance.json` records the Gate A report hash, package hash, revision and operator-supplied renderer attestation.

The script does **not** inspect the user's eyes or pretend it can verify visual quality automatically. The two renderer switches and quality note are explicit operator attestations.

## What is not proven by V1 acceptance

A V1 PASS does not claim:

- photorealistic face identity;
- high-fidelity hair/clothing reconstruction;
- perfect anthropometric accuracy;
- emotional understanding or consciousness;
- legal rights/consent verification for the source person.

The current `procedural-vrm1` fitter is explicitly marked as a placeholder visual identity. V1 acceptance proves the source-derived body/motion pipeline and portable embodiment contract, not a final photorealistic digital human.
