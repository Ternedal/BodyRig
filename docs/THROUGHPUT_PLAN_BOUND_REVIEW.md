# Plan-bound recovery throughput A/B continuation

This flow is for the physical throughput candidate created by `start-throughput-candidate-from-ab-plan.ps1`.

It exists to prevent an operator mix-up between multiple succeeded candidate jobs. The candidate-start step publishes a create-only `bodyrig-throughput-candidate-run-plan` that binds the shared baseline plan, exact baseline job, exact throughput candidate revision/ref, Person and newly enqueued candidate job id. The review continuation must consume that exact receipt.

## Preconditions

- the shared exact-main baseline job has succeeded;
- the throughput candidate was started with `start-throughput-candidate-from-ab-plan.ps1`;
- that exact candidate job has succeeded;
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
4. runs `compare-recovery-throughput.ps1` and requires machine A/B PASS for those exact job ids/revisions;
5. builds the immutable four-view review bundle;
6. rechecks checkout/ref stability;
7. publishes a create-only `bodyrig-throughput-plan-bound-review-continuation` receipt binding the candidate-run plan, machine audit and review-bundle receipt hashes.

Temporary output is removed on failure; incomplete evidence is not promoted to a final continuation directory.

## Human review

The launcher never records human review automatically. It prints the exact `record-recovery-throughput-human-review.ps1` command for the generated immutable bundle. Review all four canonical views and explicitly mark:

- identity shape;
- face identity;
- skin/texture alignment;
- gross anatomy.

A human PASS is evidence only. It remains non-promoting and non-activating until a separate explicit promotion decision exists.

## Authority boundary

This path is comparison-only. It does not grant physical acceptance, promotion authority or production activation. It does not merge the throughput candidate and it does not reinterpret historical physical evidence.
