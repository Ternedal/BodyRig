# Photoreal V2 P3 Quest 2 reference machine probe

This gate takes the exact final P3 student that already passed the software pipeline and byte-for-byte Quest 2 handoff, loads it through BodyRig's physical Unity/UniVRM reference player on a real Quest 2 and records machine evidence.

It remains deliberately **non-accepting**.

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

## What happens

The operator revalidates the runtime-review plan, handoff receipt and complete local artifact universe. It then:

1. builds the exact clean BodyRig reference renderer with the pinned Unity/UniVRM contract;
2. requires the pinned Unity Android SDK adb;
3. requires a device that explicitly identifies as Quest 2;
4. installs the reference APK;
5. copies the exact P3 artifact tree into the app's private external files area;
6. writes a P3-specific runtime manifest and explicit one-shot request marker;
7. launches the reference renderer;
8. waits for the on-device P3 machine probe;
9. pulls and revalidates the probe;
10. removes only the request marker after success so later ordinary renderer launches are not hijacked.

The Unity probe itself verifies every artifact's size and SHA-256 on-device, rejects artifact-universe drift, loads the exact VRM with UniVRM 1.0, validates the Unity Humanoid and required bones, re-hashes the avatar after loading and samples physical frame timing.

A successful machine probe may therefore state:

```text
installed_student_hashes_verified_on_device = true
vrm10_loaded = true
humanoid_valid = true
required_bones_valid = true
runtime_loaded = true
observed_refresh_hz > 0
p95_frame_time_ms > 0
```

## Current XR blocker

The canonical reference renderer does not currently pin `com.unity.xr.openxr` or another XR provider. Running an Android player on Quest hardware is not enough to prove stereo rendering.

This v1 gate therefore fails closed and always records:

```text
stereo_rendering_observed = false
vr_safe_frame_pacing_observed = false
stereo_authority = blocked-until-canonical-xr-runtime-is-pinned
runtime_acceptance_authority = false
photoreal_acceptance_authority = false
production_activation = false
```

The PowerShell runner also rejects the situation where OpenXR suddenly appears in the package manifest without a corresponding update of this evidence contract. That prevents an unreviewed package change from silently turning the blocker into authority.

## Next gate

The next implementation step is to pin and configure a canonical Quest OpenXR runtime in the reference project, then extend the machine probe to prove stereo activity and VR-safe frame pacing from that exact XR build.

Only after that machine evidence exists can the existing P3 physical review gate combine it with explicit human PASS/FAIL across all eight fidelity dimensions. Production activation remains a separate later boundary.
