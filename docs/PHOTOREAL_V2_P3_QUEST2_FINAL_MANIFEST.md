# Photoreal V2 P3 Quest 2 final distillation manifest

This stage closes the **implementation** side of P3 for the modular Quest 2 student.

It consumes:

- the exact P3 candidate request;
- the exact final specialized-eye + teacher-derived-hair student;
- the exact eight-dimension fidelity-delta evidence.

It then materializes a new create-only final distillation workspace and passes the resulting manifest through BodyRig's existing P3 core validator.

## Final workspace

The workspace contains:

```text
request.json
hair-student-receipt.json
fidelity-delta-evidence.json
p3-device-distillation-execution-receipt.json
p3-quest2-final-workspace-receipt.json
output/
  distillation-manifest.json
  student/
    avatar.vrm
    basecolor.png
    quest2-modular-provenance.json
```

The final student VRM and basecolor are copied byte-for-byte from the immutable hair-stage output.

Any copy mismatch fails the stage.

## Modular provenance

The final student artifact universe includes `quest2-modular-provenance.json`.

It binds:

- candidate request SHA;
- candidate receipt SHA;
- specialized-eye receipt SHA;
- teacher-derived-hair receipt SHA;
- fidelity-delta evidence SHA;
- accepted teacher checkpoint SHA;
- base adapter + adapter revision;
- hair implementation revision SHAs;
- final manifest-builder revision SHA;
- source and copied student artifact SHAs.

This companion artifact is necessary because the legacy P3 manifest schema carries only the selected base adapter fields. The modular provenance makes the post-adapter eye/hair/fidelity chain explicit without weakening or rewriting the established core schema.

## Core manifest

The final `distillation-manifest.json` uses the existing canonical P3 format:

```text
bodyrig-photoreal-p3-device-distillation-manifest
```

It records:

- the original exact P2/P3 lineage;
- Quest 2 target profile SHA;
- selected base adapter + revision;
- `skinned-mesh-pbr`;
- specialized-eye + teacher-derived-hair components;
- the exact five consumed teacher sources;
- all eight canonical fidelity-delta measurements;
- the three final student artifacts;
- `distillation_complete = true`.

The manifest is immediately strict-read through `validate_distillation_result()`.

BodyRig then builds the normal canonical execution receipt through `build_execution_receipt()`.

So the modular path does not introduce a parallel weaker definition of “P3 complete”.

## Authority boundary

`distillation_complete = true` means the planned teacher-to-device representation has been materially built and measured.

It does **not** mean the avatar is physically accepted on Quest.

The final manifest and execution receipt still require:

- human runtime visual acceptance;
- runtime acceptance authority = false;
- photoreal acceptance authority = false;
- production activation = false.

Those flags are intentionally unchanged.

## Windows operator

Preferred execution:

```powershell
.\run-photoreal-v2-p3-quest2-final-manifest.ps1 \
  -CandidateWorkspace <P3_CANDIDATE_WORKSPACE> \
  -HairOutputRoot <P3_HAIR_OUTPUT_ROOT> \
  -FidelityEvidence <P3_FIDELITY_EVIDENCE_JSON>
```

The default final workspace is a sibling named:

```text
p3-quest2-final-distillation
```

The operator requires a clean BodyRig checkout and refuses to overwrite an existing workspace.

## What remains after this stage

After successful final-manifest materialization there are no remaining P3 **implementation** blockers.

The next boundary is physical Quest runtime review.

That review must consume the exact final student bytes and execution receipt. It may produce PASS/FAIL evidence, but no code path in this stage grants that authority automatically.
