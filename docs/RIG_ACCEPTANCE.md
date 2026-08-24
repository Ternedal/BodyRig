# BodyRig rig acceptance

BodyRig production acceptance is a byte-bound chain from one real Stash/SiTH clone to the same materialized runtime on WindowsPlayer and Quest-class Android.

CI proves software and tamper boundaries. It never substitutes for the physical clone or the human visual-quality observations.

## Gate 0 — real high-fidelity physical clone

Run the canonical launcher on the target rig with a clean BodyRig checkout:

```powershell
.\clone-body-from-stash-ready.ps1 `
  -PerformerId 123 `
  -BodyId "performer-123"
```

The launcher:

1. binds the session to exact BodyRig Git HEAD and clean/dirty state;
2. validates the pinned target-rig setup;
3. runs live readiness for recovery, SiTH/OpenPose, diffusion model and Stash;
4. hashes that readiness report into the physical-clone session;
5. runs the existing Stash source-selection/recovery/identity/SiTH pipeline;
6. refuses PASS if Git HEAD changed while the long clone was running.

Default physical clone artifacts live outside the checkout under `%LOCALAPPDATA%\BodyRig\physical-clones`. Session/readiness evidence lives under `%LOCALAPPDATA%\BodyRig\physical-clone-sessions`. This prevents the operator path itself from making the repository dirty.

A successful clone session is still **not Gate A acceptance**. It only proves that the canonical physical clone reached a source-derived output.

## Gate A — promote the exact high-fidelity clone

Use the PASS session report from Gate 0:

```powershell
.\accept-physical-clone.ps1 `
  -SessionReport "C:\Users\you\AppData\Local\BodyRig\physical-clone-sessions\performer-123-....json"
```

`accept-physical-clone.ps1` does not fit or rebuild an avatar. It promotes the existing clone bytes into the renderer acceptance chain.

It independently requires:

- current clean BodyRig HEAD equals the clone-session revision;
- session is strict `pass/complete` and started from a clean checkout;
- the immutable readiness report still hashes to the session binding;
- readiness and session agree on the master rig-setup SHA-256;
- recovery preflight reported success;
- package BodyPrint, source count and recovery provenance match the recovery proof;
- package visual-identity provenance matches the visual-identity profile;
- exactly one `visual-identity-capture` stage exists;
- avatar fitting is exactly built-in `sith-smplx-vrm` revision `1`;
- the accepted avatar is VRM 1.0 and is **not** a placeholder;
- source-derived shape/motion evidence exists;
- skin weights are structurally valid;
- anatomical skin QA is run on the exact package/avatar bytes;
- the runtime is materialized from the exact accepted `.mrbody` package.

The resulting write-once acceptance directory contains at least:

```text
bodyrig-acceptance.json
bodyrig-physical-clone-session.json
bodyrig-rig-readiness.json
bodyrig-skin-qa.json
<BodyId>.mrbody
runtime/
  runtime-manifest.json
  avatar.vrm
  bodyprint.json
  provenance.json
  thumbnail.png
```

The Gate A report includes `physical_clone.mode=stash-sith-high-fidelity`, hashes of clone-session/readiness evidence, and a hash-bound `skin_qa` summary. Skin QA classifies anatomically suspicious cross-region weight transfer as `low-risk`, `review` or `high-risk`, but every report keeps `manual_review_required=true`.

This distinction is deliberate: automated analysis can detect suspicious weight topology, but it cannot prove that shoulders, elbows, knees, wrists, clothes and the full body deform visually well in motion. Even `low-risk` therefore still needs physical inspection. Conversely, `high-risk` is a strong review signal rather than an automatic veto if direct physical evidence shows acceptable deformation.

Gate A records `placeholder_avatar=false`, `automated_pass=true`, `physical_renderer_acceptance=pending`, and `production_activation=false`.

See `SKIN_QA.md` for the algorithm, thresholds and limitations.

### Safely resume an interrupted acceptance run

Use the read-only status checker instead of inferring the next gate from filenames:

```powershell
.\physical-acceptance-status.ps1 `
  -SessionReport "C:\path\to\bodyrig-physical-clone-session.json"
```

or, after Gate A exists:

```powershell
.\physical-acceptance-status.ps1 `
  -AcceptanceDir "C:\path\to\acceptance"
```

Equivalent CLI:

```powershell
bodyrig-acceptance-status --acceptance-dir "C:\path\to\acceptance"
```

The checker is intentionally read-only. It re-hashes the accepted `.mrbody`, runtime manifest, physical-clone session, readiness and skin-QA evidence; validates machine/deformation/attestation links; verifies embedded renderer revision consistency; and reports the exact next gate. It prefers the canonical `windows-evidence/` and `quest-evidence/` directories, accepts a complete legacy root-file pair for backward compatibility, but rejects ambiguous mixed layouts. If the evidence set is internally inconsistent or appears mutated, it returns `ERROR` rather than guessing. Use `-Json` / `--json` for machine-readable output.

### Legacy recovery Gate A

`run-physical-gate.ps1` / `validate-rig.ps1` remain useful for lower-level recovery and procedural-avatar diagnostics. They are no longer sufficient to enter renderer/release production acceptance. A procedural placeholder can therefore prove recovery mechanics without ever becoming `production_activation=true`.

The lower-level diagnostic path must still bind recovery to both pinned 4D-Humans and PHALP checkouts; omitting PHALP is not a supported shortcut:

```powershell
.\validate-rig.ps1 `
  -Source "C:\video\person-1.mp4","C:\video\person-2.mp4" `
  -ExternalPython "C:\Users\you\AppData\Local\BodyRig\recovery\conda-env\python.exe" `
  -FourDHumansRepo "C:\Users\you\AppData\Local\BodyRig\recovery\4D-Humans" `
  -PhalpRepo "C:\Users\you\AppData\Local\BodyRig\recovery\PHALP" `
  -BodyId "person-a" `
  -Name "Person A"
```

## Gate B — physical renderer + deformation evidence

Both supported platforms must load the **same `runtime/runtime-manifest.json` from high-fidelity Gate A**. The renderer never selects a loose VRM independently.

The reference renderer is pinned to Unity `6000.3.13f1` and UniVRM `v0.131.2`. Its canonical identity lives in `reference-renderer/renderer-contract.json`, which also records the application id and deformation-sequence revision. Its build wrapper requires a clean BodyRig checkout, embeds exact Git HEAD into the built player/APK, and re-checks HEAD after the build. The runtime probes read that revision from an embedded generated `Resources` asset; it is not supplied by the launch command.

The reference player first writes the renderer machine probe and then executes the fixed `humanoid-muscle-sweep-v1` sequence:

1. `neutral`;
2. `arms_abduction`;
3. `elbows_flexed`;
4. `arms_forward`;
5. `left_leg_lift`;
6. `knee_flexion`.

The sequence uses Unity Humanoid muscles through `HumanPoseHandler`, not avatar-specific local bone axes. Every pose is held for the fixed evidence interval, all required muscle names must resolve, and the baseline HumanPose is restored after the evidence run. The player then loops the same poses for human inspection.

The resulting `bodyrig-deformation-probe` v1 is machine evidence that the sequence actually ran. It binds the exact BodyRig build revision, package/runtime/avatar/BodyPrint bytes plus Unity build GUID, platform/version and physical device model. It does **not** claim that the visual deformation was good; `manual_review_required=true` remains mandatory.

### Atomic evidence-pair commit

The runtime necessarily produces the machine probe before the deformation probe. The platform wrappers therefore never point the player directly at canonical evidence filenames. Each attempt gets a unique local staging directory:

- Windows: `.bodyrig-windows-attempt-<uuid>`;
- Quest: `.bodyrig-quest-attempt-<uuid>`.

Both files must exist and pass all platform/revision/runtime/sequence checks while still staged. Only then is the **whole directory** renamed to the canonical evidence directory. If the player, ADB, validation or build fails before commit, the staging directory is removed and no canonical half-pair is left behind.

The default canonical directories are:

```text
windows-evidence/
  windows-probe.json
  windows-deformation-probe.json
quest-evidence/
  quest-probe.json
  quest-deformation-probe.json
```

A canonical evidence directory is create-only. Reusing an existing directory is refused. Custom `-ProbeOutput` / `-DeformationOutput` values must be supplied together and share one dedicated, non-existing evidence directory.

### Windows acceptance

Build/run the physical WindowsPlayer against the Gate A directory:

```powershell
.\run-windows-renderer-probe.ps1 `
  -AcceptanceDir "C:\path\to\acceptance"
```

The wrapper requires both staged outputs before it atomically commits `windows-evidence/`. It checks that both probes contain the exact Gate A BodyRig revision, that the deformation probe completed the ordered six-pose sequence, and that it came from the same build GUID, platform, body id and package/runtime/avatar/BodyPrint bytes as the machine probe.

After watching the player cycle the same sequence and confirming actual visual quality, record the human observation with the reference helper:

```powershell
.\record-reference-renderer-acceptance.ps1 `
  -AcceptanceDir "C:\path\to\acceptance" `
  -Platform "windows-unity-univrm" `
  -QualityNote "Fixed deformation sweep reviewed: identity/proportions, shoulders, elbows, wrists, hips and knees acceptable"
```

The helper reads `renderer_name` and `renderer_version` from `reference-renderer/renderer-contract.json`, requires the machine probe to report the same identity, resolves the canonical evidence pair, and calls the lower-level `record-renderer-acceptance.ps1`. The operator therefore attests only the physical quality observation; renderer identity is not free-text human input.

### Quest-class acceptance

Build/install/run the same reference project against the same Gate A runtime:

```powershell
.\run-quest-renderer-probe.ps1 `
  -AcceptanceDir "C:\path\to\acceptance"
```

The Quest app writes its pair in app-local storage. The wrapper waits until both remote files exist, pulls both into the local attempt directory, validates them there, and only then commits `quest-evidence/`. No local canonical partial pair is created on ADB/app failure.

The machine/deformation probes must carry the exact Gate A BodyRig build revision, come from Unity Android on Quest/Oculus-identifying hardware, and match each other on build/device and accepted byte identities.

After inspecting the fixed sequence in the headset:

```powershell
.\record-reference-renderer-acceptance.ps1 `
  -AcceptanceDir "C:\path\to\acceptance" `
  -Platform "android-quest-class" `
  -QualityNote "Same fixed deformation sweep and accepted runtime reviewed on Quest-class hardware"
```

Before accepting either human quality attestation, the helper verifies the machine-reported renderer identity against the canonical renderer contract. The lower-level `record-renderer-acceptance.ps1` then independently revalidates high-fidelity Gate A lineage, clone/readiness hashes, anatomical skin-QA identity, exact clean revision, package/runtime bytes, the embedded renderer revision, the ordinary machine probe and the deterministic deformation probe. The renderer report stores `deformation_report_sha256`, `deformation_sequence_revision=humanoid-muscle-sweep-v1` and `deformation_probe=true`, so the operator's QualityNote is explicitly tied to the exact sweep that was reviewed. Each renderer report remains non-activating: `production_activation=false`.

The first physical high-fidelity clone must compare static skin-QA measurements with the fixed sweep around arm/torso contact, shoulders, elbows, wrists/hands, hips, knees and legs. Nearest-vertex transfer is upgraded only if this physical evidence shows the need.

## Gate C — final release acceptance

Only after both ordinary machine probes, both deterministic deformation probes and both operator attestations exist:

```powershell
.\complete-acceptance.ps1 `
  -AcceptanceReport "C:\path\to\acceptance\bodyrig-acceptance.json" `
  -WindowsRendererReport "C:\path\to\acceptance\bodyrig-renderer-acceptance-windows.json" `
  -WindowsProbeReport "C:\path\to\acceptance\windows-evidence\windows-probe.json" `
  -WindowsDeformationReport "C:\path\to\acceptance\windows-evidence\windows-deformation-probe.json" `
  -QuestRendererReport "C:\path\to\acceptance\bodyrig-renderer-acceptance-quest.json" `
  -QuestProbeReport "C:\path\to\acceptance\quest-evidence\quest-probe.json" `
  -QuestDeformationReport "C:\path\to\acceptance\quest-evidence\quest-deformation-probe.json"
```

The final gate again checks high-fidelity clone lineage, non-placeholder status, package provenance, package/runtime hashes, exact clean BodyRig revision, clone/readiness/skin-QA evidence, both embedded renderer revisions, both physical renderer probes, both deformation probes, and both human attestations.

Each deformation report must:

- have exact `humanoid-muscle-sweep-v1` revision;
- contain all six poses in the canonical order;
- report `required_muscles_resolved=true`, `restored_neutral=true`, `complete=true` and `manual_review_required=true`;
- carry the exact accepted BodyRig build revision;
- match the corresponding renderer probe's Unity build GUID/platform/version/device;
- match the accepted body id and package/runtime/avatar/BodyPrint hashes;
- have its exact SHA-256 and sequence revision copied into the corresponding operator attestation.

Final release therefore rejects a renderer attestation that points at a substituted, modified or different deformation run, or a player built from another BodyRig revision, even if that alternate evidence otherwise looks structurally valid.

Only the final `bodyrig-release-acceptance` artifact can contain:

```json
{
  "release_gate_pass": true,
  "production_activation": true
}
```

Its automated-acceptance summary records physical clone lineage and skin-QA evidence. Each platform summary also records the renderer BodyRig revision, deformation-report SHA-256, sequence revision and deformation observation time, so final release evidence is traceable back to the exact code/build and stress-pose run on each physical device.

## What the gates still do not automate

The scripts do not pretend to inspect visual quality. Human observations remain required for identity/proportion plausibility, skinning, deformation and motion quality. CI fixtures cannot close those gates.

Skin QA narrows uncertainty by measuring structural weight validity and cross-region leakage risk. The deterministic sweep narrows it further by proving that the same set of stress poses was actually exercised on both builds. Neither component decides whether the deformation *looks* acceptable.

A production PASS also does not claim photorealistic face identity, perfect hair/clothing reconstruction, perfect anthropometric accuracy, emotional understanding, consciousness, or legal rights/consent verification for source material.