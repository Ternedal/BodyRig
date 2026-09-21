# Photoreal V2 — concrete ExAvatar → Quest 2 PBR student

This is BodyRig's first concrete P3 student builder rather than another abstract authority gate.

It is intentionally a conservative standalone Quest 2 baseline:

- base representation: `skinned-mesh-pbr`;
- exact 55-joint SMPL-X humanoid skinning;
- geometry sampled directly from the accepted ExAvatar HumanGaussian at canonical zero pose;
- appearance sampled directly from the accepted ExAvatar refined RGB field;
- glTF/VRM `COLOR_0` vertex colors, avoiding a fake per-vertex texture-atlas interpolation shortcut;
- a distinct `specialized-eye-component` primitive derived from left/right eye skinning;
- a distinct `teacher-derived-hair-component` primitive derived from head-dominant non-face teacher vertices;
- no native Gaussian dependency on Quest 2.

The accepted ExAvatar checkpoint remains the visual teacher. This adapter cannot grant photoreal or runtime acceptance.

## Exact input boundary

The generic P3 runner stages exactly five accepted teacher files before launching this adapter:

- ExAvatar checkpoint;
- shape parameters;
- face offsets;
- joint offsets;
- locator offsets.

The adapter verifies those staged bytes again. It never receives the original accepted-teacher directories.

The same single adapter file is the Windows WSL bridge and the Linux CUDA export implementation. The P3 config pins the exact SHA-256 of that file, so there is no unpinned hidden secondary adapter.

The Linux half also verifies the pinned ExAvatar checkout commit:

`d45268730c779fae4118f1a361cf9ff639bc4d1e`

and requires the already prepared ExAvatar runtime preflight.

## Student materialization

The adapter loads only ExAvatar's `HumanGaussian` state from the accepted checkpoint and applies the staged identity files.

It then derives:

- refined zero-pose teacher vertices;
- refined zero-pose teacher RGB;
- ExAvatar's upsampled SMPL-X face topology;
- effective 55-joint skinning weights;
- zero-pose rest joints and parent hierarchy.

The output VRM contains three real mesh primitives sharing the exact student geometry/skin:

1. base skinned mesh;
2. specialized eyes;
3. teacher-derived hair/scalp.

Appearance uses glTF vertex colors. That is deliberate: the pinned ExAvatar export is topology-aligned per-vertex RGB. Inventing unrelated UV coordinates would corrupt interpolation.

## Fidelity deltas

The adapter does **not** emit arbitrary quality scores.

Static dimensions measure numerical retention between accepted ExAvatar teacher samples and the serialized student payload.

Motion dimensions use a deterministic five-pose SMPL-X sweep and report the teacher's pose-dependent refined geometry that a static skinned-mesh student cannot preserve:

- motion identity preservation: normalized RMS of omitted pose-dependent refinement;
- temporal stability: normalized frame-to-frame refinement residual.

These are reproducible engineering deltas, not photoreal acceptance. They intentionally expose losses instead of hiding them.

The later physical Quest review remains authoritative for visible quality.

## Operator

After the P3 plan exists on `main`:

```powershell
.\prepare-photoreal-v2-p3-exavatar-quest2-pbr-config.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT>

.\run-photoreal-v2-p3-device-distillation.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -Config <TEACHER_WORK_ROOT>\p3-device-distillation\p3-exavatar-quest2-pbr-config.json
```

A successful run must produce at least:

- `student/avatar.vrm`;
- `student/exavatar-quest2-pbr-provenance.json`;
- core-owned P3 execution receipt.

It still leaves runtime acceptance, photoreal acceptance and production false until the real Quest 2 review.
