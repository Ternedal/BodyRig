# Photoreal V2 P2 ExAvatar animation execution input

This is the last non-executing software gate before the pinned ExAvatar animation adapter may start.

The gate combines two independently accepted input authorities:

1. the accepted static teacher's ExAvatar identity export (`shape_param.json`, `face_offset.json`, `joint_offset.json`, `locator_offset.json`); and
2. one explicitly selected, core-verified **TRAIN** motion-driver path produced by P2 motion preparation.

HELD-OUT EVALUATION motion is never copied into this execution input and is not disclosed to ExAvatar animation.

## Byte verification

At plan creation time BodyRig:

- strict-validates the P2 animation plan;
- strict-validates the ExAvatar animation identity receipt against the exact exported identity root;
- strict-validates the core-owned motion-preparation receipt;
- requires the selected source to be `split=train` and `role=motion-driver`;
- re-hashes every selected motion artifact from the motion-preparation output;
- requires identical frame IDs across `frames/`, `cam_params/`, and `smplx_optimized/smplx_params_smoothed/`;
- preserves the accepted teacher checkpoint binding;
- persists only the chosen TRAIN motion driver, never the held-out validation task.

A valid execution-input plan may set `p2_animation_execution_authorized=true`, but it also records `animation_started=false`. No external ExAvatar process runs in this stage.

## Operator

After identity export and motion preparation have completed:

```powershell
.\prepare-photoreal-v2-p2-exavatar-animation-execution-input.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -MotionDriverSourceRef <TRAIN_SOURCE_REF>
```

Output:

```text
<TEACHER_WORK_ROOT>\p2-animated-teacher\animation-input\exavatar-execution\
  p2-exavatar-animation-execution-input.json
```

The next boundary is the actual pinned ExAvatar animation runner. That runner must reverify these exact bytes immediately before launch, stage only the accepted checkpoint/identity/TRAIN-motion universe, execute the pinned upstream animation script, and produce a core-owned execution receipt. Human animated-teacher acceptance, Quest distillation, broader photoreal acceptance and production remain separate later gates.
