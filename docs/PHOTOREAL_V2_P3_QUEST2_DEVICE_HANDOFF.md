# Photoreal V2 P3 Quest 2 device handoff

This gate moves the exact final P3 student artifact universe onto a **real Quest 2** without pretending that file staging is runtime installation or visual acceptance.

It is deliberately positioned after the P3 full-software pipeline and before a future Quest renderer-load/performance gate.

## Command

Run from the exact clean BodyRig checkout that produced the P3 review plan:

```powershell
.\prepare-photoreal-v2-p3-quest2-device-handoff.ps1 `
  -RuntimeReviewWorkspace <P3_RUNTIME_REVIEW_WORKSPACE> `
  -StudentOutputRoot <FINAL_P3_OUTPUT_ROOT>
```

When multiple adb devices are online, pass the intended headset serial with `-Serial`.

## What it proves

The operator:

- strict-reads the exact P3 runtime-review plan;
- requires target family `meta-quest` and model `quest-2`;
- re-hashes every final student artifact locally and rejects artifact-universe drift;
- uses only the adb executable pinned by `reference-renderer/renderer-contract.json`;
- requires a physically connected device that identifies as Quest 2;
- stages each exact artifact under a unique create-only device path;
- pulls every staged artifact back and verifies SHA-256 byte-for-byte;
- writes a create-only device-handoff receipt.

## What it does **not** prove

A successful handoff is not runtime installation evidence. The receipt therefore keeps all of these false:

```text
runtime_loaded = false
installed_student_hashes_verified_on_device = false
stereo_rendering_observed = false
vr_safe_frame_pacing_observed = false
human_runtime_visual_acceptance_complete = false
runtime_acceptance_authority = false
photoreal_acceptance_authority = false
production_activation = false
```

The next gate must load the exact staged student through a Quest renderer, measure real runtime performance and bind that evidence back to the P3 review plan. Human visual PASS/FAIL across all eight canonical fidelity dimensions remains mandatory.
