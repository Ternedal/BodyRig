# BodyRig handoff

_Last updated: 2026-09-04_

## Repository state

BodyRig now has a real canonical software trunk.

- GitHub default/integration branch: `main`.
- Foundation PR #66 landed successfully.
- Foundation merge on `main`: `e4b032107a3bdaa8a57ba5d02462f9c32ff934f7`.
- PR #66 exact pre-merge head `eb25334d071e345e4e9514ff606117c188badfb3` passed `ci` #1566 and `windows-log-handle-regression` #738.
- Normal new work must branch from exact current `main` unless a documented frozen physical-evidence procedure explicitly requires another SHA.
- Do **not** infer current authority from branch age, PR number, or Git author name.
- PR #1 is closed and is no longer an authority pointer.

`main` is software integration authority. Historical physical evidence remains bound to the exact BodyRig revision recorded in that evidence; trunk normalization does not rewrite it.

## Old graph reconciliation already completed

The two commits that looked stranded on `agent/bodyrig-v1` were:

- `7087563235db2648710b3256dd435189259d1092` — `fix: resolve remote Stash VR paths over SMB`
- `670a179df75cbd80459d00bcaf0e612605ca405a` — `test: lock remote Stash VR share resolution`

Their surviving content is already present on `main`, including the fail-closed remote `X:\\VR` → same-host `VR_X` mapping and `tests/test_stash_remote_vr_share.py`. They were deliberately not cherry-picked merely to duplicate ancestry.

The following old stacked integration PRs have been verified with `ahead_by=0` against current `main` and closed as `LANDED`:

- PR #40 — fitted SMPL-X final body topology.
- PR #41 — anatomy-aware canonical SMPL-X appearance path.
- PR #51 — explicit high-fidelity component gates.
- PR #53 — observed embodiment / Motor State v2 lineage.

PR #1 has been closed as `SUPERSEDED` for repository/software authority. Its historical exact-SHA evidence remains historical evidence only.

## Active development lines

These are active deltas, not independent trunks:

- PR #54 / `agent/person-studio-photoreal-20260902` — source-grounded photoreal Person Studio continuation; retargeted directly to `main`.
- PR #65 / `agent/person-studio-hair-deformation-review-20260904` — exact physical hair deformation review authority; remains correctly stacked on #54 and is draft/unmerged.
- PR #60 / `agent/recovery-throughput-v3-20260903` — recovery throughput v3 performance candidate; retargeted directly to `main`; requires real A/B evidence before authority.
- PR #61 / `agent/person-studio-diagnostics-20260903` — diagnostics-only Person Studio improvements; retargeted directly to `main`.
- PR #62 / `agent/bodyrig-ui-late-fit-resume` — explicit late-fit resume from retained reconstruction; retargeted directly to `main`.
- PR #63 / `agent/gate-a-appearance-resume-20260903` — Gate A anatomy-aware appearance/resume fix; retargeted directly to `main`.
- PR #64 / `agent/bodyrig-post-clone-continuation` — post-clone continuation checkpoint; remains correctly stacked on #62.

Known real deltas after trunk normalization:

- #54: 108 commits over the foundation lineage before branch reconciliation.
- #60: 13 commits.
- #61: 4 commits.
- #62: 12 commits.
- #63: 20 commits.
- #64: 3 commits over #62 in its intended stack.
- #65: 8 commits over #54 in its intended stack.

The branch heads retain their historical exact-head CI/evidence identity. Do not force-rebase them merely to make the graph pretty; reconcile deliberately and preserve physical evidence semantics.

## Old PRs that still contain unique content

Do not close these merely because they are old. Current compare against `main` still shows unique commits/content:

- PR #49 — 39 unique commits: physical A/B evidence/handoff/review toolchain.
- PR #43 — 4 unique commits: reconstruction-authority binding in fidelity checkpoints.
- PR #42 — 4 unique commits: interrupted-fit recovery ladder hardening.
- PR #39 — 14 unique commits: topology diagnostics and bounded repair.
- PR #21 — 2 unique commits: profiled fidelity-to-renderer-ready operator path.
- PR #19 — 2 unique commits: cumulative renderer-bundle Gate A rebind helper.

Each must be explicitly classified as `ACTIVE`, `FROZEN EVIDENCE`, `SUPERSEDED`, or deliberately ported before closure.

## Authority rules

1. **Software trunk authority**
   - Exact clean current `main` SHA.
   - A feature/fix PR is an integration candidate, not global software authority merely because its CI is green.

2. **Physical evidence authority**
   - Existing physical evidence remains bound to the exact revision recorded in that evidence.
   - Rebasing, retargeting, closing a PR, or landing code does not retroactively rewrite physical evidence authority.
   - New physical runs require an exact clean checkout and the current documented operator path.

3. **High-fidelity / production authority**
   - CI can validate software/trust contracts but cannot substitute for real CUDA/SiTH execution, human visual review, Windows deformation review, Quest review, or final release gates.
   - `production_activation=true` may only arise from the canonical final release path.

4. **SiTH setup**
   - New canonical physical runs require strict nested `bodyrig-sith-setup` v4 evidence. Older v1/v2/v3 setup evidence is not sufficient for a new run.

## Current physical/product blockers

The remaining product gate is still physical, not a unit-test problem:

1. real Stash-bound subject with decodable local source;
2. source-derived reconstruction/retained anatomy on the target rig;
3. valid high-fidelity `.mrbody` / component continuation;
4. explicit component review and promotion boundaries;
5. Windows render/deformation acceptance;
6. Quest-class acceptance on the exact accepted runtime/package;
7. final release gate.

Hair deformation review is implemented as review authority only. Hair materialization/promotion is not yet landed. The safe promotion design must reconstruct and verify the exact hair-only intermediate rather than copy the combined hair+eye review VRM. Eye authority is still blocked by explicit iris identity/appearance authority and remaining face-secondary work.

## Normalization sequence from here

1. Remove the obsolete PR #1 authority-pointer wording from operator documentation.
2. Reconcile active PRs against `main` while preserving only their real deltas and exact evidence semantics.
3. Compare recovery-throughput v2/v3 unique content before closing old performance candidates.
4. Classify the remaining old unique-content PRs explicitly.
5. Resume new feature work once the active graph is shallow and understandable.

Coordination issue: #67 `BodyRig trunk normalization and PR reconciliation`.

## Handoff discipline

Every meaningful BodyRig PR should state:

- exact base SHA;
- exact head SHA after validation;
- scope and non-scope;
- authority/activation boundary;
- automated validation performed;
- physical validation still required;
- whether it supersedes or stacks on another PR.

Update this file when the canonical trunk, active integration head, physical authority, or next hard blocker changes.
