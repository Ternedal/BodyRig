# Photoreal V2 P3 Quest 2 physical runtime review plan

This stage is the first boundary after the modular Quest 2 distillation has reached `distillation_complete=true`.

It does not accept the avatar. It prepares an exact plan for installing and reviewing the already-frozen final student on a real standalone Quest.

## Inputs

The modular operator consumes:

- the original P3 distillation plan;
- the final modular P3 workspace from `run-photoreal-v2-p3-quest2-final-manifest.ps1`.

From the final workspace it uses:

- `p3-device-distillation-execution-receipt.json`;
- `output/` containing the exact final student artifacts and distillation manifest;
- `p3-quest2-final-workspace-receipt.json` as operator-visible provenance.

The core runtime-review plan strict-reads the canonical execution receipt and re-hashes every receipt-listed student artifact again.

## What is reverified

The plan binds and verifies:

- performer / epoch / P2 / P3 lineage;
- target Quest model and exact refresh/frame-time target;
- selected base adapter + revision;
- `skinned-mesh-pbr`;
- specialized eye + teacher-derived hair requirements;
- all final student artifact paths, sizes and SHA-256 values;
- all eight teacher-to-student fidelity deltas.

The final modular provenance artifact is treated like every other student artifact: its exact bytes must still match the execution receipt.

## Authority boundary

A successful plan means only:

> these exact bytes are ready to be installed and physically reviewed on this exact target class.

It records:

- physical device installation required = true;
- physical device evidence required = true;
- physical device evidence present = false;
- human runtime visual acceptance required = true;
- runtime review ready = true;
- runtime acceptance authority = false;
- photoreal acceptance authority = false;
- production activation = false.

No software-only execution can fabricate the Quest PASS.

## Operator

```powershell
.\prepare-photoreal-v2-p3-quest2-runtime-review.ps1 \
  -DistillationPlan <P3_DEVICE_DISTILLATION_PLAN_JSON> \
  -FinalWorkspace <P3_QUEST2_FINAL_DISTILLATION_WORKSPACE>
```

By default the plan is written to an isolated sibling workspace:

```text
p3-quest2-runtime-review/
  p3-device-runtime-review-plan.json
```

The final distillation workspace is not modified.

## Next boundary

The next step is physical evidence collection on the real Quest:

- install the exact student bytes;
- verify installed artifact hashes on-device;
- measure achieved refresh rate and p95 frame time;
- confirm stereo rendering and VR-safe frame pacing;
- perform explicit human visual PASS/FAIL for all required fidelity dimensions.

That evidence must remain tied to this exact runtime-review-plan SHA.
