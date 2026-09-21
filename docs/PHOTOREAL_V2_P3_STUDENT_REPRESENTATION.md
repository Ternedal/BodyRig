# BodyRig Photoreal V2 - P3 student representation selection

Status: execution-preparation boundary, not runtime or production authority.

This gate consumes the accepted P3 device-distillation plan from `#1003` and records one explicit deployment representation before any distillation adapter may be selected or run.

## Why this is separate from the P3 plan

The P3 plan intentionally keeps the candidate representation universe open. This receipt narrows that universe only after the target headset is fixed. It does not modify the accepted ExAvatar teacher and it does not grant permission to start a distillation job.

## Quest 2 policy

Quest 2 is the first owned-hardware target. Native Gaussian splats are therefore not allowed as the primary dependency for this target.

The intended first engineering direction is:

- primary: `hybrid-mesh-neural-residual`;
- optional: `specialized-eye-component`;
- optional: `teacher-derived-hair-component`.

This matches the existing mesh + learned appearance + compact residual direction while preserving explicit identity-critical eyes and teacher-derived hair.

Quest 3/3S may later select `gaussian-splat-optional`, but only as an explicit target-specific choice.

## Authority boundary

A valid selection receipt means:

- the representation is selected explicitly by the operator;
- the exact P3 plan SHA and target-profile SHA are bound;
- the accepted teacher checkpoint remains the visual authority;
- fidelity-delta reporting remains mandatory;
- a distillation adapter is still required and still unselected;
- no distillation job may start;
- runtime acceptance remains false;
- broader photoreal acceptance remains false;
- production remains false.

## Operator

From a clean `main` checkout after the accepted P3 plan exists:

```powershell
.\prepare-photoreal-v2-p3-student-representation.ps1 \
  -P3Root "C:\path\to\p3-device-distillation" \
  -PrimaryRepresentation "hybrid-mesh-neural-residual" \
  -OptionalComponent "specialized-eye-component","teacher-derived-hair-component"
```

The next boundary is adapter selection and byte/version pinning. That gate must consume this exact receipt and still remain fail-closed until the adapter implementation and teacher inputs are revalidated immediately before execution.
