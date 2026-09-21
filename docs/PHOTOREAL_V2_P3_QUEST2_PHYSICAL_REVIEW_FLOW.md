# P3 Quest 2 one-command physical review flow

After the P3 machine probe has been collected on the physical Quest 2, the remaining evidence/review sequence can be run as one operator flow:

    .\run-photoreal-v2-p3-quest2-physical-review-flow.ps1 -RuntimeReviewWorkspace <P3_RUNTIME_REVIEW_WORKSPACE> -MachineProbe <P3_QUEST2_MACHINE_PROBE_JSON>

The flow deliberately composes the existing authority boundaries instead of replacing them.

It runs, in order:

1. machine-safe physical evidence prefill;
2. explicit interactive human in-headset visual review;
3. strict physical runtime PASS/FAIL recorder.

Each stage runs in its own child PowerShell process so the existing stage scripts keep their independent exit semantics.

The evidence artifacts remain create-only, but the wrapper itself is resumable:

- an existing machine prefill is reused only after it is reproduced and matched against the exact current runtime-review plan and machine probe;
- an existing human-reviewed evidence file is reused only after its machine-bound fields match that exact revalidated prefill;
- an existing final physical-review receipt is treated as completed evidence and is never overwritten.

This means an interruption after machine prefill or after human review does not require deleting evidence and repeating already completed work.

The human review remains mandatory. The wrapper never supplies visual pass/fail decisions and cannot provide the final human attestation on the reviewer's behalf. Reuse applies only to an already completed explicit human review whose machine evidence still matches the current invocation.

The final receipt may grant runtime and photoreal acceptance only through the existing strict recorder. Production activation remains false regardless of PASS or FAIL.
