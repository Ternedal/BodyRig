# BodyRig handoff

_Last updated: 2026-09-04_

## Repository state

BodyRig is in a trunk-normalization window.

- GitHub default branch: `main`.
- `main` is not yet the code trunk; before this normalization it contained only the repository bootstrap/README history.
- Proposed foundation branch: `agent/bodyrig-main-foundation-20260904`.
- Foundation code base: `agent/donor-lbs-policy-hotfix-20260903` at `b7799d5a172e08ccf8d1759b7f988d99604abd76`.
- Do **not** start another long branch stack from the old branch graph while the foundation PR is open.
- Do **not** infer current authority from branch age, PR number, or the Git author name.

After the foundation PR lands, `main` becomes the only normal integration trunk. New work should branch from exact current `main` unless a documented frozen physical-evidence exception explicitly requires another base.

## Important recovery from the old graph

`agent/bodyrig-v1` is historically divergent from the current code line. Two commits on that branch looked stranded:

- `7087563235db2648710b3256dd435189259d1092` — `fix: resolve remote Stash VR paths over SMB`
- `670a179df75cbd80459d00bcaf0e612605ca405a` — `test: lock remote Stash VR share resolution`

Their **content is already preserved** in the foundation code line. The foundation contains the remote `X:\\VR` → same-host `VR_X` fail-closed mapping logic in `bodyrig/stash_cli.py` and `tests/test_stash_remote_vr_share.py`. Do not cherry-pick those historical commits merely to reproduce commit ancestry.

## Active development lines to reconcile after foundation landing

These are the currently relevant open lines, not independent trunks:

- PR #54 / `agent/person-studio-photoreal-20260902` — source-grounded photoreal Person Studio continuation.
- PR #65 / `agent/person-studio-hair-deformation-review-20260904` — exact physical hair deformation review authority, stacked on #54; draft/unmerged.
- PR #60 / `agent/recovery-throughput-v3-20260903` — recovery throughput v3 performance candidate; requires real A/B evidence before authority.
- PR #61 / `agent/person-studio-diagnostics-20260903` — diagnostics-only Person Studio improvements.
- PR #62 / `agent/bodyrig-ui-late-fit-resume` — explicit late-fit resume from retained reconstruction.
- PR #63 / `agent/gate-a-appearance-resume-20260903` — Gate A anatomy-aware appearance/resume fix.
- PR #64 / `agent/bodyrig-post-clone-continuation` — post-clone continuation checkpoint, stacked on #62.

Older physical/fidelity PRs remain evidence/history until each is explicitly classified as landed, superseded, or still required. Do not bulk-close them without a commit/PR pointer proving where their surviving content went.

## Authority rules

1. **Software trunk authority**
   - After foundation landing: exact clean `main` SHA.
   - Before foundation landing: use the exact SHA named by the specific active/frozen workflow; do not treat PR #1's moving branch head as a universal pointer.

2. **Physical evidence authority**
   - Existing physical evidence remains bound to the exact revision recorded in that evidence.
   - Rebasing or landing code does not retroactively rewrite physical evidence authority.
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

Hair deformation review is implemented as review authority only; hair materialization/promotion is not yet part of the foundation. Eye authority is still blocked by explicit iris identity/appearance authority and remaining face-secondary work.

## Normalization sequence

1. Land the foundation PR to `main` through CI/review.
2. Make `main` the documented integration authority and remove the PR #1 authority-pointer pattern from operator docs.
3. Reconcile active PRs against `main`, preserving only their real deltas.
4. Compare recovery-throughput v2/v3 unique content before closing old performance candidates.
5. Classify old PRs explicitly as `LANDED`, `SUPERSEDED`, `FROZEN EVIDENCE`, or `ACTIVE` with a pointer.
6. Resume new feature work only after the active branch graph is shallow and understandable.

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
