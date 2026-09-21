# Photoreal V2 P2 motion preparation authority

This boundary is the last non-executing gate before BodyRig is allowed to prepare motion inputs.

The P2 motion-input plan intentionally carries private source paths but not enough geometry to deproject spatial media safely. Exact spatial geometry already exists in the P0 `scan-plan.json`. This gate reconnects the selected P2 sources to that exact P0 authority instead of inferring projection from filenames, dimensions, tags, or a loose `vr180` label.

## What is bound

For every selected TRAIN motion driver and HELD-OUT EVALUATION validation source, BodyRig requires exact agreement on:

- source key;
- source SHA-256 already established by P0;
- resolved private source path;
- source group;
- train/evaluation split.

Flat mono sources must still be exact `flat + mono + rectilinear-mono` in the P0 scan plan.

Spatial sources are authorized by v1 only when the P0 scan plan resolves them to exact `equi` geometry with an existing Spherical-V2 or explicit projection-authority object. That authority must still state `deprojection_authority=false`; this P2 gate grants the later preparation runner permission to perform the deprojection.

Mesh and cubemap projection paths remain fail-closed here. They are not silently approximated as equirectangular.

## Operator

After `prepare-photoreal-v2-p2-motion-input-plan.ps1`:

```powershell
.\authorize-photoreal-v2-p2-motion-preparation.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -P0Root <EXACT_P0_RUN_ROOT>
```

The operator writes:

```text
<TEACHER_WORK_ROOT>\p2-animated-teacher\motion-input\p2-motion-preparation-authority.json
```

The authority is bound to the exact P0 scan-plan file SHA-256 and to the complete P2 evidence -> selection -> input-plan lineage.

It performs no source-media rehash, no video decode, no deprojection, no SMPL-X fitting, and no animation.

A successful gate may set only `motion_input_preparation_execution_authorized=true`. Animation execution, animated-teacher acceptance, Quest distillation, broader photoreal acceptance and production remain false.

The next step is the preparation runner. It can reuse BodyRig's existing ExAvatar virtual-camera preprocessing implementation rather than creating a second SMPL-X fitting pipeline.
