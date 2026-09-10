# Photoidentity source authority router

BodyRig must not present another avatar for human review until identity-critical source evidence is complete enough to proceed without generic guessing.

The canonical source-authority order is:

1. `collect-photoidentity-evidence.ps1`
   - broad Stash sweep;
   - coarse views + OpenPose eyes/hands/feet + SCHP hair/exposed-skin observability;
   - no avatar render authority.
2. `discover-photoidentity-nail-sources.ps1`
   - source-only hand/foot closeup discovery;
   - machine discovery has no nail identity authority.
3. `prepare-photoidentity-nail-source-review.ps1`
   - exposes only byte-verified review-eligible source closeups.
4. `record-photoidentity-nail-source-attestation.ps1`
   - canonical operator is atomic over both fingernails and toenails;
   - requires both left/right coverage and at least two distinct source scenes per nail domain;
   - no create-only partial nail receipt is permitted by the operator.
5. `discover-photoidentity-anatomy-sources.ps1`
   - source-only rear/torso/waist candidate discovery;
   - OpenPose is locator-only and cannot assert hidden anatomy or rear orientation.
6. `prepare-photoidentity-anatomy-source-review.ps1`
   - exposes only byte-verified review-eligible source crops.
7. `record-photoidentity-anatomy-source-attestation.ps1`
   - atomic human confirmation of actual rear view, observable torso/chest anatomy and observable waist/hips anatomy;
   - anatomy hidden by clothing/occlusion must not be inferred.
8. `register-photoidentity-source-authority.ps1`
   - accepts only the final `anatomy-attested-evidence` bundle;
   - validates the exact nail -> anatomy human source receipt chain;
   - persists create-only body-job authority.
9. High-fidelity preview may only be evaluated after the registered authority passes `require_body_job_photoidentity_evidence(...)`.

Use `photoidentity-source-status.ps1` after the initial collection. It reports the exact current stage and the next safe operator action. It never starts reconstruction or rendering, never synthesizes human confirmations, and keeps `generic_guessing_permitted=false` and `production_activation=false`.

## Fail-closed rules

- Partial or ambiguous receipt/evidence state is an error, not a best-effort continuation.
- A friendly capability name is not authority. Registered evidence must use the exact approved analyzer/composite adapter and per-domain claim adapter/revision.
- Final registration requires both human nail domains plus rear/torso/waist human source attestation.
- Source-evidence sufficiency authorizes only the next reconstruction/preview gate to be evaluated. It is not reconstruction quality PASS, physical acceptance, release, or production activation.
- If source data is insufficient, collect/scan more source media. Do not substitute generic anatomy or appearance priors for identity-critical regions.
