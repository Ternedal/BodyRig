# Photoreal V2 P2 ExAvatar animation identity input

The accepted ExAvatar checkpoint is not sufficient by itself to reproduce animation identity.

Pinned ExAvatar `avatar/main/animate.py` also loads four performer-specific SMPL-X identity files from the teacher dataset:

- `shape_param.json`;
- `face_offset.json`;
- `joint_offset.json`;
- `locator_offset.json`.

Those bytes therefore belong to animation input authority. A valid accepted checkpoint paired with substituted identity geometry is not an accepted animated teacher.

## Boundary

`bodyrig.photoreal_p2_exavatar_animation_identity` runs against the exact Linux ExAvatar workspace named by the original `exavatar-teacher-config.json`.

It:

- strict-validates the current P2 animation plan;
- strict-validates the ExAvatar workspace receipt and its digest;
- strict-validates the completed preprocess state and its digest;
- requires exactly one persisted `smplx-fit` stage;
- finds the four identity files only through that stage's recorded output provenance;
- re-hashes each current identity file and requires exact size/SHA agreement with preprocessing;
- re-hashes the accepted `checkpoint/snapshot_4.pth` in the Windows teacher output and requires exact agreement with the P2 plan;
- copies only the four small identity JSON files into a closed portable export;
- writes a digest-bound receipt;
- rejects extra files in the export universe.

It never re-hashes the source-media library and never reruns fitting, training, or animation.

## Operator

After the P2 animation plan exists:

```powershell
.\prepare-photoreal-v2-p2-exavatar-animation-identity.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT>
```

The operator derives WSL distribution, WSL executable, Linux Python and the exact Linux workspace root from the same `exavatar-teacher-config.json` used for the accepted static teacher.

Output:

```text
<TEACHER_WORK_ROOT>\p2-animated-teacher\animation-input\exavatar-identity\
  identity\shape_param.json
  identity\face_offset.json
  identity\joint_offset.json
  identity\locator_offset.json
  p2-exavatar-animation-identity.json
```

This receipt deliberately keeps `p2_animation_execution_authorized=false`. The next gate must combine this identity authority with the core-verified bounded TRAIN motion-driver receipt before ExAvatar animation may start. HELD-OUT EVALUATION motion remains validation-only.
