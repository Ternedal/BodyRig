# Photoreal V2 P2 human animated-teacher review

This is the human authority gate after the frozen accepted teacher has been evaluated on HELD-OUT motion.

The software cannot infer PASS. It first creates a private review pack containing exact copies of the selected HELD-OUT evaluation videos and a hash-bound HTML index. The ExAvatar video layout shows:

1. the real HELD-OUT reference frame;
2. the rendered SMPL-X mesh;
3. the frozen teacher render.

The reviewer must explicitly decide PASS or FAIL for every motion dimension:

- head turn;
- eye motion;
- mouth motion;
- hands;
- full-body pose;
- identity/appearance preservation through motion.

The reviewer must also decide PASS or FAIL for every quality check:

- temporal stability;
- identity stability across motion;
- appearance stability across motion;
- geometry stability / no collapse;
- no visible texture swimming or flicker;
- visually coherent motion control.

Any single FAIL produces a valid persisted P2 FAIL and keeps P3/Quest distillation closed.

Only an all-PASS receipt may set animated-teacher acceptance and P3/Quest distillation authority true. Broader runtime photoreal acceptance and production activation remain false even after P2 PASS.

## Prepare the review pack

```powershell
.\prepare-photoreal-v2-p2-heldout-animated-human-review.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT>
```

The operator opens the generated `review-index.html`. No decision is recorded by this command.

## Record PASS or FAIL

After visually reviewing every item, call the record operator with every required dimension and quality check as `name=pass|fail`, plus a non-empty review note and explicit completion confirmation.

```powershell
.\record-photoreal-v2-p2-heldout-animated-human-review.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -Decision @(
    "head_turn_validation=pass",
    "eye_motion_validation=pass",
    "mouth_motion_validation=pass",
    "hand_motion_validation=pass",
    "full_body_pose_validation=pass",
    "identity_appearance_motion_preservation=pass"
  ) `
  -QualityCheck @(
    "temporal_stability=pass",
    "identity_stability_across_motion=pass",
    "appearance_stability_across_motion=pass",
    "geometry_stability_no_collapse=pass",
    "no_visible_texture_swimming_or_flicker=pass",
    "visually_coherent_motion_control=pass"
  ) `
  -ReviewedBy "<OPERATOR>" `
  -ReviewNotes "<NOTES>" `
  -ConfirmReviewComplete
```

The receipt is create-only. P2 FAIL is evidence, not a software error; it simply prevents P3 authority.
