# Photoreal V2 → Person binding authority

Photoreal V2 P3 currently proves an accepted photoreal/runtime result for one Stash performer lineage. The canonical BodyRig M4→M6 release chain, however, is Person-revision based.

This authority is the explicit bridge between those identity domains. It does **not** modify an `.mrbody`, create M4 authority, satisfy M5, or activate production.

## Required inputs

The binding operator requires:

- one exact BodyRig Person library;
- one exact Person id;
- the current Person assembly receipt;
- the exact promoted body-release status used by that Person/body lineage;
- one strict all-PASS Photoreal V2 P3 physical runtime review;
- an exact clean BodyRig checkout.

Run:

```powershell
.\bind-photoreal-v2-person.ps1 `
  -PersonLibrary <PERSON_LIBRARY> `
  -PersonId <PERSON_ID> `
  -AssemblyReceipt <ASSEMBLY_RECEIPT> `
  -BodyReleaseStatus <BODY_RELEASE_STATUS> `
  -P3PhysicalReview <P3_PHYSICAL_RUNTIME_REVIEW> `
  -Output <PHOTOREAL_PERSON_BINDING_JSON>
```

## Fail-closed identity rules

The authority is created only when all of these remain true:

1. the Person profile is valid and still contains the exact Person revision named by the assembly receipt;
2. that immutable Person revision references the same body revision as the assembly receipt;
3. the promoted body-release package SHA matches the Person profile body revision;
4. that body revision still has a valid BodyRig source-alignment receipt;
5. the Person source is an exact `stash-performer` binding;
6. the P3 receipt performer id equals that exact Person Stash performer id;
7. the P3 receipt strictly validates and records:
   - `runtime_review_status=pass`;
   - `runtime_acceptance_authority=true`;
   - `photoreal_acceptance_authority=true`;
   - `production_activation=false`.

The resulting authority binds exact Person/body identity, source-binding evidence, the promoted body package SHA and the exact P3 receipt bytes/content.

## Authority boundary

A successful artifact records:

```text
photoreal_binding_authority = true
m4_photoreal_integration_eligible = true
production_activation = false
```

`m4_photoreal_integration_eligible=true` means only that the identity bridge is proven strongly enough for a later M4 integration step to consume it.

It does **not** mean M4 currently consumes the binding, and it does not grant M4, M5, M6, `digital_twin_ready` or production authority by itself.

The next integration step is to make M4 explicitly consume and revalidate this authority when Photoreal V2 is selected as the visual-authority path.
