# Photoreal V2 P3 Quest 2 full software pipeline

This operator is the complete **software-only** Quest 2 P3 continuation from an already-authorized P3 device-distillation plan.

It regenerates the base Quest 2 student with the corrected refined ExAvatar teacher semantics and then runs every modular software stage through the physical-review handoff.

It does not perform or synthesize physical Quest acceptance.

## Command

Run from an exact clean BodyRig checkout:

```powershell
.\run-photoreal-v2-p3-quest2-full-software.ps1 \
  -TeacherWorkRoot <TEACHER_WORK_ROOT> \
  -DistillationPlan <P3_DEVICE_DISTILLATION_PLAN_JSON>
```

Optional parameters:

- `-P2Root <P2_WORK_ROOT>` when the P2 root is not the default `<TeacherWorkRoot>\p2-animated-teacher`;
- `-WorkRoot <NEW_CREATE_ONLY_ROOT>`;
- `-CanonicalUvTemplate <WINDOWS_OR_WSL_SMPLX_UV_OBJ>`;
- `-WindowsPython <EXACT_BODYRIG_PYTHON>`.

The default full work root is a sibling of the P3 plan named:

```text
quest2-full-software
```

It must not already exist.

## Stage 1: corrected refined ExAvatar candidate

The full operator first runs:

```text
run-photoreal-v2-p3-quest2-refined-candidate.ps1
```

That launcher reads the exact accepted `exavatar-teacher-config.json` and reuses its:

- WSL distribution;
- WSL executable;
- pinned ExAvatar Linux Python;
- accepted ExAvatar workspace.

The Windows P3 plan, teacher output, P2 identity export and candidate output paths are translated into WSL paths.

Before GPU work begins, the launcher runs a fail-fast preflight in the exact pinned Linux Python. It requires `numpy`, Pillow, `pytorch3d`, `nvdiffrast`, the BodyRig candidate core module and `torch.cuda.is_available() == true`. The selected CUDA device is printed before the expensive stage starts.

The candidate core runner itself then executes **inside WSL**, so its pinned adapter entrypoint is a real Linux path and is hash-verified by the existing P3 runner.

## Candidate adapter config

The launcher creates a v1 canonical P3 adapter config with:

- adapter `bodyrig-exavatar-quest2-student-candidate-v1`;
- revision equal to SHA-256 of the exact current candidate adapter file;
- `skinned-mesh-pbr`;
- specialized eye + teacher-derived hair required components;
- Quest 2 as the only supported target;
- all eight canonical fidelity-delta dimensions;
- staged-teacher-only consumption;
- no native Gaussian target support.

The external command is the pinned ExAvatar Linux Python invoking the exact adapter path plus:

- accepted ExAvatar workspace;
- canonical SMPL-X UV template.

## Canonical UV authority

By default the launcher resolves WSL home and requires:

```text
~/.local/share/bodyrig/sith/data/smplx_uv.obj
```

This is the same pinned SiTH canonical SMPL-X UV template used elsewhere in BodyRig's high-fidelity pipeline.

An explicit Windows or WSL path may be supplied with `-CanonicalUvTemplate`.

## Refined ExAvatar authority

The base runtime body remains the exact identity-bound zero-pose SMPL-X mesh.

Appearance transfer uses the **refined** ExAvatar HumanGaussian output:

```text
refined_teacher["mean_3d"]
refined_teacher["rgb"]
```

The manifest reports:

```text
appearance_source =
  accepted-exavatar-refined-zero-pose-gaussian-rgb
```

A regression test prevents the candidate loader from silently returning to the base pre-refinement teacher output.

## Stage 2: modular continuation

After the candidate is core-verified, the full operator launches:

```text
run-photoreal-v2-p3-quest2-modular-continuation.ps1
```

That stage performs:

1. specialized eye component;
2. teacher-derived hair envelope and hair student;
3. exact teacher-to-student fidelity delta;
4. canonical final P3 distillation manifest;
5. canonical execution receipt;
6. physical Quest runtime-review plan;
7. deliberately invalid physical evidence template.

Eye and hair appearance deltas are measured on the actual materialized runtime primitives and their UVs, not merely the underlying body/scalp vertices.

## Child process isolation

Both top-level stages are run in isolated child PowerShell processes.

This is deliberate: the standalone BodyRig operators use `exit`, so directly invoking them in one PowerShell runspace could terminate the parent orchestration after an otherwise successful substage.

## Output layout

```text
quest2-full-software/
  quest2-refined-student-candidate-config.json
  candidate/
    request.json
    staged-teacher/
    output/
      quest2-student-candidate.json
      student/
        avatar.vrm
        basecolor.png
    p3-quest2-student-candidate-receipt.json
  continuation/
    eyes/
    hair-envelope/
    hair/
    fidelity/
    final-distillation/
    runtime-review/
      p3-device-runtime-review-plan.json
      p3-physical-runtime-evidence.template.json
    p3-quest2-modular-continuation.json
  p3-quest2-full-software.json
```

## Final software summary

A successful run writes:

```text
p3-quest2-full-software.json
```

It hash-binds:

- P3 device-distillation plan;
- refined candidate manifest;
- refined candidate receipt;
- modular continuation summary;
- final P3 execution receipt;
- runtime-review plan;
- physical-evidence template.

It records:

```text
refined_candidate_complete = true
software_pipeline_complete = true
physical_device_evidence_present = false
physical_runtime_review_complete = false
runtime_acceptance_authority = false
photoreal_acceptance_authority = false
production_activation = false
```

## Deliberate stop boundary

The full software operator never calls the physical PASS/FAIL recorder.

A green software run means the exact final student bytes and the exact physical-review plan are ready.

The next authority boundary remains the real Quest 2 headset:

- install the exact final student artifacts;
- verify hashes on-device;
- record observed refresh and p95 frame time;
- confirm stereo rendering and VR-safe frame pacing;
- perform explicit human PASS/FAIL over all eight visual dimensions.

Only the separate physical-review gate may turn an all-PASS headset review into runtime and photoreal acceptance.

Production activation remains a later independent BodyRig release boundary.
