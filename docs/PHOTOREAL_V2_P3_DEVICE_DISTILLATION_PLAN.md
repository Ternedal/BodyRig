# Photoreal V2 P3 device distillation plan

P3 begins only after an exact human P2 animated-teacher PASS.

The accepted teacher source for distillation is the **frozen ExAvatar model**, not the MP4 used for human review. BodyRig therefore re-verifies exactly five teacher-source artifacts immediately before P3 planning:

- `checkpoint/snapshot_4.pth`;
- `shape_param.json`;
- `face_offset.json`;
- `joint_offset.json`;
- `locator_offset.json`.

The HELD-OUT/TRAIN review videos remain quality evidence. They are not student-training source bytes.

## Device target profile

The target profile is operator supplied and v1 supports standalone Meta Quest 2, Quest 3 and Quest 3S. It must declare an explicit refresh rate and an exact frame budget equal to `1000 / target_refresh_hz`.

Example for Quest 2 at 72 Hz:

```json
{
  "format": "bodyrig-photoreal-device-target-profile",
  "version": 1,
  "operator_supplied": true,
  "target_family": "meta-quest",
  "target_model": "quest-2",
  "target_runtime": "standalone",
  "target_refresh_hz": 72.0,
  "max_frame_time_ms": 13.888889,
  "stereo_rendering_required": true,
  "vr_safe_frame_pacing_required": true,
  "teacher_quality_ceiling_preserved": true,
  "fidelity_delta_reporting_required": true,
  "production_activation": false
}
```

## Planning authority

A valid P3 plan:

- requires the exact P2 human PASS receipt;
- binds that PASS to the exact P2 ExAvatar execution-input SHA and frozen checkpoint SHA;
- re-hashes the five teacher-source artifacts;
- keeps the accepted teacher as visual authority;
- forbids a student fidelity claim above the teacher;
- requires explicit teacher-to-student fidelity deltas;
- carries a representation candidate universe but selects no permanent student architecture;
- grants only P3 distillation execution authority.

Runtime visual acceptance, broader photoreal acceptance and production remain false.

## Operator

```powershell
.\prepare-photoreal-v2-p3-device-distillation.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -TargetProfile <TARGET_PROFILE_JSON>
```

The next boundary is a distillation runner behind this plan. It must select an explicit adapter/student representation, preserve the five exact teacher-source bytes as provenance, measure the required fidelity deltas, and still require physical runtime review before any production authority.
