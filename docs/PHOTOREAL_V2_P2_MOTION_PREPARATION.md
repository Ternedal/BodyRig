# Photoreal V2 P2 motion preparation

This is the first P2 boundary that is allowed to perform physical work on the selected motion sources.

It consumes:

- the exact P2 motion-evidence handoff;
- the bound build-private source index;
- the explicit human motion-source selection receipt;
- the private P2 motion-input plan;
- the explicit P2 eye/viewport normalization-selection receipt;
- the original P0 `scan-plan.json`;
- an explicit pinned motion-preparation adapter config.

## Why the P0 scan plan is required again

The P2 teacher-input path intentionally did not carry private projection geometry forward. A spatial source cannot therefore be deprojected safely from `projection=equi` alone.

The runner rebinds every selected P2 source to the original P0 scan source by:

- source key;
- source SHA-256 already established by P0;
- source group and split;
- projection and stereo layout;
- the exact original projection-authority payload.

No spatial geometry is reconstructed or guessed.

## Eye and viewport authority

Before physical preparation, BodyRig records a separate digest-bound normalization selection.

- flat mono sources are deterministic: `mono`, no viewport;
- flat side-by-side/over-under sources require an explicit left/right eye;
- authoritative `equi` sources require an allowed eye plus one viewport ID from the exact P0 projection-authority viewport universe;
- unsupported spatial projections remain fail-closed.

Use:

```powershell
.\record-photoreal-v2-p2-motion-normalization-selection.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -P0Root <P0_RUN_ROOT> `
  -ReviewedBy <OPERATOR> `
  -ReviewNotes "<NOTES>"
```

The first invocation prints the legal choice universe. If human selection is required it exits with code 2 without touching media. Rerun with choices such as `-Choice "src-...=left@v00" -ApproveHumanSelection`.

The physical preparation runner requires this exact receipt and binds it back to the original P0 scan authority.

## Source hashing boundary

The runner verifies selected source presence and byte size before execution, but does **not** SHA-256 the source videos again. The existing P0 source hash remains provenance authority.

Generated motion artifacts are different: BodyRig core hashes every generated file before creating the execution receipt.

## Motion-path contract

Every successfully prepared source must expose aligned integer frame IDs across:

```text
frames/<frame>.png
cam_params/<frame>.json
smplx_optimized/smplx_params_smoothed/<frame>.json
```

Every camera JSON must contain at least:

`R, t, focal, princpt`

Every SMPL-X JSON must contain at least:

`root_pose, body_pose, jaw_pose, leye_pose, reye_pose, lhand_pose, rhand_pose, expr, trans`

The fitting backend is pinned to `pinned-exavatar-fitting-v1` with `camera_mode=virtual`.

## Authority

The external adapter can never grant animation acceptance or downstream authority.

Only after BodyRig core has verified the complete generated artifact universe and exact motion-path structure does the BodyRig-owned receipt set:

`p2_animation_execution_authorized=true`

It still keeps animated-teacher acceptance, Quest distillation, broader photoreal acceptance and production activation false.

## Windows operator

```powershell
.\run-photoreal-v2-p2-motion-preparation.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -P0Root <P0_RUN_ROOT> `
  -Config <PINNED_MOTION_PREPARATION_CONFIG>
```

This command may perform substantial GPU/video work. It should only be run after the preceding P2 authority stack has landed and the pinned adapter config has been reviewed.
