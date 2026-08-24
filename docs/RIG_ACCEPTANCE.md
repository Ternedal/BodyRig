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
- the runtime is materialized from the exact accepted `.mrbody` package.

The resulting write-once acceptance directory contains at least:

```text
bodyrig-acceptance.json
bodyrig-physical-clone-session.json
bodyrig-rig-readiness.json
<BodyId>.mrbody
runtime/
  runtime-manifest.json
  avatar.vrm
  bodyprint.json
  provenance.json
  thumbnail.png
```

The Gate A report includes `physical_clone.mode=stash-sith-high-fidelity` and hashes of the copied clone-session and readiness evidence. It records `placeholder_avatar=false`, `automated_pass=true`, `physical_renderer_acceptance=pending`, and `production_activation=false`.

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

## Gate B — physical renderer evidence

Both supported platforms must load the **same `runtime/runtime-manifest.json` from high-fidelity Gate A**. The renderer never selects a loose VRM independently.

Before accepting a human quality attestation, `record-renderer-acceptance.ps1` independently revalidates the lineage:

- high-fidelity Gate A mode and `placeholder_avatar=false`;
- clone-session/readiness evidence hashes;
- exact clean BodyRig revision;
- accepted `.mrbody` package hash;
- package provenance contains one visual-identity stage and built-in `sith-smplx-vrm` v1 fitting;
- runtime manifest hash and materialized avatar/bodyprint hashes;
- machine probe byte identity;
- actual `WindowsPlayer` for Windows;
- actual Android + Quest/Oculus-identifying device model for Quest-class acceptance.

### Windows acceptance

After the built WindowsPlayer writes its machine probe and the avatar visibly passes the required quality checks:

```powershell
.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\path\to\acceptance\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\path\to\acceptance\runtime\runtime-manifest.json" `
  -ProbeReport "C:\path\to\windows-probe.json" `
  -Platform "windows-unity-univrm" `
  -Pass `
  -RendererName "BodyRig Unity/UniVRM reference renderer" `
  -RendererVersion "Unity 2022.3 LTS / UniVRM <exact version>" `
  -QualityNote "Source-derived identity/proportions and reference motion looked correct"
```

The first high-fidelity physical clone must specifically be inspected for cross-limb skin-weight leakage around arm/torso, legs and hands. Nearest-vertex transfer is upgraded only if this physical evidence shows the need.

### Quest-class acceptance

After the same runtime is loaded by the Quest-class Android build and its machine probe is written:

```powershell
.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\path\to\acceptance\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\path\to\acceptance\runtime\runtime-manifest.json" `
  -ProbeReport "C:\path\to\quest-probe.json" `
  -Platform "android-quest-class" `
  -Pass `
  -RendererName "BodyRig Unity/UniVRM Quest renderer" `
  -RendererVersion "Unity 2022.3 LTS / UniVRM <exact version> / Quest build <id>" `
  -QualityNote "Same source-derived accepted runtime rendered correctly on Quest-class hardware"
```

Each renderer report remains non-activating: `production_activation=false`.

## Gate C — final release acceptance

Only after both machine probes and both operator attestations exist:

```powershell
.\complete-acceptance.ps1 `
  -AcceptanceReport "C:\path\to\acceptance\bodyrig-acceptance.json" `
  -WindowsRendererReport "C:\path\to\bodyrig-renderer-acceptance-windows.json" `
  -WindowsProbeReport "C:\path\to\windows-probe.json" `
  -QuestRendererReport "C:\path\to\bodyrig-renderer-acceptance-quest.json" `
  -QuestProbeReport "C:\path\to\quest-probe.json"
```

The final gate again checks high-fidelity clone lineage, non-placeholder status, package provenance, package/runtime hashes, exact clean BodyRig revision, WindowsPlayer evidence, Quest device evidence, and all cross-file hash bindings.

Only the final `bodyrig-release-acceptance` artifact can contain:

```json
{
  "release_gate_pass": true,
  "production_activation": true
}
```

Its automated-acceptance summary also records the physical clone mode and the clone-session/readiness SHA-256 values, so the final release artifact remains traceable back to the physical clone that produced the accepted body.

## What the gates still do not automate

The scripts do not pretend to inspect visual quality. Human observations remain required for identity/proportion plausibility, skinning, deformation and motion quality. CI fixtures cannot close those gates.

A production PASS also does not claim photorealistic face identity, perfect hair/clothing reconstruction, perfect anthropometric accuracy, emotional understanding, consciousness, or legal rights/consent verification for source material.
