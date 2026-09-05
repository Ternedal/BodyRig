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
- Temporary validation PRs #84, #85 and #86 were used only to obtain exact-head
  CI before folding their changes into #83. They are not parallel integration
  authorities.
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
- source physical session/readiness bytes.

Any drift fails closed back to an invalid `physical-gate-a`, removes a runnable
next command and forces `production_activation=false`. This also means a later
tamper can no longer remain surfaced as production-ready merely because a final
release receipt exists. The underlying Windows → Quest → release authority is
still `bodyrig.acceptance_status`; the audit layer can revoke visibility, never
invent PASS.

## Canonical downstream gates

1. `high_fidelity_human_review` — explicit review of the exact final package.
2. `physical_gate_a` — fresh QA/runtime/Gate A for that exact package.
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
  - revalidates package/review/handoff/physical state;
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
- canonical Windows/Quest/release state mapping;
- production activation only after canonical final release;
- transitive receipt ↔ Gate A ↔ QA/runtime ↔ source-lineage tamper detection;
- post-release tamper revocation;
- clean/matching operator checkout enforcement;
- renderer-attestation command completion from exact probe identity;
- read-only preview discovery;
- runbook/preflight safety contracts and PowerShell parsing.

Exact current-head CI belongs on PR #83 after this handoff commit. Automated CI
is **not** target-device evidence. No actual final human visual review,
WindowsPlayer physical acceptance or Quest physical acceptance was performed in
this environment.

## Remaining real work

There is no known software-only acceptance gap left in this path. The remaining
authority is deliberately physical/manual:

1. run rig preflight and identify the intended persisted high-fidelity preview;
2. complete final package-bound high-fidelity human review if status still
   requires it;
3. create fresh promoted-package Gate A;
4. run real WindowsPlayer probe and human attestation;
5. run real Quest probe and headset attestation;
6. complete canonical final release;
7. require the final status to report both `production_ready=true` and
   `production_activation=true`.

Keep PR #83 draft. Do not merge it to `main` merely because software CI is green;
the remaining physical/human evidence must stay honest and exact-input bound.
