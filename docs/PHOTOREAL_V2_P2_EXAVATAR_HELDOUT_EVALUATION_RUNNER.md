# Photoreal V2 P2 HELD-OUT ExAvatar evaluation runner

This is the evaluation-only counterpart to the canonical TRAIN animation run.

The accepted static teacher is frozen. BodyRig may disclose one already prepared `evaluation / held-out-motion-validation` motion path to ExAvatar only after the TRAIN animation execution has completed successfully in inference-only mode.

The runner immediately re-verifies the accepted checkpoint, four identity artifacts and every selected HELD-OUT frame/camera/smoothed-SMPL-X artifact. It then runs the same pinned ExAvatar animation path with the HELD-OUT motion path.

The disclosure purpose is fixed to:

`post-training-inference-only-evaluation`

It cannot authorize teacher training or checkpoint mutation.

## Operator

First build the source-specific evaluation input:

```powershell
.\prepare-photoreal-v2-p2-exavatar-heldout-evaluation-input.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -HeldOutSourceRef <EVALUATION_SOURCE_REF>
```

Then execute the frozen-teacher evaluation:

```powershell
.\run-photoreal-v2-p2-exavatar-heldout-evaluation.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -HeldOutSourceRef <EVALUATION_SOURCE_REF>
```

Each HELD-OUT source gets its own input and execution directories, so several independent evaluation motions can be run without overwriting evidence.

A successful run creates exactly one core-verified review artifact:

`review/heldout-animation.mp4`

and one digest-bound `heldout-evaluation-execution-receipt.json`.

Success proves only reproducible frozen-teacher inference over that exact held-out motion. Human animated-teacher acceptance, Quest distillation, broader photoreal acceptance and production remain false.
