# P3 Quest 2 interactive human review

After prepare-photoreal-v2-p3-quest2-physical-evidence-from-machine.ps1 has produced a machine-safe prefill, the remaining human review no longer requires hand-editing JSON.

Run the interactive operator:

    .\complete-photoreal-v2-p3-quest2-physical-evidence-review.ps1 -MachinePrefill <P3_MACHINE_PREFILL_JSON>

The operator:

- requires the untouched machine prefill;
- preserves all machine-observed refresh, frame-time, stereo and installed-hash evidence;
- asks the human reviewer for an explicit pass or fail for every visual fidelity criterion;
- requires reviewer identity and non-empty review notes;
- requires the exact final confirmation text REVIEW COMPLETE;
- creates a new evidence file instead of mutating the machine prefill.

It deliberately does not grant runtime acceptance, photoreal acceptance or production activation.

The resulting file is only input evidence. Final authority still comes from the existing strict recorder:

    .\record-photoreal-v2-p3-quest2-physical-runtime-review.ps1 -RuntimeReviewWorkspace <P3_RUNTIME_REVIEW_WORKSPACE> -Evidence <P3_HUMAN_REVIEW_EVIDENCE_JSON>

If any visual criterion is fail, the strict recorder persists a FAIL receipt and keeps runtime/photoreal authority false. Production activation remains false in both PASS and FAIL cases.
