# Plan-bound recovery throughput A/B continuation

This flow is for the physical throughput candidate created by the canonical `start-throughput-candidate-from-ab-plan.ps1` sequencing gate.

It exists to prevent an operator mix-up between multiple succeeded candidate jobs **and** to enforce that the shared-plan PBR human review actually happened before throughput evaluation. The candidate-start step publishes a create-only `bodyrig-throughput-candidate-run-plan` plus a create-only `bodyrig-throughput-pbr-human-review-gate` receipt that binds that candidate run to the exact reviewed PBR evidence chain.

## Preconditions

- the shared exact-main baseline job has succeeded;
- the plan-bound PBR A/B has completed through `record-pbr-ab-human-review-from-plan.ps1` and has a valid create-only `bodyrig-pbr-plan-bound-human-review-authority`;
- the throughput candidate was started with the canonical `start-throughput-candidate-from-ab-plan.ps1`, not the internal launcher;
- the PBR-to-throughput gate receipt still revalidates against the exact PBR run/review/plan/source/machine bytes;
- that exact candidate job has succeeded;
- both succeeded jobs still have authoritative persisted Person source-binding and four-view body-review receipts matching the hashes recorded when each body job completed;
- baseline and candidate source-bindings resolve to the exact same deterministic `stash-physical-source-manifest-v1` SHA;
- the source-binding receipts also preserve the same success-time source-file hash list, so identical source selection cannot mask differing source bytes at body-job completion;
- the checkout is still the exact clean plan-bound throughput candidate branch/revision;
- the candidate branch still resolves to the same revision and `origin/main` is still the baseline revision frozen by the shared plan.

The canonical wrappers fail closed if any of those conditions drift. `start-throughput-candidate-from-ab-plan-internal.ps1` and `record-throughput-human-review-from-ab-plan-internal.ps1` are implementation details, not operator entrypoints.

## Build plan-bound machine evidence and immutable human-review bundle

From the exact candidate checkout:

```powershell
.\continue-throughput-review-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>'
```

The launcher:

1. validates the shared baseline plan and candidate-run plan receipt;
2. validates the candidate byte-contract hash, exact branch/HEAD and remote refs;
3. validates the exact succeeded baseline/candidate job identities and retention semantics;
4. runs the checkout-bound `bodyrig.body_job_receipt_authority` validator for both jobs, revalidating their registered body revisions, persisted source-binding receipts and persisted four-view body-review chains;
5. rehashes each retained source manifest and requires both jobs to bind the exact same deterministic `stash-physical-source-manifest-v1` SHA plus the same success-time source-file hash-list fingerprint before any machine comparison runs;
6. runs `compare-recovery-throughput.ps1` and requires machine A/B PASS for those exact job ids/revisions;
7. builds the immutable four-view review bundle;
8. rechecks checkout/ref stability and replays both persisted receipt validators; any job/receipt/source-manifest/source-file-hash drift aborts publication;
9. publishes a create-only `bodyrig-throughput-plan-bound-review-continuation` receipt binding the candidate-run plan, both exact job JSON hashes, body revision identities, source-binding hashes, body-review hashes, shared source-manifest SHA, shared success-time source-file hash-list SHA, machine audit and review-bundle receipt hash.

Temporary output is removed on failure; incomplete evidence is not promoted to a final continuation directory.

## Human review

The continuation never records a human decision automatically. Review all four canonical views and then use the **canonical main-owned wrapper** that the continuation prints:

```powershell
.\record-throughput-human-review-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>' `
  -RunDir '<plan-bound-throughput-review-root>' `
  -IdentityShape pass `
  -FaceIdentity pass `
  -SkinTextureAlignment pass `
  -GrossAnatomy pass `
  -Note '<actual visual assessment>' `
  -ConfirmVisualReview
```

The canonical wrapper first requires the create-only `bodyrig-throughput-pbr-human-review-gate` for the selected baseline/candidate jobs and replays the checkout-bound `bodyrig.pbr_human_review_gate` validator against the exact reviewed PBR run. It also requires the gate to bind the exact current candidate-run-plan bytes.

The established plan-bound throughput review logic remains byte-identical in `record-throughput-human-review-from-ab-plan-internal.ps1`. That internal wrapper consumes `continuation-authority.json`, revalidates the shared baseline plan and candidate-run plan, exact candidate checkout and remote refs, both persisted body-job receipt chains, source-manifest/source-file-hash parity, machine audit and immutable review-bundle bytes. It invokes the frozen candidate-owned `record-recovery-throughput-human-review.ps1` in a separate `pwsh`, verifies the resulting human receipt, replays the same receipt/ref authority and publishes the **intermediate** create-only `bodyrig-throughput-plan-bound-human-review-authority` receipt.

The canonical outer wrapper then replays the PBR gate again and publishes the canonical terminal sequencing receipt:

```text
<plan-bound-throughput-review-root>.pbr-sequenced-human-review-authority.json
```

with format `bodyrig-throughput-pbr-sequenced-human-review-authority`. It binds the exact PBR human-review gate, PBR human authority/review bytes, candidate-run-plan bytes and intermediate throughput plan-bound human-review authority/human-review bytes.

The terminal sequencing receipt records both `pbr_human_visual_authority_recorded=true` and `human_visual_authority_recorded=true`, but keeps physical acceptance, promotion and production activation false. A human PASS remains comparison evidence only until a later explicit promotion decision exists.

The low-level `record-recovery-throughput-human-review.ps1` and both `*-internal.ps1` wrappers **must not be invoked directly** as canonical #208 sequencing authority.

## Authority boundary

This path is comparison-only. Persisted receipt validation, source-manifest parity, success-time source-file hash parity and PBR→throughput sequencing prove evidence integrity/comparability/order only; they do not create a physical PASS. Human visual review is explicit and create-only, but it still does not grant physical acceptance, promotion authority or production activation. This path does not merge the throughput candidate and it does not reinterpret historical physical evidence.
