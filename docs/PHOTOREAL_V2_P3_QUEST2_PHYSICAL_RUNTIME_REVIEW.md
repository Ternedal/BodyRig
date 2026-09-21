# Photoreal V2 P3 Quest 2 physical PASS/FAIL

This is the first stage on the modular Quest 2 path that is allowed to grant runtime and photoreal acceptance authority.

It cannot do so from CI, generated screenshots, synthetic metrics or software evidence alone.

A real target Quest must be physically observed, the exact final student artifacts must be verified on-device, and a human reviewer must explicitly record PASS/FAIL for every required fidelity dimension.

## Inputs

The stage consumes the exact runtime-review workspace produced by:

```text
prepare-photoreal-v2-p3-quest2-runtime-review.ps1
```

Specifically:

```text
p3-quest2-runtime-review/
  p3-device-runtime-review-plan.json
```

The plan already binds:

- exact P2/P3 lineage;
- final distillation execution receipt;
- exact Quest 2 target profile;
- final student VRM;
- final teacher-derived basecolor;
- final modular provenance artifact;
- all eight measured teacher-to-student fidelity deltas.

## Evidence template

Create a non-authoritative review template:

```powershell
.\prepare-photoreal-v2-p3-quest2-physical-evidence-template.ps1 \
  -RuntimeReviewWorkspace <P3_QUEST2_RUNTIME_REVIEW_WORKSPACE>
```

This writes:

```text
p3-physical-runtime-evidence.template.json
```

The template pre-populates:

- runtime-review-plan SHA;
- target device class;
- all expected final artifact paths and SHA-256 values;
- all eight visual criteria.

It is deliberately invalid as final evidence:

- `physical_device_observed=false`;
- refresh and p95 frame time are unset;
- stereo/frame-pacing/hash-verification are false;
- every visual decision is `REVIEW_REQUIRED`;
- `confirm_physical_device_review_complete=false`.

This prevents a generated template from accidentally becoming acceptance evidence.

## Physical evidence requirements

After the actual Quest review, the operator-supplied evidence must contain:

- `physical_device_observed=true`;
- exact installed artifact paths and on-device SHA-256 values;
- observed refresh rate;
- p95 frame time;
- physically observed stereo rendering;
- physically observed VR-safe frame pacing;
- explicit confirmation that installed hashes were verified on-device;
- PASS/FAIL for all eight canonical fidelity dimensions:
  - identity likeness;
  - face detail;
  - eyes;
  - hair silhouette and appearance;
  - skin material response;
  - hands and extremities;
  - motion identity preservation;
  - temporal stability;
- reviewer identity;
- non-empty review notes;
- `confirm_physical_device_review_complete=true`.

The installed artifact universe must exactly match the plan, including the modular provenance artifact.

## Derived performance decisions

Performance decisions are not entered manually.

BodyRig derives them fail-closed from raw evidence:

1. observed refresh >= target refresh;
2. p95 frame time <= target frame-time budget;
3. stereo rendering observed;
4. VR-safe frame pacing observed;
5. installed final artifact hashes verified on-device.

A reviewer cannot reseal the JSON to convert a raw performance failure into PASS; strict readback recomputes these decisions.

## Guided human review without hand-editing JSON

When the machine probe has already been converted to the safe machine prefill:

```text
p3-physical-runtime-evidence.machine-prefill.json
```

use the guided operator instead of editing that JSON directly:

```powershell
.\complete-photoreal-v2-p3-quest2-human-review.ps1 `
  -RuntimeReviewWorkspace <P3_QUEST2_RUNTIME_REVIEW_WORKSPACE> `
  -ReviewedBy "<REVIEWER>" `
  -ReviewNotes "<NOTES>" `
  -IdentityLikeness pass|fail `
  -FaceDetail pass|fail `
  -Eyes pass|fail `
  -HairSilhouetteAndAppearance pass|fail `
  -SkinMaterialResponse pass|fail `
  -HandsAndExtremities pass|fail `
  -MotionIdentityPreservation pass|fail `
  -TemporalStability pass|fail `
  -ConfirmPhysicalDeviceReviewComplete
```

The operator accepts no default PASS values. Every canonical visual criterion is mandatory, and the confirmation switch must be explicitly present. It preserves the machine-proven artifact hashes, refresh/p95 measurements, stereo evidence, frame-pacing evidence and runtime-review-plan binding unchanged.

The result is create-only:

```text
p3-physical-runtime-evidence.reviewed.json
```

The guided operator does **not** grant runtime or photoreal authority. It only creates operator-supplied evidence that the existing final recorder can strict-validate.

## Recording PASS/FAIL

Run:

```powershell
.\record-photoreal-v2-p3-quest2-physical-runtime-review.ps1 \
  -RuntimeReviewWorkspace <P3_QUEST2_RUNTIME_REVIEW_WORKSPACE> \
  -Evidence <COMPLETED_PHYSICAL_QUEST_EVIDENCE_JSON>
```

The output is create-only:

```text
p3-quest2-runtime-review/
  p3-physical-runtime-review.json
```

## Authority

If **any** visual or performance criterion fails:

```text
runtime_review_status = fail
runtime_acceptance_authority = false
photoreal_acceptance_authority = false
production_activation = false
```

Only a complete all-PASS physical review can set:

```text
runtime_review_status = pass
runtime_acceptance_authority = true
photoreal_acceptance_authority = true
```

Even an all-PASS physical review still records:

```text
production_activation = false
```

Production remains a separate later authority boundary.

## Non-automatable boundary

GitHub Actions may test the validators, schemas and operators.

GitHub Actions cannot create a physical Quest PASS.

The PASS receipt is valid only when tied to the exact runtime-review-plan SHA and explicit evidence from the physically observed target headset.
