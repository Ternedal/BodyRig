> **A/B v1 lifecycle — completed 2026-09-10.** The PBR-v3 / recovery-throughput-v3 shared comparison cycle is finished and promoted under receipt SHA-256 `2daac171b018b0bdb813fb4698c17fa882ef8d130cd9df0ab7e87d7282c9850d`. `contracts/ab-baseline-candidates-v1.json` is now immutable historical evidence; it is not an active candidate contract. `contracts/ab-baseline-cycle-state-v1.json` records that closure. `start-ab-baseline.ps1` and `preflight-ab-baseline.ps1` fail closed before physical work until a **new versioned candidate contract/lifecycle** is introduced. This retirement grants no physical acceptance, production activation, or release authority.

# Historical plan-bound recovery throughput A/B continuation

This flow records the completed v1 physical throughput-candidate continuation. It is historical evidence documentation; `start-throughput-candidate-from-ab-plan.ps1` is not a current new-work entrypoint after promotion.

It exists to prevent an operator mix-up between multiple succeeded candidate jobs **and** to enforce that the shared-plan PBR human review actually happened before throughput evaluation. The candidate-start step publishes a create-only `bodyrig-throughput-candidate-run-plan` plus a create-only `bodyrig-throughput-pbr-human-review-gate` receipt that binds that candidate run to the exact reviewed PBR evidence chain.

## Preconditions

- the shared exact-main baseline job has succeeded;
- the plan-bound PBR A/B has completed through `record-pbr-ab-human-review-from-plan.ps1` and has a valid create-only `bodyrig-pbr-plan-bound-human-review-authority`;
- the throughput candidate was started with the canonical `start-throughput-candidate-from-ab-plan.ps1`, not the internal launcher;
- the PBR-to-throughput gate receipt still revalidates against the exact PBR run/review/plan/source/machine bytes;
- that exact candidate job has succeeded;
- the PBR-reviewed source, baseline succeeded-job source and candidate succeeded-job source resolve to the exact same Stash performer;
- both succeeded jobs still have authoritative persisted Person source-binding and four-view body-review receipts matching the hashes recorded when each body job completed;
- baseline and candidate source-bindings resolve to the exact same deterministic `stash-physical-source-manifest-v1` SHA;
- the source-binding receipts also preserve the same success-time source-file hash list, so identical source selection cannot mask differing source bytes at body-job completion;
- the checkout is still the exact clean plan-bound throughput candidate branch/revision;
- the candidate branch still resolves to the same revision and `origin/main` is still the baseline revision frozen by the shared plan.

The canonical wrappers fail closed if any of those conditions drift. `start-throughput-candidate-from-ab-plan-internal.ps1` and `record-throughput-human-review-from-ab-plan-internal.ps1` are implementation details, not operator entrypoints.

## Monitor the long-running candidate

The canonical launcher prints a plan-bound watcher immediately after the candidate job is enqueued. Use that watcher rather than falling back to the generic job monitor when you need to leave the physical run and return later:

```powershell
.\watch-throughput-candidate-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>'
```

The watcher delegates the live progress display to `watch-body-build.ps1`, but it owns the terminal **routing** for this plan-bound candidate. When the job reaches a terminal state it requires the exact create-only candidate-run plan and exact PBR-to-throughput sequencing-gate receipt for the supplied baseline/candidate ids. It structurally checks the terminal job, Person, candidate revision, source enqueue performer, shared-plan/contract lineage, exact candidate-run-plan SHA and comparison-only authority boundary.

The watcher is deliberately advisory. It does **not** reproduce the full continuation validator and it grants no physical, human, promotion or production authority. If routing evidence is missing/drifted or the candidate did not finish with normal `succeeded` status, it prints `THROUGHPUT CANDIDATE CONTINUATION BLOCKED` and emits no next command.

Only an exact normally-succeeded candidate with matching routing evidence gets this canonical next command:

```powershell
.\continue-throughput-review-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>'
```

The continuation wrapper below remains the authority-bearing validator and revalidates the full receipt/source/checkout/PBR chain before it may publish machine-review continuation authority.

## Build plan-bound machine evidence and immutable human-review bundle

From the exact candidate checkout:

```powershell
.\continue-throughput-review-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>'
```

The launcher:

1. validates the shared baseline plan, candidate-run plan receipt and exact PBR-to-throughput gate receipt;
2. replays the checkout-bound PBR human-review gate and requires its exact reviewed Stash performer/source lineage;
3. validates the candidate byte-contract hash, exact branch/HEAD and remote refs;
4. validates the exact succeeded baseline/candidate job identities and retention semantics;
5. runs the checkout-bound `bodyrig.body_job_receipt_authority` validator for both jobs, revalidating their registered body revisions, persisted enqueue/source-binding receipts and persisted four-view body-review chains;
6. requires `PBR-reviewed performer == baseline succeeded-job performer == candidate succeeded-job performer` before expensive machine evidence is created;
7. rehashes each retained source manifest and requires both jobs to bind the exact same deterministic `stash-physical-source-manifest-v1` SHA plus the same success-time source-file hash-list fingerprint before any machine comparison runs;
8. runs `compare-recovery-throughput.ps1` and requires machine A/B PASS for those exact job ids/revisions;
9. builds the immutable four-view review bundle;
10. rechecks checkout/ref stability, replays the PBR gate and both persisted receipt validators, and rechecks performer/source parity; any gate/job/receipt/source-manifest/source-file-hash drift aborts publication;
11. publishes a create-only `bodyrig-throughput-plan-bound-review-continuation` receipt binding the candidate-run plan, exact PBR gate/review lineage, verified Stash performer, both exact job JSON hashes, body revision identities, source-binding hashes, body-review hashes, shared source-manifest SHA, shared success-time source-file hash-list SHA, machine audit and review-bundle receipt hash.

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

The canonical wrapper first requires the create-only `bodyrig-throughput-pbr-human-review-gate` for the selected baseline/candidate jobs and replays the checkout-bound `bodyrig.pbr_human_review_gate` validator against the exact reviewed PBR run. It also requires the gate to bind the exact current candidate-run-plan bytes. Before invoking the internal recorder it consumes `continuation-authority.json`, requires the continuation's PBR sequencing and source-performer parity flags, requires the same verified Stash performer as the live PBR gate, and hashes those exact continuation-authority bytes.

The established plan-bound throughput review logic remains byte-identical in `record-throughput-human-review-from-ab-plan-internal.ps1`. That internal wrapper consumes `continuation-authority.json`, revalidates the shared baseline plan and candidate-run plan, exact candidate checkout and remote refs, both persisted body-job receipt chains, source-manifest/source-file-hash parity, machine audit and immutable review-bundle bytes. It invokes the frozen candidate-owned `record-recovery-throughput-human-review.ps1` in a separate `pwsh`, verifies the resulting human receipt, replays the same receipt/ref authority and publishes the **intermediate** create-only `bodyrig-throughput-plan-bound-human-review-authority` receipt.

The canonical outer wrapper then revalidates the exact continuation-authority bytes, replays the PBR gate again and publishes the canonical terminal sequencing receipt:

```text
<plan-bound-throughput-review-root>.pbr-sequenced-human-review-authority.json
```

with format `bodyrig-throughput-pbr-sequenced-human-review-authority`. It binds the exact PBR human-review gate, PBR human authority/review bytes, verified Stash performer, candidate-run-plan bytes, continuation-authority SHA and intermediate throughput plan-bound human-review authority/human-review bytes.

The terminal sequencing receipt records both `pbr_human_visual_authority_recorded=true` and `human_visual_authority_recorded=true`, but keeps physical acceptance, promotion and production activation false. A human PASS remains comparison evidence only until a later explicit promotion decision exists.

The low-level `record-recovery-throughput-human-review.ps1` and both `*-internal.ps1` wrappers **must not be invoked directly** as canonical #208 sequencing authority.

## Authority boundary

This path is comparison-only. Persisted receipt validation, source-manifest parity, success-time source-file hash parity, exact Stash-performer parity and PBR→throughput sequencing prove evidence integrity/comparability/order only; they do not create a physical PASS. Human visual review is explicit and create-only, but it still does not grant physical acceptance, promotion authority or production activation. This path does not merge the throughput candidate and it does not reinterpret historical physical evidence.