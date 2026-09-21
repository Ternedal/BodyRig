# Photoreal V2 P3 physical Quest PASS/FAIL

This is the first boundary allowed to grant BodyRig's runtime and photoreal acceptance authority for the distilled student.

It cannot run from software evidence alone. The operator must supply evidence from a physically observed target Quest device and explicitly confirm that the physical review is complete.

## Evidence requirements

The evidence must bind to the exact runtime-review plan and target Quest class, and must include:

- exact installed student artifact paths and SHA-256 values;
- observed refresh rate;
- p95 frame time;
- whether stereo rendering was physically observed;
- whether VR-safe frame pacing was physically observed;
- whether the installed student hashes were verified on device;
- explicit PASS/FAIL for all eight visual fidelity dimensions:
  - identity likeness;
  - face detail;
  - eyes;
  - hair silhouette and appearance;
  - skin material response;
  - hands and extremities;
  - motion identity preservation;
  - temporal stability;
- reviewer identity and non-empty notes;
- explicit physical-review completion confirmation.

Performance PASS is derived fail-closed from the target profile:

- observed refresh must be at least the target refresh;
- p95 frame time must be at or below the target frame budget;
- stereo, frame pacing and on-device hash verification must all be true.

Any visual or performance FAIL creates a valid persisted FAIL receipt and keeps runtime/photoreal acceptance false.

## PASS authority

Only an all-PASS physical review may set:

- `runtime_acceptance_authority=true`;
- `photoreal_acceptance_authority=true`.

Even then:

- `production_activation=false`.

Production remains a separate later decision.

## Operator

```powershell
.\record-photoreal-v2-p3-physical-runtime-review.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -Evidence <PHYSICAL_QUEST_EVIDENCE_JSON>
```

This gate is deliberately not automatable from CI. A green GitHub pipeline cannot substitute for the real headset review.
