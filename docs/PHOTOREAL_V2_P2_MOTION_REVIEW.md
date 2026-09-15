# Photoreal V2 P2 motion review evidence

This note documents the authority boundary implemented by the P2 motion-review stack.

## Sequence

```text
P1 static teacher human PASS
  -> P2 animation plan
  -> animation adapter execution
  -> core-owned animation execution receipt
  -> human-selected held-out motion review plan
  -> held-out motion reference materialization
  -> explicit human animated-teacher PASS/FAIL
```

## Motion evidence rule

Animated-teacher review uses held-out evaluation video only. The operator selects one held-out observation anchor and one explicit before/after time window for each directly visual motion dimension:

- head turn;
- eye motion;
- mouth motion;
- hand motion;
- full-body pose;
- identity/appearance preservation through motion.

BodyRig does not auto-select the clip that supposedly proves quality.

## Materialization rule

The motion materializer verifies the selected source file SHA-256 before decode and re-decodes each selected anchor with the same OpenCV BGR-array semantics used by P0. The anchor must reproduce the exact P0 frame SHA-256 before the review window is materialized.

Review windows are emitted as deterministic lossless PNG sequences at 24 fps instead of transcoded review video. This avoids making a new video codec/transcode a source of evidence authority.

The current v1 materializer supports flat mono, side-by-side and over-under video. Spatial/VR projection remains fail-closed until the same authoritative deprojection path can be reused here.

## Persisted authority

The raw materializer result is not downstream authority. BodyRig core validates:

- exact request/result lineage;
- source and anchor verification flags;
- planned window universe;
- anchor universe and dimension binding;
- deterministic frame count and timestamps;
- exact PNG paths, sizes and hashes;
- exact output file universe.

Only then may BodyRig write the create-only `bodyrig-photoreal-motion-reference-materialization-receipt`.

Downstream readback uses the strict receipt authority layer. It revalidates the receipt digest and independently reconstructs window IDs, observation IDs, the canonical six-dimension review universe, canonical PNG paths and deterministic 24-fps cadence. Re-sealing a structurally inconsistent receipt is therefore insufficient to create review authority.

## Authority boundary

Materialized motion evidence does not establish animated likeness.

The receipt keeps:

- `human_animated_visual_acceptance_required=true`;
- `animated_teacher_acceptance_authority=false`;
- `p3_device_distillation_authorized=false`;
- `production_activation=false`.

The next gate is an explicit human animated-teacher PASS/FAIL over the exact animation artifacts and exact held-out motion evidence.