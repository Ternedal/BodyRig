# One-command recovery throughput review preparation

This helper shortens the post-candidate operator flow for PR #60 without creating a new evidence or authority path.

Use it only after the uncapped baseline and sampled candidate body-build jobs have both succeeded, while the rig is still on the exact clean candidate checkout that produced the candidate job:

```powershell
.\prepare-recovery-throughput-review.ps1 `
  -PersonId "person-<32 hex>"
```

Use `-NoBrowser` when the bundle should be prepared without opening the HTML review page. `-Out` may be supplied for an explicit create-only bundle destination.

## What it does

1. Runs the existing `compare-recovery-throughput-auto.ps1` with the requested Person id.
2. Therefore uses the existing newest-candidate + exact-parent-baseline selection rule and the canonical fail-closed machine A/B audit.
3. Writes that first machine report only to a unique temporary scratch path.
4. Refuses to continue unless the report is exactly `bodyrig-recovery-throughput-sampling-audit` v1, belongs to the requested Person, has `machine_evidence_pass=true`, has decision `eligible-for-human-ab-review`, and still has `promotion_authority=false` plus `production_activation=false`.
5. Reads the exact baseline/candidate job ids selected by that canonical auto-comparator.
6. Calls `build-recovery-throughput-review-bundle.ps1` with those exact ids.
7. The bundle builder independently re-runs the full machine evidence gate before copying any review bytes.
8. Verifies `review-bundle.json` and `index.html` exist after the successful create-only build.
9. Opens `index.html` unless `-NoBrowser` was supplied.
10. Deletes only the temporary scratch machine report in `finally`.

The durable bundle still contains its own canonical `machine-audit.json`; deleting the preliminary scratch report does not remove or weaken evidence.

## What it deliberately does not do

The helper does **not**:

- record a human visual PASS or FAIL;
- call `record-recovery-throughput-human-review.ps1` on the operator's behalf;
- switch Git branches or update BodyRig;
- restore Person Studio authority;
- activate a body/person;
- merge PR #60;
- move physical authority;
- grant promotion or production authority.

After inspecting all four canonical views in the generated `index.html`, record the explicit human receipt with `record-recovery-throughput-human-review.ps1`. Then restore the rig to canonical Person Studio authority exactly as required by `RECOVERY_THROUGHPUT_AB.md`.

This helper is operator ergonomics only. The physical A/B, human-review and explicit-promotion boundaries remain unchanged.
