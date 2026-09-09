# PBR → throughput sequencing gate

This gate makes the existing shared #196/#208 operator order enforceable instead of advisory.

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

## Throughput human review

After the candidate succeeds, continue through the existing plan-bound continuation and use its canonical human-review command:

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
