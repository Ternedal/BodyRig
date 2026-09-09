# Plan-bound recovery throughput A/B continuation

This flow is for the physical throughput candidate created by `start-throughput-candidate-from-ab-plan.ps1`.

It exists to prevent an operator mix-up between multiple succeeded candidate jobs. The candidate-start step publishes a create-only `bodyrig-throughput-candidate-run-plan` that binds the shared baseline plan, exact baseline job, exact throughput candidate revision/ref, Person and newly enqueued candidate job id. The review continuation must consume that exact receipt.

## Preconditions

- the shared exact-main baseline job has succeeded;
- the throughput candidate was started with `start-throughput-candidate-from-ab-plan.ps1`;
- that exact candidate job has succeeded;
- both succeeded jobs still have authoritative persisted Person source-binding and four-view body-review receipts matching the hashes recorded when each body job completed;
- baseline and candidate source-bindings resolve to the exact same `stash-physical-source-manifest-v1` SHA, so the throughput comparison cannot silently compare different selected source media;
- the checkout is still the exact clean plan-bound throughput candidate branch/revision;
- the candidate branch still resolves to the same revision and `origin/main` is still the baseline revision frozen by the shared plan.

The launcher fails closed if any of those conditions drift.

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
5. requires both jobs to bind the exact same deterministic `stash-physical-source-manifest-v1` SHA before any machine comparison runs;
6. runs `compare-recovery-throughput.ps1` and requires machine A/B PASS for those exact job ids/revisions;
7. builds the immutable four-view review bundle;
8. rechecks checkout/ref stability and replays both persisted receipt validators; any job/receipt/source drift aborts publication;
9. publishes a create-only `bodyrig-throughput-plan-bound-review-continuation` receipt binding the candidate-run plan, both exact job JSON hashes, body revision identities, source-binding hashes, body-review hashes, shared source-manifest SHA, machine audit and review-bundle receipt hash.

Temporary output is removed on failure; incomplete evidence is not promoted to a final continuation directory.

## Human review

The launcher never records human review automatically. It prints the exact `record-recovery-throughput-human-review.ps1` command for the generated immutable bundle. Review all four canonical views and explicitly mark:

- identity shape;
- face identity;
- skin/texture alignment;
- gross anatomy.

A human PASS is evidence only. It remains non-promoting and non-activating until a separate explicit promotion decision exists.

## Authority boundary

This path is comparison-only. Persisted receipt validation and source-manifest parity prove evidence integrity/comparability only; they do not create a physical PASS. This path does not grant physical acceptance, promotion authority or production activation. It does not merge the throughput candidate and it does not reinterpret historical physical evidence.
