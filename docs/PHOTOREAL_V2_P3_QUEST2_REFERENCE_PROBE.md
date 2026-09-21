# Photoreal V2 P3 Quest 2 reference machine probe

This gate takes the exact final P3 student that already passed the software pipeline and byte-for-byte Quest 2 handoff, loads it through BodyRig's physical Unity/UniVRM reference player on a real Quest 2 and records machine evidence.

It remains deliberately **non-accepting** until the separate human visual review is complete.

## Canonical XR runtime

Quest builds now use a dedicated create-only contract:

`reference-renderer/quest-xr-contract.json`

The contract pins:

- XR Plug-in Management `4.5.3`;
- Unity OpenXR `1.16.1`;
- provider `openxr`;
- Android / Meta Quest / Quest 2;
- loader type `UnityEngine.XR.OpenXR.OpenXRLoader`;
- single-pass-instanced rendering;
- XR Management runtime initialization.

The ordinary `renderer-contract.json` remains v1 and unchanged. The build wrapper validates both direct package pins and the resolved `packages-lock.json`.

## Required inputs

- the P3 runtime-review workspace;
- the exact final P3 `output/` directory;
- the create-only receipt from `prepare-photoreal-v2-p3-quest2-device-handoff.ps1`;
- a connected Quest 2 visible through the adb pinned by `reference-renderer/renderer-contract.json`.

## Command

```powershell
.\run-photoreal-v2-p3-quest2-reference-probe.ps1 `
  -RuntimeReviewWorkspace <P3_RUNTIME_REVIEW_WORKSPACE> `
  -StudentOutputRoot <FINAL_P3_OUTPUT_ROOT> `
  -DeviceHandoffReceipt <P3_QUEST2_DEVICE_HANDOFF_JSON>
```

Pass `-Serial` when more than one adb device is attached.

## What the build proves

The reference build configures only the OpenXR loader for Android and refuses any competing XR loader. It enables XR Manager initialization on start and pins OpenXR to single-pass-instanced rendering.

The build runs from an ephemeral copy of the exact clean BodyRig checkout. The wrapper validates:

1. exact Unity editor revision;
2. exact UniVRM Git revision;
3. exact XR Management and OpenXR package pins;
4. exact resolved package lock;
5. exact Git revision before and after the build.

## What the physical probe proves

The operator revalidates the runtime-review plan, handoff receipt and complete local artifact universe. It then:

1. builds and installs the canonical Quest reference APK;
2. requires a physical device that explicitly identifies as Quest 2;
3. copies the exact P3 artifact tree into the app's private external files area;
4. writes a P3-specific runtime manifest carrying the exact target refresh and frame-time budget;
5. launches an explicit one-shot P3 request;
6. requires XR Management to resolve an active `OpenXRLoader`;
7. requires exactly one running XR display subsystem and an active XR device;
8. verifies every artifact's size and SHA-256 inside the Android player;
9. loads the exact VRM through UniVRM 1.0;
10. validates the Unity Humanoid and required bones;
11. re-hashes the avatar after loading;
12. requires a stereo MainCamera targeting both eyes;
13. requires non-zero XR eye textures;
14. requires single-pass-instanced or its Android multiview runtime equivalent;
15. obtains refresh rate from `XRDisplaySubsystem.TryGetDisplayRefreshRate`;
16. measures 240 physical frame samples and calculates p95;
17. fails if refresh or p95 do not satisfy the P3 target profile.

A successful machine probe therefore records true for:

```text
installed_student_hashes_verified_on_device
vrm10_loaded
humanoid_valid
required_bones_valid
openxr_loader_active
xr_device_active
xr_display_running
stereo_camera_active
runtime_loaded
stereo_rendering_observed
vr_safe_frame_pacing_observed
```

It also records the eye texture dimensions, runtime stereo-rendering mode, physical XR refresh rate and p95 frame time.

## Authority boundary

Machine evidence is not human photoreal acceptance. Even after every OpenXR/runtime check passes, the probe keeps:

```text
human_runtime_visual_acceptance_required = true
runtime_acceptance_authority = false
photoreal_acceptance_authority = false
production_activation = false
```

The existing P3 physical-review gate is still the authority that combines this machine evidence with explicit human PASS/FAIL across all eight canonical fidelity dimensions. Only that combined review can grant runtime/photoreal acceptance. Production activation remains a later, separate boundary.
