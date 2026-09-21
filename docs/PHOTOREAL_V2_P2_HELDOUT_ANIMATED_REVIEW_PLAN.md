# Photoreal V2 P2 HELD-OUT animated review plan

After frozen-teacher ExAvatar evaluation has been executed on one or more HELD-OUT motion sources, this boundary binds the exact review videos to the visual criteria a human must inspect.

The six required review dimensions are:

- head turn;
- eye motion;
- mouth motion;
- hand motion;
- full-body pose;
- identity/appearance preservation through motion.

The selection is explicitly operator supplied. A source may be reused for several dimensions, but every dimension must be mapped exactly once.

For every selected source BodyRig strict-readback validates the HELD-OUT evaluation execution receipt and re-hashes the exact `output/review/heldout-animation.mp4` bytes. All selected evidence must belong to the same performer, appearance epoch, teacher input, P2 plan, TRAIN execution input, TRAIN animation execution receipt and frozen teacher checkpoint.

The plan deliberately does **not** record PASS or FAIL. It keeps human review incomplete, animated-teacher acceptance false, Quest distillation false and production false.

## Selection input

```json
{
  "format": "bodyrig-photoreal-p2-heldout-animated-review-selection",
  "version": 1,
  "reviewer": "operator",
  "operator_supplied": true,
  "selections": [
    {"dimension": "head_turn_validation", "held_out_source_ref": "src-..."},
    {"dimension": "eye_motion_validation", "held_out_source_ref": "src-..."},
    {"dimension": "mouth_motion_validation", "held_out_source_ref": "src-..."},
    {"dimension": "hand_motion_validation", "held_out_source_ref": "src-..."},
    {"dimension": "full_body_pose_validation", "held_out_source_ref": "src-..."},
    {"dimension": "identity_appearance_motion_preservation", "held_out_source_ref": "src-..."}
  ]
}
```

## Operator

```powershell
.\prepare-photoreal-v2-p2-heldout-animated-review-plan.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -SelectionInput <SELECTION_JSON>
```

The next gate must present these exact videos for human review and record explicit PASS/FAIL outcomes. No automatic visual score may grant P2 acceptance.
