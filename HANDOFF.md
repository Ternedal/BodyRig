# BodyRig high-fidelity integration handoff

Updated: 2026-09-05.

## Authority and branch

- Canonical software trunk remains `main`; last verified trunk SHA is
  `438201ddf8131e3de646b5057006463b64eadc86` (PR #72).
- Draft PR #83 on `agent/high-fidelity-integration-20260904` is the single
  high-fidelity integration candidate. It is **not** replacement trunk
  authority and must remain draft until the physical/release policy is
  deliberately completed.
- PR #83 is stacked on PR #54, exact base
  `a33372de359a24b3daffae4649a06008d00179bd`, because the integrated Person
  Studio path depends on the unmerged anatomy/hair/eyes/face-secondary chain.
- Temporary validation PRs #84, #85, #86 and #87 were used only to obtain
  exact-head CI before folding their changes into #83. They are not parallel
  integration authorities.
- PR #87 was validated on exact head
  `3c61f235e5a31ec2be6c52737565376ed5f94ad0` before fold-back: `ci` #1653
  and `windows-log-handle-regression` #825 both completed SUCCESS.
- Historical physical evidence keeps its recorded exact revision. Nothing in
  this continuation rebases, rewrites or relabels historical physical PASS.

## Software-complete promoted-package handoff

The final component-complete promoted `.mrbody` now has a concrete, fail-closed
handoff into the existing canonical physical acceptance state machine.

- The promoted package SHA is verified around component audit and final
  package-bound high-fidelity human review.
- `prepare-high-fidelity-physical-acceptance.ps1` creates a **fresh Gate A** for
  the exact promoted package. It never points old package/runtime authority at
  promoted bytes and does not rerun retained reconstruction merely to create
  authority.
- Only the original hash-bound physical clone session and rig-readiness receipt
  are reused, and only as source-lineage evidence after the original Gate A is
  revalidated and body identity matches the final package.
- Skin QA and mesh-topology QA are recomputed, runtime is freshly materialized,
  and the final package-bound human-review receipt is copied and revalidated
  against the accepted package copy.
- The new physical-acceptance directory is create-only and atomically committed
  from staging. Its fresh `bodyrig-acceptance.json` must validate through the
  existing canonical acceptance validator before becoming visible.
- Fresh Gate A intentionally stops at the canonical Windows renderer probe with
  `production_activation=false`.

## Final-release compatibility is re-proved on promoted bytes

The fresh high-fidelity Gate A is now compatible with the existing canonical
`complete-acceptance.ps1` contract without copying release PASS flags from the
historical Gate A.

`bodyrig.high_fidelity_release_gate` re-proves the final promoted package against
the already-revalidated physical source Gate A before fresh Gate A is written:

- canonical body identity is unchanged;
- BodyPrint is semantically unchanged from the physical source package;
- source count is unchanged;
- source-derived shape and motion fields are still present;
- `body-recovery` provenance still matches the source recovery authority;
- the exact `visual-identity-capture` provenance is preserved;
- `avatar-fitting` is still exactly `sith-smplx-vrm` revision `1`;
- the final promoted avatar independently validates as VRM 1.0;
- source recovery/preflight facts are inherited only from a source Gate A that
  has itself passed canonical revalidation.

Only after those checks pass does fresh Gate A materialize the canonical release
fields used by `complete-acceptance.ps1`, including:

- `bodyrig_checkout_clean`;
- `preflight_ok`;
- `recovery_adapter_pinned`;
- `observed_frames_ge_2`;
- source-derived shape/motion checks;
- BodyPrint/source-count/recovery-provenance checks;
- fitting and VRM 1.0 checks;
- `runtime_materialized_from_package`;
- canonical `recovery` and package release metadata.

The handoff receipt and Gate A extension also bind the source/final BodyPrint
lineage hashes and record `releaseLineageReproved=true`. A mismatch fails closed
before Windows evidence can start.

## Transitive authority hardening

Release-readiness no longer trusts only a valid-looking downstream Gate A.
`bodyrig.high_fidelity_physical_acceptance_audit` wraps the existing physical
status machine and revalidates the complete high-fidelity handoff authority on
**every status read** before Windows, Quest or release state is exposed:

- exact promoted package copy;
- exact package-bound high-fidelity human-review receipt;
- copied physical session/readiness lineage;
- fresh skin QA and mesh-topology QA hashes;
- fresh runtime-manifest hash;
- Gate A's high-fidelity extension and exact handoff-receipt SHA;
- persisted source body-job / preview identity;
- source Gate A revision, package hash and exact Gate A bytes;
- source physical session/readiness bytes;
- the final-release-compatible Gate A field set;
- a fresh re-run of promoted-package BodyPrint/provenance/fitting/VRM lineage.

Any drift fails closed back to an invalid `physical-gate-a`, removes a runnable
next command and forces `production_activation=false`. This also means a later
tamper can no longer remain surfaced as production-ready merely because a final
release receipt exists. The underlying Windows → Quest → release authority is
still `bodyrig.acceptance_status`; the audit layer can revoke visibility, never
invent PASS.

## Canonical downstream gates

1. `high_fidelity_human_review` — explicit review of the exact final package.
2. `physical_gate_a` — fresh QA/runtime/release-lineage proof/Gate A for that
   exact package.
3. `physical_windows_acceptance` — built WindowsPlayer machine/deformation
   evidence plus explicit human visual attestation.
4. `physical_quest_acceptance` — the same exact runtime on Quest-class hardware
   plus explicit headset attestation.
5. `final_release` — canonical release receipt for the complete exact evidence
   chain.

`production_ready=true` and `production_activation=true` may surface **only**
when the canonical state is complete at `release` and the transitive handoff
audit still validates.

## Rig operator tooling now included

The integration branch contains a deliberately read-only/operator-safe front end
for the physical session:

- `high-fidelity-rig-preflight.ps1`
  - requires Windows and PowerShell 7+;
  - proves a clean exact Git checkout and checkout-bound BodyRig Python 3.11+;
  - verifies the pinned reference-renderer contract;
  - verifies Unity `6000.3.13f1`, UniVRM `0.131.2`, Unity Android Build Support
    and `adb` availability;
  - optionally requires an actual Quest/Oculus adb device with
    `-RequireQuestConnected`;
  - creates/modifies **no acceptance evidence**.
- `list-high-fidelity-previews.ps1 -SucceededOnly`
  - read-only discovery of persisted `hfpreview-...` jobs, newest first;
  - does not import the preview manager and therefore does not reconcile or
    mutate old jobs merely by listing them.
- `high-fidelity-physical-status.ps1 -PreviewJobId <id>`
  - is the single recommended source for the next operator action;
  - revalidates package/review/handoff/physical/release-lineage state;
  - requires a clean checkout;
  - once fresh Gate A exists, requires the checkout to remain on that exact
    accepted revision;
  - absolutizes the next operator script path;
  - for Windows/Quest human attestation, inserts the mandatory
    `-ConfirmQualityChecklist` and reads the exact renderer name/version from
    the committed machine probe instead of asking the operator to guess it.
- `HIGH-FIDELITY-PHYSICAL-RUNBOOK.md`
  - documents the complete one-gate-at-a-time physical session and the checkout
    freeze rule after fresh Gate A.

## Afternoon entry point

Before fresh Gate A exists, synchronize #83 and make sure the checkout is clean:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
git status --short
git fetch origin
git switch agent/high-fidelity-integration-20260904
git pull --ff-only origin agent/high-fidelity-integration-20260904
git status --short
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1
pwsh -NoProfile -File .\list-high-fidelity-previews.ps1 -SucceededOnly
```

Both `git status --short` outputs must be empty and the preflight must report
PASS. Then choose the intended persisted job and ask the status tool for exactly
one next action:

```powershell
$preview = 'hfpreview-0123456789abcdef0123456789abcdef'
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview
```

Run the printed next command, perform any explicitly required human review, and
then rerun the same status command. Repeat until it either fails closed or reports
`PRODUCTION READY`.

Before the Quest gate, connect the headset and run:

```powershell
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected
```

If several adb devices are online, use `-Serial '<serial>'` for the intended
Quest. The complete safety/detail procedure is in
`HIGH-FIDELITY-PHYSICAL-RUNBOOK.md`.

## Checkout freeze after fresh Gate A

Once `prepare-high-fidelity-physical-acceptance.ps1` succeeds, **do not pull,
switch branch, edit tracked files or otherwise change the BodyRig checkout**
until that exact acceptance chain is complete or deliberately abandoned.
Windows, Quest and final-release evidence are bound to the Gate A revision.

Do not hand-edit evidence JSON, delete a create-only acceptance directory just
to retry, use `accept-reconciled-physical-clone.ps1` for this flow, or treat CI /
component screenshots as physical PASS.

## Verification boundary

The folded software has automated coverage for:

- atomic fresh Gate A creation and package/review staleness;
- final-release canonical field/check alignment;
- final promoted BodyPrint/source-count/recovery/visual/fitting/VRM re-proof;
- rejection of BodyPrint, visual-provenance and fitter drift;
- canonical Windows/Quest/release state mapping;
- production activation only after canonical final release;
- transitive receipt ↔ Gate A ↔ QA/runtime ↔ source-lineage tamper detection;
- release-lineage revalidation on subsequent status reads;
- post-release tamper revocation;
- clean/matching operator checkout enforcement;
- renderer-attestation command completion from exact probe identity;
- read-only preview discovery;
- runbook/preflight safety contracts and PowerShell parsing.

PR #87 exact head `3c61f235e5a31ec2be6c52737565376ed5f94ad0`
was green in `ci` #1653 (Python 3.11, Python 3.12 and Windows acceptance) and
`windows-log-handle-regression` #825 before fold-back. The final #83 head must
also be green before the rig session is treated as software-ready.

Automated CI is **not** target-device evidence. No actual final human visual
review, WindowsPlayer physical acceptance or Quest physical acceptance was
performed in this environment.

## Remaining real work

There is no known software-only acceptance gap left in this path. The remaining
authority is deliberately physical/manual:

1. run rig preflight and identify the intended persisted high-fidelity preview;
2. complete final package-bound high-fidelity human review if status still
   requires it;
3. create fresh promoted-package Gate A (including final-release lineage re-proof);
4. run real WindowsPlayer probe and human attestation;
5. run real Quest probe and headset attestation;
6. complete canonical final release;
7. require the final status to report both `production_ready=true` and
   `production_activation=true`.

Keep PR #83 draft. Do not merge it to `main` merely because software CI is green;
the remaining physical/human evidence must stay honest and exact-input bound.