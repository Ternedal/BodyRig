# BodyRig high-fidelity integration handoff

Updated: 2026-09-05.

## Authority and branch

- Canonical software trunk remains `main`; last verified trunk SHA is
  `438201ddf8131e3de646b5057006463b64eadc86` (PR #72).
- This checkout continues draft PR #83 on
  `agent/high-fidelity-integration-20260904`. It is the single high-fidelity
  integration candidate, not replacement trunk authority.
- PR #83 is stacked on PR #54, exact base
  `a33372de359a24b3daffae4649a06008d00179bd`, because its Person Studio flow
  depends on the unmerged anatomy/hair/eyes/face-secondary component chain.
- Temporary validation PR #84 was tested on exact head
  `fc307565d6dc15797d28eae27581aaf9b7a1ab59` and folded into #83 as merge
  commit `b7ecc2749fcd10a5b311cc7cc787eaa32ea54798`. PR #84 is not a parallel
  integration authority.
- Historical physical evidence keeps its recorded exact revision. Nothing in
  this continuation rebases, rewrites or relabels historical physical PASS.

## Software-complete continuation

The final component-complete promoted `.mrbody` now has a concrete, fail-closed
handoff into the existing canonical physical acceptance state machine.

- The promoted package SHA is verified before and after component audit and
  final package-bound human review.
- `prepare-high-fidelity-physical-acceptance.ps1` creates a **fresh Gate A** for
  the exact promoted package. It does not repoint old package/runtime authority
  at new bytes and does not rerun retained reconstruction merely to manufacture
  authority.
- Only the original hash-bound physical clone session and rig-readiness receipt
  are reused, and only as source-lineage evidence after their original Gate A is
  revalidated and body identity matches the final promoted package.
- Skin QA and mesh-topology QA are recomputed for the promoted package, runtime
  is freshly materialized, and the final package-bound high-fidelity human
  review is copied and revalidated against the accepted package copy.
- The new physical-acceptance directory is create-only and committed atomically
  from staging. Its fresh `bodyrig-acceptance.json` is validated by the existing
  canonical acceptance validator before it becomes visible.
- The handoff intentionally stops at the canonical Windows renderer probe with
  `production_activation=false`.

## Canonical downstream gates

After fresh Gate A, release readiness and Person Studio delegate to the existing
`bodyrig.acceptance_status` state machine rather than inventing a second physical
acceptance stack:

1. `physical_gate_a` — prepare the promoted package for physical acceptance.
2. `physical_windows_acceptance` — Windows renderer probe and human attestation.
3. `physical_quest_acceptance` — Quest probe and human attestation.
4. `final_release` — canonical final release for the exact accepted package.

`production_ready=true` and `production_activation=true` may surface **only**
when the canonical acceptance state is complete at gate `release`. Software
completion, component review, final human review, fresh Gate A, Windows-only PASS
or Quest-only PASS cannot activate production.

## Person Studio behaviour

- Software-ready status shows the actual next downstream gate and command.
- Blocked evidence stays fail-closed and cannot expose a runnable rerun command
  into an invalid existing create-only output.
- Selection changes clear stale status and delayed responses from a previous
  person are ignored.
- `PRODUCTION READY` is shown only when both canonical `production_ready` and
  `production_activation` are true after final release.

## Verification

- Temporary PR #84 exact head `fc307565d6dc15797d28eae27581aaf9b7a1ab59`:
  - `ci` run #1641: **SUCCESS** (Python 3.11, Python 3.12 and Windows acceptance job).
  - `windows-log-handle-regression` run #813: **SUCCESS**.
- The physical-handoff test suite covers fresh QA/runtime/Gate A materialization,
  atomic create-only commit, package/review staleness, canonical Windows/Quest/
  release state mapping and the rule that only canonical final release activates
  production.
- No target-rig CUDA/SiTH execution, actual final human visual review, WindowsPlayer
  physical acceptance or Quest physical acceptance was performed here. Automated
  CI is not target-device evidence.

## Next concrete operator work

For an exact final high-fidelity preview whose final package-bound human review
has passed:

```powershell
.\prepare-high-fidelity-physical-acceptance.ps1 -PreviewJobId '<preview-job-id>'
```

The command must leave the new acceptance state at the canonical Windows probe.
Then run the existing canonical Windows probe + human attestation, Quest probe +
human attestation, and final-release commands surfaced by the acceptance state
machine / Person Studio.

Do **not** mark those hardware/human gates PASS without their real evidence.
Until canonical final release is complete for the exact promoted package,
`production_ready=false` and `production_activation=false` remain mandatory.

## Remaining software hardening

The main software handoff gap is closed. A useful follow-up hardening is stronger
transitive status-read validation of the handoff receipt, Gate A extension,
fresh QA/runtime hashes and source Gate A lineage. This is defense-in-depth; it
must not weaken or bypass the canonical physical state machine.

Keep PR #83 draft until the integration candidate's updated head is green and
physical/operator acceptance is ready to be executed on the actual rig.
