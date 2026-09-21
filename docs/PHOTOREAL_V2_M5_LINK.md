# Photoreal-aware M5 link authority

The existing BodyRig M5 contract remains unchanged. It still proves that the exact M4 composition was physically realized on real WindowsPlayer and Quest-class targets.

Photoreal V2 adds a separate create-only sidecar **after** canonical M5 is complete. The sidecar binds those exact M5 realization bytes to the exact M4↔Photoreal authority from the previous stage.

## Operator

Run from the exact clean BodyRig checkout shared by the M4 Photoreal link and M5 evidence:

```powershell
.\link-photoreal-v2-m5.ps1 `
  -CompositionAuthorityDir <M4_AUTHORITY_DIR> `
  -AcceptanceDir <CANONICAL_ACCEPTANCE_DIR> `
  -M4PhotorealLinkDir <M4_PHOTOREAL_LINK_DIR>
```

The operator refuses to create authority unless the existing M5 inspector reports:

```text
m5_ready = true
digital_twin_ready = false
production_activation = false
```

Both required platform realizations must already be canonical complete:

- `windows-unity-univrm`;
- `android-quest-class`.

## Bound evidence

The sidecar freezes exact copies of:

- the M4 Photoreal link authority;
- Windows `platform-input.json`;
- Windows `realization.json`;
- Quest `platform-input.json`;
- Quest `realization.json`.

It also binds the exact Person/body/M4 identity and BodyRig revision. Readback rebuilds the expected authority from the live canonical M4 Photoreal link and canonical M5 acceptance state, so a resealed or replaced realization cannot retain authority.

## Boundary

A valid sidecar records:

```text
visual_authority = photoreal-v2-p3
photoreal_m5_ready = true
m6_photoreal_release_eligible = true
production_activation = false
```

This still does not release the digital twin. A later Photoreal-aware M6 contract must explicitly consume and revalidate this authority before setting `digital_twin_ready=true` or `production_activation=true`.
