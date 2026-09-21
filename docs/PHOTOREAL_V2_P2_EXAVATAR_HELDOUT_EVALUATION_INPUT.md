# Photoreal V2 P2 held-out ExAvatar evaluation input

This boundary opens HELD-OUT motion to the frozen ExAvatar teacher only after a successful core-owned TRAIN animation execution has proved that the teacher runs inference-only.

It is intentionally separate from TRAIN animation. The gate requires the TRAIN execution receipt to prove:

- `animation_complete=true`;
- `inference_only=true`;
- `teacher_training_performed=false`;
- `checkpoint_mutation_performed=false`;
- `held_out_evaluation_disclosed=false`.

Only after those conditions hold may the operator select one prepared motion task whose split is exactly `evaluation` and whose role is exactly `held-out-motion-validation`.

## Byte boundary

Before producing the evaluation input, BodyRig re-hashes:

- the frozen accepted `snapshot_4.pth` and requires the SHA to equal the checkpoint consumed by the TRAIN run;
- all four accepted ExAvatar identity files;
- every selected HELD-OUT motion artifact, with aligned frame/camera/smoothed-SMPL-X frame IDs.

The resulting input explicitly sets:

- `held_out_evaluation_disclosed_to_animation=true`;
- `held_out_disclosure_purpose=post-training-inference-only-evaluation`;
- `teacher_training_authorized=false`;
- `checkpoint_mutation_authorized=false`;
- `p2_heldout_animation_evaluation_authorized=true`.

This stage does not start evaluation animation and cannot grant animated-teacher acceptance.

## Operator

```powershell
.\prepare-photoreal-v2-p2-exavatar-heldout-evaluation-input.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -HeldOutSourceRef <EVALUATION_SOURCE_REF>
```

The next boundary is an evaluation-only ExAvatar execution using these exact held-out motion bytes and the already frozen teacher checkpoint. Only after that output exists should the human animated-teacher review be allowed to record PASS or FAIL.
