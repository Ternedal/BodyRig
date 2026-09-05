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

The final component-complete promoted `.mrbody` has a concrete, fail-closed
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
- Fresh Gate A intentionally stops at the Windows renderer probe with
  `production_activation=false`.

## Final-release compatibility is re-proved on promoted bytes

The fresh high-fidelity Gate A is compatible with the existing core
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
fields used by the core release gate, including:

- `bodyrig_checkout_clean`;
- `preflight_ok`;
- `recovery_adapter_pinned`;
- `observed_frames_ge_2`;
- source-derived shape/motion checks;
- BodyPrint/source-count/recovery-provenance checks;
- fitting and VRM 1.0 checks;
- `runtime_materialized_from_package`;
- canonical `recovery` and package release metadata.

The handoff receipt and Gate A extension bind the source/final BodyPrint lineage
hashes and record `releaseLineageReproved=true`. A mismatch fails closed before
Windows evidence can start.

## Canonical reference-renderer policy is part of high-fidelity authority

A later command-contract audit found an important integration gap: the raw
physical state machine intentionally emits low-level implementation commands,
while canonical BodyRig V1 operator authority is added by
`bodyrig.acceptance_status_cli` through the reference-renderer policy wrappers.
The high-fidelity operator CLI had duplicated command rendering and was therefore
bypassing that canonical outer policy layer.

That gap is now closed. High-fidelity physical progression uses the same four
reference wrappers as canonical V1:

1. `run-reference-windows-renderer-probe.ps1`;
2. `record-reference-renderer-acceptance.ps1`;
3. `run-reference-quest-renderer-probe.ps1`;
4. `complete-reference-acceptance.ps1`.

The low-level scripts remain implementation dependencies only:

- `run-windows-renderer-probe.ps1`;
- `record-renderer-acceptance.ps1`;
- `run-quest-renderer-probe.ps1`;
- `complete-acceptance.ps1`.

The reference probe wrappers stage low-level evidence into unique non-canonical
directories, revalidate the machine/deformation pair against
`reference-renderer/renderer-contract.json`, and only then atomically commit the
canonical `windows-evidence/` or `quest-evidence/` bundle. The reference human
attestation wrapper revalidates the exact evidence pair and renderer contract,
requires the structured quality checklist, supplies the contracted renderer
identity to the core recorder, and rechecks checkout authority after the write.
The reference release wrapper revalidates renderer contract, dedicated evidence
layout and structured human quality review before delegating to the core release
gate.

`bodyrig.reference_acceptance_policy.apply_reference_policy` is also applied
inside the high-fidelity audited physical-status path, not only at the UI/CLI
edge. Legacy root renderer evidence or renderer-contract drift therefore fails
closed before high-fidelity readiness may expose Windows, Quest or final-release
progress. High-fidelity is a stricter facade over canonical V1 authority, not a
parallel acceptance policy.

## Transitive authority hardening

Release-readiness does not trust only a valid-looking downstream Gate A.
`bodyrig.high_fidelity_physical_acceptance_audit` wraps the existing physical
status machine and revalidates the complete high-fidelity handoff authority on
**every status read** before Windows, Quest or release state is exposed:

- canonical reference-renderer policy and dedicated evidence layout;
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
next command and forces `production_activation=false`. This includes reference
contract/layout drift and later tamper after an apparently complete release. The
underlying generic state machine may inspect historical/low-level evidence, but
canonical high-fidelity progression cannot bypass the reference policy wrappers.

## Canonical downstream gates

1. `high_fidelity_human_review` — explicit review of the exact final package.
2. `physical_gate_a` — fresh QA/runtime/release-lineage proof/Gate A for that
   exact package.
3. `physical_windows_acceptance` — reference-wrapped WindowsPlayer
   machine/deformation evidence plus explicit human visual attestation.
4. `physical_quest_acceptance` — reference-wrapped evidence for the same exact
   runtime on Quest-class hardware plus explicit headset attestation.
5. `final_release` — reference-policy release wrapper over the complete exact
   evidence chain.

`production_ready=true` and `production_activation=true` may surface **only**
when the canonical state is complete at `release`, reference policy still
validates, and the transitive high-fidelity handoff audit still validates.

## Rig operator tooling

- `high-fidelity-rig-preflight.ps1`
  - requires Windows and PowerShell 7+;
  - proves a clean exact Git checkout and checkout-bound BodyRig Python 3.11+;
  - delegates renderer authority to `check-reference-renderer-ready.ps1`;
  - cross-validates renderer contract, Unity `ProjectVersion.txt`, canonical
    package pins, UniVRM revision and Unity Android SDK/NDK/OpenJDK;
  - requires the complete reference-wrapper chain plus its core implementation
    dependencies;
  - uses the **pinned Unity Android SDK `adb.exe`** for device discovery rather
    than an arbitrary PATH adb;
  - optionally requires an actual Quest/Oculus adb device with
    `-RequireQuestConnected` and can bind an explicit `-Serial`;
  - creates/modifies **no acceptance evidence**.
- `list-high-fidelity-previews.ps1 -SucceededOnly`
  - read-only discovery of persisted `hfpreview-...` jobs, newest first;
  - does not import the preview manager and therefore does not reconcile or
    mutate old jobs merely by listing them.
- `high-fidelity-physical-status.ps1 -PreviewJobId <id>`
  - is the single recommended source for the next operator action;
  - revalidates package/review/handoff/release-lineage and reference policy;
  - requires a clean checkout;
  - once fresh Gate A exists, requires the checkout to remain on that exact
    accepted revision;
  - translates raw low-level physical commands onto canonical reference
    wrappers and absolutizes the selected wrapper path;
  - for the Quest reference probe, injects the pinned Unity Android SDK
    `adb.exe` automatically and carries an optional `-Serial` through to the
    generated command;
  - never requires the operator to invent renderer name/version because the
    reference attestation wrapper owns that contract authority.
- `reference-renderer/build-reference-renderer.ps1`
  - independently fails closed before Unity launch if ProjectVersion,
    application id, deformation-sequence contract or UniVRM package authority
    drifts, so bypassing preflight cannot silently build a different renderer.
- `HIGH-FIDELITY-PHYSICAL-RUNBOOK.md`
  - documents the complete reference-wrapper one-gate-at-a-time physical
    session, pinned adb / serial flow and checkout freeze after fresh Gate A.

## Rig entry point

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

Both `git status --short` outputs must be empty and preflight must report PASS.
Then choose the intended persisted job and ask the status tool for exactly one
next action:

```powershell
$preview = 'hfpreview-0123456789abcdef0123456789abcdef'
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview
```

Run the printed next command, perform any explicitly required human review, and
then rerun the same status command. Repeat until it either fails closed or
reports `PRODUCTION READY`.

Before the Quest gate, connect the headset and run:

```powershell
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected
```

If several adb devices are online, bind the intended Quest to both preflight and
status so the generated reference Quest command remains deterministic:

```powershell
$questSerial = '<serial>'
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected -Serial $questSerial
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview -Serial $questSerial
```

Do not replace the printed reference-wrapper command with its low-level inner
script. The complete procedure is in `HIGH-FIDELITY-PHYSICAL-RUNBOOK.md`.

## Checkout freeze after fresh Gate A

Once `prepare-high-fidelity-physical-acceptance.ps1` succeeds, **do not pull,
switch branch, edit tracked files or otherwise change the BodyRig checkout**
until that exact acceptance chain is complete or deliberately abandoned.
Windows, Quest and final-release evidence are bound to the Gate A revision.

Do not hand-edit evidence JSON, delete a create-only acceptance directory just
to retry, use `accept-reconciled-physical-clone.ps1` for this flow, substitute a
PATH adb for the pinned Unity Android SDK adb, bypass a reference wrapper with a
low-level/core acceptance script, or treat CI/component screenshots as physical
PASS.

## Verification boundary

Automated coverage now includes:

- atomic fresh Gate A creation and package/review staleness;
- final-release canonical field/check alignment;
- final promoted BodyPrint/source-count/recovery/visual/fitting/VRM re-proof;
- rejection of BodyPrint, visual-provenance and fitter drift;
- canonical Windows/Quest/release state mapping;
- reference-wrapper command routing for Windows, Quest, attestation and release;
- reference-policy revocation inside the high-fidelity physical audit;
- rejection of missing canonical reference operator dependencies;
- production activation only after canonical final release;
- transitive receipt ↔ Gate A ↔ QA/runtime ↔ source-lineage tamper detection;
- release-lineage revalidation on subsequent status reads;
- post-release tamper revocation;
- clean/matching operator checkout enforcement;
- canonical renderer readiness delegation and project/package pin validation;
- pinned Unity adb + optional Quest serial command generation through the
  reference Quest wrapper;
- direct renderer-build project/contract drift rejection;
- read-only preview discovery;
- runbook/preflight safety contracts and PowerShell parsing.

The reference-policy/wrapper integration fix was validated on exact #83 head
`90bf045bf8bed1cc3fda8b867ad7d15eed578212`:

- `ci` #1680: **SUCCESS** — Python 3.11, Python 3.12, managed physical wrapper
  and Windows final-acceptance job.
- `windows-log-handle-regression` #852: **SUCCESS**.

The immediately preceding exact head `d7e4d6638a370d575bb209b4dc229d1b8d4afba4`
was also fully green in `ci` #1672 and `windows-log-handle-regression` #844.

PR #87 exact head `3c61f235e5a31ec2be6c52737565376ed5f94ad0`
was independently green in `ci` #1653 and `windows-log-handle-regression` #825
before fold-back.

Automated CI is **not** target-device evidence. No actual final human visual
review, WindowsPlayer physical acceptance or Quest physical acceptance was
performed in this environment.

## Remaining real work

After the reference-policy integration correction, there is no known
software-only acceptance gap left in this path. The remaining authority is
physical/manual:

1. run rig preflight and identify the intended persisted high-fidelity preview;
2. complete final package-bound high-fidelity human review if status still
   requires it;
3. create fresh promoted-package Gate A (including final-release lineage re-proof);
4. run the real **reference-wrapped** WindowsPlayer probe and human attestation;
5. run the real **reference-wrapped** Quest probe and headset attestation;
6. complete `complete-reference-acceptance.ps1`;
7. require final status to report both `production_ready=true` and
   `production_activation=true`.

Keep PR #83 draft. Do not merge it to `main` merely because software CI is green;
the remaining physical/human evidence must stay honest and exact-input bound.
