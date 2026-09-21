# Photoreal V2 P2 motion source selection

This boundary records the explicit human choice of motion-driver and held-out validation video sources after the path-private P2 motion evidence handoff.

It deliberately does **not** rehash source media, materialize/deproject video, run SMPL-X fitting, start ExAvatar animation, accept an animated teacher, authorize Quest distillation, grant broader photoreal acceptance, or activate production.

## Operator

Run from an exact clean current `main` checkout after `prepare-photoreal-v2-p2-motion-evidence.ps1` has produced the public handoff and build-private path map:

```powershell
.\record-photoreal-v2-p2-motion-selection.ps1 -TeacherWorkRoot <TEACHER_WORK_ROOT>
```

Without approval parameters, the operator prints the opaque TRAIN driver candidates and HELD-OUT EVALUATION validation candidates, then exits with code 2.

After human review, rerun with at least one source ref from each split:

```powershell
.\record-photoreal-v2-p2-motion-selection.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -MotionDriverSourceRef <TRAIN_SOURCE_REF> `
  -HeldOutValidationSourceRef <EVALUATION_SOURCE_REF> `
  -ReviewedBy <OPERATOR> `
  -ReviewNotes "<NOTES>" `
  -ApproveHumanSelection
```

The resulting `p2-motion-source-selection.json` is hash-bound to the public handoff and its private path index. It contains opaque refs, group refs, source hashes and preparation modes only; local source keys and resolved paths remain private.

A valid receipt sets only:

- `human_motion_source_selection_complete=true`
- `motion_source_selection_authority=true`
- `p2_motion_input_authorized=true`

Animation execution, animated-teacher acceptance, Quest distillation, photoreal acceptance and production activation remain false.
