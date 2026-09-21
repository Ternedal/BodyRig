# M4 ↔ Photoreal V2 link authority

The canonical BodyRig M4 authority remains version 1 and remains immutable historical/current evidence. Photoreal V2 does not add fields to that contract.

Instead, a separate create-only sidecar binds one exact M4 composition authority to one exact accepted Photoreal Person/P3 authority.

## Why a sidecar

M4 v1 already has deployed evidence and a strict field set. Adding a mandatory Photoreal field to M4 v1 would invalidate historical receipts.

The sidecar preserves M4 v1 while creating a new authority edge:

```text
Person/source + accepted P3
  -> Photoreal Person binding
  -> exact M4 composition
  -> M4 Photoreal link
  -> future Photoreal-aware M5
```

## Operator

From the exact clean checkout used to finalize both the Photoreal Person binding and M4:

```powershell
.\link-photoreal-v2-m4.ps1 `
  -CompositionAuthorityDir <M4_AUTHORITY_DIR> `
  -PhotorealPersonBinding <PHOTOREAL_PERSON_BINDING_JSON> `
  -P3PhysicalReview <P3_PHYSICAL_RUNTIME_REVIEW_JSON>
```

The link requires exact equality across:

- Person id and Person revision;
- assembly fingerprint;
- body revision/id;
- promoted body package SHA-256;
- BodyRig revision.

It also fully revalidates the Photoreal Person binding against the Person library, M4-frozen assembly/body-release inputs and the strict P3 receipt.

## Frozen evidence

The sidecar freezes:

- the exact Photoreal Person binding bytes;
- the exact P3 physical runtime review bytes;
- hashes/content hashes for the exact M4 authority.

Readback revalidates the live canonical M4 authority and the frozen Photoreal evidence. A changed or resealed input cannot silently retain link authority.

## Boundary

A valid link records:

```text
visual_authority = photoreal-v2-p3
m5_photoreal_integration_eligible = true
production_activation = false
```

This is **not M5** and does not activate production. The next contract change is a Photoreal-aware M5 path that explicitly consumes this sidecar while the existing non-Photoreal M5 path remains compatible with historical M4-v1 evidence.
