# Photoreal V2 P3 Quest 2 modular software continuation

This operator chains the completed modular Quest 2 software stages after an existing real P3 student candidate.

It deliberately stops before physical PASS/FAIL.

## Inputs

Required:

- accepted ExAvatar teacher work root;
- existing Quest 2 candidate workspace from the candidate runner;
- exact P3 device distillation plan used by that candidate.

## Command

```powershell
.\run-photoreal-v2-p3-quest2-modular-continuation.ps1 \
  -TeacherWorkRoot <TEACHER_WORK_ROOT> \
  -CandidateWorkspace <P3_QUEST2_CANDIDATE_WORKSPACE> \
  -DistillationPlan <P3_DEVICE_DISTILLATION_PLAN_JSON>
```

Optional:

- `-WorkRoot <NEW_CREATE_ONLY_ROOT>`;
- `-WindowsPython <EXACT_PYTHON_EXE>`.

The default work root is a sibling named:

```text
p3-quest2-modular-continuation
```

The root must not already exist.

## Stages

The operator runs, in order:

1. specialized eye student;
2. accepted-teacher-derived hair envelope and hair student;
3. exact teacher-to-student fidelity delta;
4. final canonical P3 distillation manifest and execution receipt;
5. physical Quest runtime-review plan;
6. deliberately non-authoritative physical evidence template.

Each existing PowerShell stage operator is launched in an isolated child PowerShell process. This is important because the standalone operators use `exit`; invoking them directly in the parent runspace could otherwise terminate the continuation after the first successful stage.

## Workspace layout

```text
p3-quest2-modular-continuation/
  eyes/
  hair-envelope/
    p3-quest2-teacher-hair-envelope.json
  hair/
  fidelity/
    p3-quest2-fidelity-delta-evidence.json
  final-distillation/
  runtime-review/
    p3-device-runtime-review-plan.json
    p3-physical-runtime-evidence.template.json
  p3-quest2-modular-continuation.json
```

The hair envelope intentionally has its own directory. It is not placed inside the create-only hair output root and does not mutate the original candidate workspace.

## Refined ExAvatar authority

The candidate and all downstream teacher-derived stages use the refined ExAvatar asset returned by `HumanGaussian`, not the base pre-refinement output.

The refined geometry and RGB are the authority for:

- canonical basecolor transfer;
- teacher-derived hair displacement;
- teacher/student fidelity measurement.

The candidate test suite contains an explicit regression guard for that output selection.

## Fidelity behavior

Eye and hair appearance are measured on their actual materialized runtime primitives:

- specialized eye surface positions + eye UVs;
- teacher-derived hair shell positions + hair UVs.

They are compared against nearest refined-teacher RGB.

This avoids accidentally scoring only the underlying body/scalp vertices.

## Output summary

On success the operator writes:

```text
p3-quest2-modular-continuation.json
```

The summary binds SHA-256 values for the candidate receipt, eye receipt, hair envelope, hair receipt, fidelity evidence, final receipts, runtime-review plan and physical-evidence template.

It records:

```text
software_continuation_complete = true
physical_device_evidence_present = false
physical_runtime_review_complete = false
runtime_acceptance_authority = false
photoreal_acceptance_authority = false
production_activation = false
```

## Deliberate stop boundary

The operator never calls:

```text
record-photoreal-v2-p3-quest2-physical-runtime-review.ps1
```

The next step requires a real Quest 2 review.

The generated evidence template remains invalid until the exact final artifacts are installed on the physical headset, their hashes are verified on-device, performance measurements are recorded and a human reviewer explicitly records PASS/FAIL for all eight fidelity dimensions.
