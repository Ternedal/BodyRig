# Photoreal V2 P3 Quest 2 integration landing

This document describes the integrated P3 Quest 2 path that is intended to land on `main` through PR #1026.

## End-to-end path

The integrated flow is:

1. materialize the accepted ExAvatar-derived Quest 2 student;
2. add the specialized eye component;
3. add the teacher-derived hair component;
4. measure all canonical teacher-to-student fidelity deltas;
5. materialize the final P3 distillation manifest and execution receipt;
6. build the exact Quest 2 runtime-review plan;
7. stage and byte-verify the exact student artifact universe on the physical Quest 2;
8. load the exact student through the canonical Unity/UniVRM OpenXR reference renderer;
9. collect machine evidence for installed hashes, OpenXR stereo, refresh rate and frame pacing;
10. prefill only machine-observable physical-review evidence;
11. collect explicit human pass/fail decisions for every visual fidelity criterion;
12. record the final strict P3 physical runtime PASS/FAIL receipt.

## Authority boundary

Software-only and machine-only stages do not grant human visual acceptance.

The machine prefill deliberately leaves:

- every visual fidelity decision at `REVIEW_REQUIRED`;
- `operator_supplied=false`;
- `confirm_physical_device_review_complete=false`.

The interactive human-review operator requires an explicit `pass` or `fail` for every visual criterion, reviewer identity, review notes, and the exact final attestation `REVIEW COMPLETE`.

Only the strict physical runtime recorder validates the completed evidence and emits the final runtime-review receipt.

Production activation remains false in both PASS and FAIL cases.

## Landing model

PR #1026 is the integration PR against `main`. Earlier stacked P3 PRs remain useful as implementation history but are superseded for landing by the integration PR.

The integration PR should be squash-merged only when its exact head has successful CI, CodeQL, Windows log-handle regression, and LOC metrics checks.
