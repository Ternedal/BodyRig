# Photoreal V2 P2 pinned ExAvatar animation runner

This is the first P2 stage that actually starts the pinned ExAvatar animation implementation.

It consumes only the digest-bound execution input produced by the preceding gate. That input contains the accepted static-teacher checkpoint, the four accepted ExAvatar identity files, and one core-verified TRAIN motion-driver path. HELD-OUT EVALUATION motion is not disclosed to the animation process.

## Execution isolation

The Linux adapter validates the original accepted ExAvatar workspace, preprocess state and runtime preflight, then creates a temporary execution staging tree. It copies only:

- the pinned ExAvatar avatar code and linked model assets required for execution;
- `checkpoint/snapshot_4.pth` from the accepted teacher;
- `shape_param.json`, `face_offset.json`, `joint_offset.json`, and `locator_offset.json` from the accepted identity export;
- the exact selected TRAIN motion-driver `frames/`, `cam_params/`, and smoothed SMPL-X parameter files.

The original accepted ExAvatar workspace is used as read-only provenance/code authority. The adapter does not copy the original training video or held-out validation motion into the animation staging tree.

Immediately before launch, core re-hashes the checkpoint, every identity artifact and every selected motion artifact. The Linux adapter independently verifies those same source bytes while staging them.

## Pinned invocation

The adapter runs the pinned upstream `avatar/main/animate.py` at ExAvatar commit `d45268730c779fae4118f1a361cf9ff639bc4d1e` with:

```text
--subject_id <accepted subject>
--test_epoch 4
--motion_path <isolated staged TRAIN motion>
```

The resulting upstream `motion.mp4` is copied to the core-owned output as `review/animation.mp4`. Core then re-hashes the output and writes a digest-bound `animation-execution-receipt.json`.

## Operator

```powershell
.\run-photoreal-v2-p2-exavatar-animation.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT>
```

Default output:

```text
<TEACHER_WORK_ROOT>\p2-animated-teacher\animation-execution\
  adapter.log
  request.json
  animation-execution-receipt.json
  output\
    animation-manifest.json
    review\animation.mp4
```

## Authority boundary

A successful execution receipt proves that the pinned ExAvatar animation completed from the exact accepted teacher identity and exact bounded TRAIN motion bytes. The receipt also fixes the execution semantics as inference-only: `inference_only=true`, `teacher_training_performed=false`, and `checkpoint_mutation_performed=false`. It does **not** assert that the animation looks good.

`human_animated_visual_acceptance_required=true` remains mandatory. Animated-teacher acceptance, Quest distillation, broader photoreal acceptance and production activation remain false until later explicit human review.
