# Photoreal V2 — Quest 2 runtime materialization

The ExAvatar Quest 2 PBR adapter produces a core-verified student in the P3 execution output. The Unity/UniVRM reference renderer does not accept a loose VRM; it accepts the existing `bodyrig-runtime-assets` v1 contract.

This boundary converts the exact core-owned P3 student into that loader contract without pretending it passed an older Gate A clone flow.

## Runtime contents

The materialized runtime contains:

- `runtime-manifest.json`;
- `avatar.vrm`;
- `bodyprint.json`;
- `p3-quest-runtime-package-receipt.json`.

`avatar.vrm` is copied byte-for-byte from the core-verified `quest2-vrm-student-runtime` artifact.

`bodyprint.json` is a new P3 provenance record. It binds the performer/epoch, target Quest 2 class, exact adapter + SHA revision, P3 plan/request/execution receipts, student provenance and complete teacher-to-student fidelity deltas. It does not claim an old physical clone acceptance.

The existing reference renderer loader only requires that `bodyprint.json` is present and SHA-bound; it does not reinterpret its internal schema.

## Package identity

The runtime package SHA is deterministic over:

- exact avatar SHA-256;
- exact bodyprint file SHA-256;
- the fixed P3 Quest runtime package domain.

The loader manifest preserves its established fixed paths:

- `avatar = avatar.vrm`;
- `bodyprint = bodyprint.json`.

## Authority

Materialization proves only that the exact student bytes are packaged for the existing Unity/UniVRM loader.

It keeps:

- physical review required;
- runtime acceptance false;
- photoreal acceptance false;
- production false.

## Operator

```powershell
.\prepare-photoreal-v2-p3-quest-runtime.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT>
```

The next physical operator can build/install the pinned reference-renderer APK, push this runtime to Quest 2 and collect device/deformation evidence without creating a fake legacy Gate A receipt.
