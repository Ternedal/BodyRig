# Final Photoreal digital-twin release

The existing canonical BodyRig M6-v1 release remains the base production authority. Photoreal V2 does not replace or weaken it.

A final Photoreal release is an **additional** create-only authority that can exist only after both release chains are already valid:

```text
canonical Person/M4/M5 -> canonical M6-v1 RELEASED
Photoreal P3 -> Person binding -> M4 Photoreal link -> Photoreal M5 link
                                  \______________________________/
                                                |
                                   final Photoreal M6 release
```

## Non-bypass rule

The Photoreal release cannot create production authority from P3/M5 evidence alone.

Before creation, BodyRig strict-readbacks:

1. the existing canonical M6-v1 release;
2. the complete Photoreal M5 link;
3. the M4 Photoreal link and its underlying Person/P3 authority through the M5 readback;
4. the exact M4 composition and canonical acceptance evidence through the canonical M6 readback.

The canonical M6 must already record:

```text
state = released
digital_twin_ready = true
production_activation = true
```

The Photoreal M5 authority must still record:

```text
photoreal_m5_ready = true
m6_photoreal_release_eligible = true
production_activation = false
```

Person/revision/body/package/BodyRig revision must match exactly, and Windows/Quest realization SHA-256 values must be identical across both chains.

## Operator

From the exact clean checkout shared by the bound authorities:

```powershell
.\finalize-photoreal-digital-twin.ps1 `
  -CanonicalM6ReleaseDir <CANONICAL_M6_RELEASE_DIR> `
  -CompositionAuthorityDir <M4_AUTHORITY_DIR> `
  -AcceptanceDir <CANONICAL_ACCEPTANCE_DIR> `
  -PhotorealM5LinkDir <PHOTOREAL_M5_LINK_DIR> `
  -M4PhotorealLinkDir <M4_PHOTOREAL_LINK_DIR>
```

Use `-LibraryRoot` only when the canonical Person library is intentionally overridden.

## Final authority

Only after all readbacks pass can the final artifact record:

```text
visual_authority = photoreal-v2-p3
state = released
canonical_digital_twin_ready = true
photoreal_digital_twin_ready = true
production_activation = true
```

The release freezes exact canonical-M6 and Photoreal-M5 authority bytes. Readback rebuilds the expected Photoreal release from both live canonical chains, so replacing or resealing either upstream authority invalidates the final release.
