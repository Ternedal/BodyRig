# Photoreal V2 P3 Quest 2 fidelity delta

This stage is stacked on the completed modular Quest 2 eye + teacher-derived hair student.

Its job is deliberately narrow: measure how much fidelity is lost when the accepted ExAvatar teacher is represented by the standalone Quest 2 student. It does **not** issue a photoreal PASS, runtime PASS or production authority.

## Evidence policy

BodyRig reports all eight canonical P3 dimensions:

1. identity likeness;
2. face detail;
3. eyes;
4. hair silhouette and appearance;
5. skin material response;
6. hands and extremities;
7. motion identity preservation;
8. temporal stability.

The stage does not invent a learned quality score and does not combine measurements with arbitrary weights.

Single-axis dimensions report their physical delta directly.

Face, eyes and hair each have two independently measured axes:

- geometry delta, normalized by body height;
- teacher/student RGB RMSE in normalized 0..1 colour space.

Their canonical P3 value is the **worst measured axis**. This is intentionally conservative and fully reproducible.

## Exact teacher authority

Before measurement, the Linux generator revalidates:

- the exact P3 candidate request digest;
- the exact core candidate receipt;
- the exact final hair-student receipt and current student artifact bytes;
- the complete five-file staged teacher universe;
- the accepted ExAvatar workspace receipt;
- the pinned ExAvatar commit and protected source files;
- the linked human-model asset hashes.

The accepted ExAvatar checkpoint is loaded through the same staged identity/checkpoint boundary used by the modular Quest 2 student.

No teacher retraining occurs and the P0/P2 source corpus is not rehashed.

## Static geometry measurements

The generator loads the final student VRM and strict-reads its canonical body primitive plus the separate specialized-eye and teacher-derived-hair primitives.

Teacher and student surfaces are compared with symmetric nearest-surface Chamfer RMS:

```text
sqrt((mean(d(teacher -> student)^2) + mean(d(student -> teacher)^2)) / 2)
```

Geometry measurements are normalized by the accepted zero-pose donor body height.

Semantic regions are derived from the exact student SMPL-X skinning weights rather than image heuristics:

- eyes: left/right eye joints;
- face: neck/head/jaw domain, excluding eye and materialized hair domains;
- hands/extremities: wrists, finger chains, ankles and feet;
- hair: the exact base-head domain recovered from the materialized teacher-derived hair primitive.

Accepted ExAvatar teacher points are assigned to the closest canonical body vertex before regional geometry comparison.

## Appearance measurements

The final `student/basecolor.png` bytes are hash-bound by the hair receipt.

For each canonical body vertex, BodyRig:

1. finds the nearest accepted refined ExAvatar teacher point;
2. reads its teacher RGB;
3. samples the exact student basecolor at the canonical UV coordinate;
4. computes normalized RGB RMSE for the selected region.

This produces independent appearance deltas for face, eyes, hair and the broad non-eye/non-hair skin/material domain.

The `skin_material_response` metric is intentionally named `skin-basecolor-rgb-rmse`: this stage does **not** pretend that a frozen RGB teacher contains measured roughness, subsurface scattering or other unavailable physical material ground truth.

## Motion and temporal measurements

The accepted teacher is evaluated on the fixed five-pose canonical P3 sweep.

For every pose BodyRig measures the ExAvatar refinement residual:

```text
refined teacher geometry - base SMPL-X-driven geometry
```

The Quest 2 student currently uses static rest geometry plus SMPL-X skinning. Therefore the omitted pose-dependent teacher refinement is the measurable student loss.

Two canonical deltas are recorded:

- motion identity preservation: pose-dependent refinement residual relative to the zero-pose residual;
- temporal stability: frame-to-frame refinement-residual delta across the canonical sweep.

Both are reported as RMSE normalized by body height.

## Hash-bound references

Every canonical measurement contains explicit teacher and student references including SHA-256 authority.

Examples:

```text
sha256:<accepted-checkpoint>#accepted-exavatar-refined-zero-pose
sha256:<student-vrm>#quest2-vrm-body-eye-hair-surfaces
sha256:<student-vrm>#quest2-vrm;sha256:<basecolor>#teacher-derived-basecolor
```

The evidence itself is also digest-bound.

## Output authority

A successful measurement produces:

```text
p3-quest2-fidelity-delta-evidence.json
```

Success means:

- all eight canonical dimensions are present;
- exact teacher/student references are hash-bound;
- the final student artifacts have not drifted;
- the fidelity-delta blocker is complete.

It still records:

- `p3_distillation_complete = false`;
- human runtime visual acceptance required;
- runtime acceptance false;
- photoreal acceptance false;
- production activation false.

After this stage, the only remaining P3 implementation blocker is:

```text
p3-distillation-manifest
```

Physical Quest review remains a separate human authority gate after the final manifest/runtime package exists.

## Windows operator

Preferred execution:

```powershell
.\run-photoreal-v2-p3-quest2-fidelity-delta.ps1 \
  -TeacherWorkRoot <TEACHER_WORK_ROOT> \
  -CandidateWorkspace <P3_CANDIDATE_WORKSPACE> \
  -HairOutputRoot <P3_HAIR_OUTPUT_ROOT>
```

The wrapper:

1. requires an exact clean BodyRig checkout;
2. reads the existing pinned ExAvatar teacher config;
3. reuses its WSL distribution, Linux Python and accepted ExAvatar workspace;
4. runs the CUDA measurement generator in WSL;
5. strict-reads the generated evidence again through BodyRig core on Windows;
6. prints the eight measured deltas.

It does not rerun training and does not rehash the original P0/P2 media corpus.

## Next boundary

The next stage must materialize the final P3 distillation manifest from:

- the exact P3 request/plan lineage;
- the exact final Quest 2 student artifacts;
- the completed eye and hair component provenance;
- this exact fidelity-delta evidence.

That manifest may mark **distillation complete**, but it must still leave physical runtime review, photoreal acceptance and production activation false.
