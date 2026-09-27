# Photoreal V2 P3 ExAvatar Quest 2 student candidate

This stage materializes the first real device-oriented student from the accepted
ExAvatar teacher. It is intentionally a **candidate stage**, not the final P3
distillation gate.

The candidate is useful because it replaces placeholder/device-planning work
with real runtime bytes:

- body geometry comes from the accepted ExAvatar identity's **refined first-subdivision Gaussian surface**, rather than the low-resolution zero-pose SMPL-X mannequin;
- skinning comes from ExAvatar's upsampled 55-joint skinning-weight universe;
- base color is derived from the accepted teacher checkpoint's zero-pose Human Gaussian RGB values;
- the canonical SMPL-X UV domain is deterministically subdivided with seam-safe midpoint binding;
- every render vertex carries `_BODYRIG_SOURCE_VERTEX` so seam duplicates retain exact source-geometry identity;
- source-derived normal and roughness maps are attached before downstream eye/hair review;
- the resulting mesh is serialized as a skinned VRM using BodyRig's existing
  runtime builder;
- the candidate VRM and baked basecolor are re-hashed by BodyRig core after the
  external materializer exits.

No source video, held-out media, or unstaged teacher model bytes are passed to
the candidate adapter.

## Why this is not final P3 yet

The candidate deliberately persists:

- `student_candidate_complete=true`;
- `p3_distillation_complete=false`;
- `runtime_acceptance_authority=false`;
- `photoreal_acceptance_authority=false`;
- `production_activation=false`.

The exact remaining blocker universe is:

1. `specialized-eye-component`;
2. `teacher-derived-hair-component`;
3. `teacher-student-fidelity-delta-measurement`;
4. `p3-distillation-manifest`.

The base SMPL-X mesh includes the ordinary eye geometry, but candidate v1 does
**not** call that the specialized eye component. Likewise, hair encoded in the
teacher Gaussians may contribute color near the scalp, but candidate v1 does
**not** claim a teacher-derived hair runtime component or preserved hair
silhouette.

## Teacher-to-student appearance transfer

The candidate loads the accepted ExAvatar checkpoint and the four accepted
identity files into an isolated copy of the pinned ExAvatar runtime.

It asks ExAvatar's `HumanGaussian` for:

- refined zero-pose Gaussian `mean_3d`;
- zero-pose base `rgb`;
- the canonical zero-pose SMPL-X mesh and ExAvatar's upsampled zero surface;
- first-subdivision topology;
- zero-pose joint positions;
- upsampled skinning weights and parent topology.

BodyRig deterministically subdivides the canonical SMPL-X UV binding to the first-subdivision geometry and then rasterizes that UV domain into 3D. For every
occupied texel it finds the nearest accepted teacher Gaussian point and copies
that Gaussian's base RGB into the student texture. The bake records:

- teacher point count;
- canonical UV template SHA-256;
- occupied/padded UV coverage;
- mean, p95 and maximum teacher-point transfer distance;
- baked basecolor SHA-256.

This is a real teacher-to-student appearance transfer. It does not invent a flat placeholder color or reuse the old SiTH texture. The resulting candidate is rejected if it collapses to the 10,475-vertex low-resolution surface, loses source-vertex authority, or lacks the source-derived PBR normal/roughness payload.

## Runtime requirements

Candidate v1 is a CUDA/WSL build stage. The Python environment used to execute
the adapter needs the already working ExAvatar dependencies plus:

- PyTorch with CUDA;
- PyTorch3D / the pinned ExAvatar runtime;
- `nvdiffrast`;
- Pillow;
- NumPy;
- the BodyRig package/repository on `PYTHONPATH`.

The accepted ExAvatar workspace must still be present because it supplies the
pinned code and licensed/runtime model assets. The candidate only copies code
and model assets from that workspace. The checkpoint and identity values used
as teacher data come exclusively from BodyRig's isolated P3 staged-teacher
directory.

## Adapter config

The normal P3 adapter config schema is reused. Candidate v1 requires
`skinned-mesh-pbr`.

Example shape:

```json
{
  "format": "bodyrig-photoreal-p3-device-distillation-config",
  "version": 1,
  "adapter": "bodyrig-exavatar-quest2-student-candidate-v1",
  "revision": "<SHA256_OF_ADAPTER_ENTRYPOINT>",
  "entrypoint": "../../tools/photoreal_p3_exavatar_quest2_student_candidate.py",
  "student_representation": "skinned-mesh-pbr",
  "student_components": [
    "specialized-eye-component",
    "teacher-derived-hair-component"
  ],
  "command": [
    "python",
    "../../tools/photoreal_p3_exavatar_quest2_student_candidate.py",
    "--exavatar-workspace-root",
    "<EXAVATAR_WORKSPACE_ROOT>",
    "--canonical-uv-template",
    "<SMPLX_UV_OBJ>"
  ],
  "timeout_seconds": 86400,
  "supported_target_models": ["quest-2"],
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

The config still declares the final required component/fidelity universe because
it is derived from the same P3 plan. Candidate v1 does **not** claim those
requirements have been satisfied; its own core receipt records the explicit
remaining blockers.

## Core runner

Run the candidate through the dedicated core boundary, not through the final P3
distillation runner:

```bash
python -m bodyrig.photoreal_p3_quest2_student_candidate_runner \
  --config <QUEST2_CANDIDATE_CONFIG_JSON> \
  --plan <P3_DEVICE_DISTILLATION_PLAN_JSON> \
  --teacher-output-root <ACCEPTED_EXAVATAR_TEACHER_OUTPUT_ROOT> \
  --identity-root <ACCEPTED_EXAVATAR_IDENTITY_ROOT> \
  --workspace <NEW_CANDIDATE_WORKSPACE>
```

A successful run produces:

- `output/student/avatar.vrm`;
- `output/student/basecolor.png`;
- `output/quest2-student-candidate.json`;
- `p3-quest2-student-candidate-receipt.json`.

BodyRig core verifies the exact output artifact universe and the staged teacher
bytes again after adapter execution.

## Next implementation boundary

The next code should not add another generic gate. It should promote real
device components:

1. extract/construct a separate eye runtime component from the accepted
   ExAvatar/SMPL-X eye authority and teacher appearance;
2. derive a Quest-safe hair geometry/shell component from teacher Gaussians
   outside the body/scalp surface;
3. render teacher and student under the same fixed views/motions and compute
   the eight explicit teacher-to-student deltas;
4. only then emit the final P3 distillation manifest accepted by
   `photoreal_p3_device_distillation_runner`.
