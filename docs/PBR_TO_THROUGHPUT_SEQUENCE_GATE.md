# PBR → throughput sequencing gate

This gate makes the existing shared #258/#208 operator order enforceable instead of advisory.

## Canonical transition

Start from the exact clean `main` revision bound by the shared baseline plan. The shared baseline must already have succeeded and the plan-bound PBR A/B run must already have an explicit human review recorded through `record-pbr-ab-human-review-from-plan.ps1`.

Then use only the canonical launcher:

```powershell
.\start-throughput-candidate-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>'
```

The launcher discovers the single reviewed canonical PBR run for that baseline. If more than one reviewed PBR run exists, bind the exact run explicitly:

```powershell
.\start-throughput-candidate-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -PbrRunDir '<exact-pbr-run-dir>'
```

Before any throughput checkout switch or candidate enqueue, the wrapper uses the checkout-bound `bodyrig.pbr_human_review_gate` validator to revalidate:

- the exact create-only shared baseline plan and candidate byte-contract;
- the exact PBR run directory under the canonical local BodyRig PBR root;
- `run-authority.json`;
- `body-job-source-authority.json`;
- `body-job-plan-authority.json`;
- `machine-ab.json`;
- `human-review.json`;
- `plan-bound-human-review-authority.json`;
- the exact main/PBR/throughput revisions and refs recorded by that authority;
- `human_visual_authority_recorded=true` while physical acceptance, promotion and production activation remain false.

The established throughput launch logic remains byte-identical in `start-throughput-candidate-from-ab-plan-internal.ps1`. The canonical wrapper invokes it only after the PBR human-review gate passes. After enqueue it replays the PBR authority. Drift cancels the candidate job and removes candidate-run authority when present.

A successful canonical launch writes a create-only receipt:

```text
%LOCALAPPDATA%\BodyRig\ab-baseline-plans\<baseline>-throughput-<candidate>-pbr-gate.json
```

with format `bodyrig-throughput-pbr-human-review-gate`. The receipt binds the exact candidate-run-plan bytes to the exact PBR human-review authority/review bytes and the stable PBR evidence fingerprint.

## Throughput continuation

After the exact candidate succeeds, remain on the exact clean plan-bound throughput candidate checkout and run:

```powershell
.\continue-throughput-review-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>'
```

The continuation is itself sequencing-gated. Before persisted body-job receipt replay or any throughput machine A/B/bundle generation it requires the exact create-only `bodyrig-throughput-pbr-human-review-gate` receipt for that baseline/candidate pair and replays the checkout-bound `bodyrig.pbr_human_review_gate` validator against the exact PBR run recorded by the receipt.

The continuation rejects any mismatch in shared-plan bytes, candidate-run-plan bytes, candidate contract, Person, baseline/candidate identity, revisions, refs, PBR human-review authority bytes, human-review bytes, decision or stable PBR evidence fingerprint. After machine evidence and bundle generation it replays the same PBR sequencing authority again. Drift prevents `continuation-authority.json` publication.

A successful continuation authority binds:

- `pbr_to_throughput_sequence_verified=true`;
- the exact PBR-to-throughput gate-receipt SHA-256;
- the exact PBR human-review authority and human-review SHA-256 values;
- the stable PBR evidence fingerprint;
- the PBR decision;
- the existing exact source/job/revision/machine/bundle lineage.

This does not mean that throughput human review has occurred. The continuation remains `comparison_only=true`, keeps `human_visual_authority_required=true`, and grants no physical acceptance, promotion or production activation.

## Throughput human review

After the candidate succeeds and the sequencing-gated continuation has produced its review bundle, use its canonical human-review command:

```powershell
.\record-throughput-human-review-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>' `
  -RunDir '<plan-bound-run-dir>' `
  -IdentityShape pass|fail `
  -FaceIdentity pass|fail `
  -SkinTextureAlignment pass|fail `
  -GrossAnatomy pass|fail `
  -Note '<actual human assessment>' `
  -ConfirmVisualReview
```

The canonical wrapper requires the PBR-to-throughput gate receipt and replays the PBR authority before and after the existing throughput plan-bound human-review recorder. The established recorder remains byte-identical as `record-throughput-human-review-from-ab-plan-internal.ps1` and produces the intermediate plan-bound authority.

The canonical wrapper then publishes a separate create-only terminal receipt:

```text
<plan-bound-run-dir>.pbr-sequenced-human-review-authority.json
```

with format `bodyrig-throughput-pbr-sequenced-human-review-authority`. It binds both human-review stages without changing their evidence meaning.

## Authority boundary

This sequencing gate does **not** prove photorealism, physical acceptance or throughput benefit. It only proves that the throughput candidate/review belongs to a shared plan whose PBR human review was actually recorded first.

All gate receipts remain comparison evidence:

- `physical_acceptance_authority=false`
- `promotion_authority=false`
- `production_activation=false`

The `*-internal.ps1` scripts are implementation details and must not be used as canonical operator entrypoints.
