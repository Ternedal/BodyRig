# Photoreal V2 P3 physical runtime review plan

This is the final software-only boundary before a real standalone Meta Quest review.

It consumes the core-owned P3 distillation execution receipt and re-hashes the current student output bytes. The raw adapter manifest is metadata only; downstream authority comes from the BodyRig execution receipt.

The plan binds:

- exact performer / appearance epoch / P2 / P3 lineage;
- exact target Quest model and refresh-derived frame budget;
- exact base student representation;
- mandatory specialized eye and teacher-derived hair components;
- exact student artifact paths, sizes and SHA-256 values;
- the full eight-dimension teacher-to-student fidelity delta set.

The student output directory must contain exactly the receipt-listed student artifacts, except for the reserved `distillation-manifest.json`.

## Authority boundary

A successful plan means only that the exact student package is ready to be installed and reviewed on the target device.

It requires:

- physical device installation;
- physical device evidence;
- human runtime visual review.

It explicitly keeps:

- `physical_device_evidence_present=false`;
- `runtime_acceptance_authority=false`;
- `photoreal_acceptance_authority=false`;
- `production_activation=false`.

No software-only path can fabricate a Quest PASS.

## Operator

```powershell
.\prepare-photoreal-v2-p3-runtime-review.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT>
```

The next gate must collect real device evidence on the exact target Quest class and record explicit human PASS/FAIL against the installed student package. Any physical runtime failure or visual fidelity regression must keep photoreal/production authority closed.


## Source snapshot binding

The runtime-review plan persists the exact strict-readback P3 distillation plan and core-owned distillation execution receipt used to build it. Standalone readback revalidates both snapshots and requires the top-level target profile, executed adapter revision, student representation/components, student artifact universe and fidelity-delta measurements to match those sources exactly.

For Quest 2, `gaussian-splat-optional` is rejected at this boundary as well, even if a resealed input attempts to reintroduce it. Quest 2 remains on the mesh/neural-residual family; the optional Gaussian path is reserved for Quest 3/3S-class targets.
