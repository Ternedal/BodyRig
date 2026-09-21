# Photoreal V2 P3 distillation runner

This boundary executes one explicitly configured student-distillation adapter after the P3 plan has been authorized.

The adapter never receives BodyRig's accepted ExAvatar teacher directories. BodyRig first re-verifies the five accepted teacher-source artifacts and copies them into a new execution workspace:

- checkpoint;
- shape parameters;
- face offsets;
- joint offsets;
- locator offsets.

Only the staged copies are passed to the adapter. After execution BodyRig re-hashes the staged copies again and rejects any adapter that changed those bytes or added files to the staged-teacher universe.

## Adapter config

The adapter is explicit and revision-bound. Example:

```json
{
  "format": "bodyrig-photoreal-p3-device-distillation-config",
  "version": 1,
  "adapter": "bodyrig-quest-student-v1",
  "revision": "<PINNED_REVISION>",
  "student_representation": "skinned-mesh-neural-texture",
  "command": ["python", "distill_adapter.py"],
  "timeout_seconds": 86400,
  "supported_target_models": ["quest-2", "quest-3", "quest-3s"],
  "supported_fidelity_delta_dimensions": [
    "identity_likeness",
    "face_detail",
    "eyes",
    "hair_silhouette_and_appearance",
    "skin_material_response",
    "hands_and_extremities",
    "motion_identity_preservation",
    "temporal_stability"
  ],
  "reports_teacher_student_delta": true,
  "gaussian_splat_target_support": false,
  "consumes_staged_teacher_only": true
}
```

The adapter is invoked with the BodyRig request path, staged teacher root, output root, adapter/revision and selected student representation.

It must emit `output/distillation-manifest.json` and list:

- the exact staged teacher-source bytes it consumed;
- exactly one teacher-to-student delta for every required fidelity dimension;
- every generated student artifact with size and SHA-256;
- no claim that student fidelity exceeds the accepted teacher.

BodyRig core then re-hashes every student artifact and requires the output artifact universe to match the manifest exactly.

## Authority after success

A successful run produces `p3-device-distillation-execution-receipt.json` with:

- distillation complete;
- teacher staging verified before and after adapter execution;
- student artifact bytes core-verified;
- fidelity deltas present for the full canonical universe;
- human physical runtime visual review still required;
- runtime acceptance false;
- broader photoreal acceptance false;
- production activation false.

## Operator

```powershell
.\run-photoreal-v2-p3-device-distillation.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -Config <PINNED_DISTILLATION_CONFIG_JSON>
```

The next boundary is not another automatic metric gate. It is physical runtime materialization and human review on the target Quest class, using the generated student package and the recorded teacher-to-student deltas as evidence.
