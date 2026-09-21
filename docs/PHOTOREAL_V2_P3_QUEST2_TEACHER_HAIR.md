# Photoreal V2 P3 Quest 2 teacher-derived hair

This stage is stacked on the exact specialized-eye student from P3 Quest 2 and removes only the `teacher-derived-hair-component` blocker.

It does **not** treat scalp colour as completed hair.

## Source authority

The hair envelope is regenerated from the exact five staged teacher files already retained inside the Quest 2 candidate workspace:

- accepted ExAvatar checkpoint;
- `shape_param.json`;
- `face_offset.json`;
- `joint_offset.json`;
- `locator_offset.json`.

The generator revalidates the candidate receipt, request digest, staged teacher byte universe, accepted ExAvatar workspace receipt, pinned ExAvatar revision and linked human-model assets before loading the zero-pose teacher.

No P0/P2 dataset is rehashed and no teacher is retrained.

## Geometry derivation

The generator compares accepted ExAvatar zero-pose teacher points with the exact zero-pose SMPL-X donor.

For each teacher point it:

1. finds the nearest donor vertex in bounded CUDA chunks;
2. measures outward displacement along the donor normal;
3. rejects non-finite, inward and implausibly distant samples;
4. retains the maximum accepted outward teacher displacement per donor vertex.

BodyRig then applies the same conservative shape logic used by the retained source-hair path:

- head-region restriction;
- minimum teacher/body separation;
- seed region at the upper head;
- one connected seed-bearing shell only;
- minimum face count;
- minimum head footprint;
- minimum vertical span;
- a stricter normal mode followed by a bounded short-hair fallback.

If neither mode proves a usable connected shell, the stage fails. It does not silently substitute a scalp shell.

The persisted envelope stores face indices plus the three exact normal offsets for each selected triangle and is SHA-bound to the P3 request, candidate receipt and accepted teacher checkpoint.

## Quest representation

The core hair stage strict-reads the exact P3 eye receipt and re-hashes its current VRM/basecolor bytes.

It then appends one separately skinned mesh primitive:

- positions are the exact current student body triangle corners displaced by the accepted teacher envelope;
- UVs are inherited from the current student;
- LBS joints/weights are inherited from the current student;
- appearance uses the exact teacher-derived basecolor bytes;
- the original body and specialized-eye meshes are not modified.

This is a bounded mesh representation suitable for standalone Quest 2. It does not require native Gaussian rendering at runtime.

## Authority after success

A successful core run records:

- `specialized-eye-component` implemented;
- `teacher-derived-hair-component` implemented;
- teacher-derived/non-generative geometry;
- exact artifact-byte verification;
- physical hair-silhouette review still required;
- physical face close-up review still required;
- separate eyelash geometry **not claimed**;
- runtime acceptance false;
- photoreal acceptance false;
- production activation false.

The remaining P3 blockers are then:

1. `teacher-student-fidelity-delta-measurement`;
2. `p3-distillation-manifest`.

The hair component is therefore an implementation milestone, not visual acceptance.

## Operator flow

On Windows, the preferred path is the one-command wrapper. It reads the already pinned `exavatar-teacher-config.json`, reuses its WSL distribution/Python/workspace and performs both the Linux envelope step and the Windows core graft:

```powershell
.\\run-photoreal-v2-p3-quest2-teacher-hair.ps1 \
  -TeacherWorkRoot <TEACHER_WORK_ROOT> \
  -CandidateWorkspace <P3_CANDIDATE_WORKSPACE> \
  -EyeOutputRoot <P3_EYE_OUTPUT_ROOT>
```

The wrapper requires a clean checkout, never reruns teacher training, never rehashes the P0/P2 source corpus and keeps every output create-only.

For manual/debug execution, first generate the envelope in the same pinned ExAvatar Linux/CUDA environment used by the accepted teacher:

```powershell
wsl.exe -d <DISTRO> -- /usr/bin/env PYTHONNOUSERSITE=1 <LINUX_PYTHON> \
  <BODYRIG_REPO_WSL>/tools/photoreal_p3_exavatar_quest2_hair_envelope.py \
  --candidate-workspace <CANDIDATE_WORKSPACE_WSL> \
  --exavatar-workspace-root <EXAVATAR_WORKSPACE_LINUX> \
  --output <HAIR_ENVELOPE_WSL>
```

Then graft the envelope onto the exact eye-stage student:

```powershell
python -m bodyrig.photoreal_p3_quest2_hair_student_runner \
  --eye-receipt <EYE_OUTPUT_ROOT>/p3-quest2-eye-student-receipt.json \
  --eye-output-root <EYE_OUTPUT_ROOT> \
  --hair-envelope <HAIR_ENVELOPE_JSON> \
  --output-root <NEW_HAIR_OUTPUT_ROOT>
```

The output is create-only and contains:

- `student/avatar.vrm`;
- `student/basecolor.png` copied byte-for-byte;
- `p3-quest2-hair-student-receipt.json`.

## Next boundary

The next implementation target is an exact teacher-to-student fidelity-delta stage over the completed eye+hair Quest student.

It must measure all canonical P3 dimensions from retained teacher/student evidence rather than inventing quality scores. The final P3 manifest may only be issued after those measurements are complete. Physical Quest review remains a separate human authority gate.
