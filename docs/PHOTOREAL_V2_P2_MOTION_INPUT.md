# Photoreal V2 P2 motion-input plan

This boundary turns an approved P2 motion-source selection into an exact build-private preparation plan. It does not touch source media.

The plan preserves the private source path binding from the P2 motion evidence index and includes only sources explicitly selected by the human motion-source receipt.

For every selected source it records:

- the opaque public source/group references;
- the private source key, group ID and resolved path;
- the already-bound source SHA-256 and size;
- TRAIN versus HELD-OUT EVALUATION role;
- whether the source is already flat mono or requires exact authorized deprojection;
- that motion-parameter extraction is still required;
- the pinned ExAvatar fitting backend with `camera_mode=virtual`, matching ExAvatar's documented animation-motion preparation path.

## Operator

After the human source selection has been recorded:

```powershell
.\prepare-photoreal-v2-p2-motion-input-plan.ps1 -TeacherWorkRoot <TEACHER_WORK_ROOT>
```

The resulting private plan is written below:

```text
<TEACHER_WORK_ROOT>\p2-animated-teacher\motion-input\p2-motion-input-plan.json
```

This stage deliberately performs no source-media rehash, no frame/video decode, no deprojection, no SMPL-X/camera fitting and no ExAvatar animation.

A valid plan may state only that motion input has been selected and the private preparation plan is ready. It keeps media-preparation execution, animation execution, animated-teacher acceptance, Quest distillation, broader photoreal acceptance and production activation false.

The next software boundary is an explicit preparation runner that consumes this exact plan and creates hash-bound motion parameters without changing the train/evaluation roles.
