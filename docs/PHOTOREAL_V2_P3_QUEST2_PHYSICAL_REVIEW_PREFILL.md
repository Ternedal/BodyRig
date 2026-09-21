# P3 Quest 2 physical-review machine prefill

After the canonical Quest 2 OpenXR machine probe succeeds, BodyRig can now prefill the machine-observable part of the existing physical-review evidence document.

This is a convenience and lineage-hardening step. It is **not** a replacement for the human photoreal review.

## Command

```powershell
.\prepare-photoreal-v2-p3-quest2-physical-evidence-from-machine.ps1 `
  -RuntimeReviewWorkspace <P3_RUNTIME_REVIEW_WORKSPACE> `
  -MachineProbe <P3_QUEST2_MACHINE_PROBE_JSON>
```

The default output is:

```text
<P3_RUNTIME_REVIEW_WORKSPACE>\p3-physical-runtime-evidence.machine-prefill.json
```

## Machine fields that are copied

The prefill only accepts a machine probe that is bound to the exact runtime-review plan and proves:

- exact installed student hashes;
- real UniVRM/Humanoid load;
- active OpenXR loader;
- active Quest XR device and running display subsystem;
- stereo camera and valid eye textures;
- supported single-pass/multiview stereo mode;
- refresh rate at or above the exact plan target;
- p95 frame time at or below the exact plan budget.

It then safely prefills:

```text
physical_device_observed = true
installed_student_artifacts = <exact device-verified hashes>
observed_refresh_hz = <machine measurement>
p95_frame_time_ms = <machine measurement>
stereo_rendering_observed = true
vr_safe_frame_pacing_observed = true
installed_student_hashes_verified_on_device = true
```

## Human boundary remains locked

Every visual fidelity criterion is emitted as:

```text
decision = REVIEW_REQUIRED
```

and the two human authority switches remain:

```text
operator_supplied = false
confirm_physical_device_review_complete = false
```

The existing final recorder therefore rejects the generated file until a human reviewer has actually used the Quest 2, replaced every visual decision with `pass` or `fail`, supplied reviewer identity/notes, and explicitly changed both human confirmation booleans to `true`.

The prefill script never writes runtime acceptance, photoreal acceptance, or production authority.
