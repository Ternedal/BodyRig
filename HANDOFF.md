# BodyRig high-fidelity integration handoff

Updated: 2026-09-05.

## Authority

- Canonical trunk remains `main`; this work is **not** merged there.
- Draft PR #83 / `agent/high-fidelity-integration-20260904` is the single high-fidelity integration candidate.
- PR #83 remains stacked on `agent/person-studio-photoreal-20260902`, exact base `a33372de359a24b3daffae4649a06008d00179bd`.
- Temporary PRs #84, #85, #86 and #87 were validation/fold-back branches only, not parallel authorities.
- Historical physical evidence retains its original exact revision. Nothing here rebinds old Gate A/package/runtime PASS to promoted bytes.
- `production_activation=false` remains mandatory until the exact fresh physical chain reaches canonical final release.

## Integrated high-fidelity chain

The branch carries the complete software continuation:

Stash/SiTH physical source → anatomy → hair → eyes/iris → face-secondary → exact package-bound final human review → fresh promoted-package Gate A → reference-wrapped Windows acceptance → reference-wrapped Quest acceptance → reference-wrapped final release.

Fresh promoted-package Gate A:

- revalidates the original physical Gate A and canonical body identity;
- reuses only hash-bound physical session/readiness as source lineage;
- copies the exact final promoted `.mrbody` and package-bound human review;
- recomputes skin QA and mesh-topology QA;
- freshly materializes runtime from the promoted package;
- is create-only and atomically committed;
- stops at Windows probe with `production_activation=false`.

## Final-release compatibility

`bodyrig.high_fidelity_release_gate` re-proves final release invariants on the **final promoted bytes** rather than copying historical PASS booleans. It requires unchanged body identity/BodyPrint/source count, source-derived shape/motion authority, recovery and visual-identity provenance, exact `sith-smplx-vrm` revision `1` fitting provenance and final promoted VRM 1.0 validation.

Fresh Gate A then materializes the canonical recovery/package/runtime fields and checks expected by the core release gate.

## Reference-renderer authority

Canonical high-fidelity physical progression uses:

1. `run-reference-windows-renderer-probe.ps1`;
2. `record-reference-renderer-acceptance.ps1`;
3. `run-reference-quest-renderer-probe.ps1`;
4. `complete-reference-acceptance.ps1`.

The inner `run-windows-renderer-probe.ps1`, `record-renderer-acceptance.ps1`, `run-quest-renderer-probe.ps1` and `complete-acceptance.ps1` remain implementation dependencies only.

The reference wrappers stage evidence outside the canonical directory, validate it against `reference-renderer/renderer-contract.json`, and only then commit canonical evidence or delegate to the core recorder/release gate.

`bodyrig.reference_acceptance_policy` is enforced inside the high-fidelity audited physical-status path. Legacy root evidence or renderer-contract drift fails closed before Windows, Quest or release progression is exposed, including after an apparently complete release.

Windows and Quest core probes independently re-read Gate A and require current HEAD to equal the exact Gate A revision plus a clean checkout before physical evidence can be committed. The core final release gate also independently requires current HEAD == Gate A revision and binds all physical evidence to that same revision/package/runtime.

## Human-review authority and recovery

The exact package-bound human review is itself a hard gate before fresh Gate A.

Current safeguards:

- `record-high-fidelity-human-review.ps1` uses `.venv\Scripts\python.exe` first, PATH only as fallback, checkout `PYTHONPATH`, and exact `bodyrig.__file__` authority;
- both the PowerShell wrapper and canonical Python writer/reader reject untouched generated `<...>` quality-note placeholders;
- the status-generated quality-note placeholder is quoted as a literal but must be replaced with a real operator observation before PASS;
- the review remains package-SHA + component-state bound and independently non-activating.

Create-only review receipts are not silently overwritten. If an existing receipt is stale/tampered/placeholder-invalid while the exact promoted package still passes the current high-fidelity package audit, status exposes one narrow recovery gate:

`high_fidelity_human_review_recovery` → `archive-invalid-high-fidelity-human-review.ps1`

That recovery path:

- refuses a valid review receipt;
- requires the current package to remain high-fidelity-ready;
- rechecks exact continuation package SHA before exposing the command;
- preserves the exact invalid receipt bytes under a content-addressed `.invalid-<receipt-sha256>.json` archive;
- refuses conflicting archive bytes;
- never mutates package bytes or creates human PASS;
- keeps `production_activation=false`;
- returns control to the normal status loop, which must then require a fresh explicit human review.

Do not manually delete or overwrite a human-review sidecar.

## Pre-Gate-A and Python authority

Before fresh Gate A, `high-fidelity-rig-preflight.ps1`, `high-fidelity-physical-status.ps1` and direct Gate-A preparation require a clean checkout containing minimum-safe physical-handoff revision:

`ed3bb6cd0329b26fc4771ed7bda02964b42e9fa7`

as an ancestor. This rejects stale clean checkouts while allowing later safe descendants.

After Gate A exists, that minimum floor does **not** substitute for authority: the exact Gate A revision freeze is mandatory.

Preflight, package review, status and Gate-A preparation use the same validated Python selection/import authority. Preflight also requires both the normal human-review wrapper and invalid-review recovery wrapper to exist before the rig session starts.

## Transitive audit

`bodyrig.high_fidelity_physical_acceptance_audit` revalidates canonical reference policy, promoted package bytes, package-bound human review, source physical lineage, fresh QA/runtime hashes, handoff/Gate A bindings, source Gate A authority and final promoted BodyPrint/provenance/fitting/VRM lineage on every status read.

Any drift returns an invalid physical state, removes the next physical command and forces `production_activation=false`, including after an apparently complete release.

## Rig tooling

`high-fidelity-rig-preflight.ps1` requires Windows + PowerShell 7+, clean checkout, minimum-safe handoff ancestry, checkout-bound BodyRig Python 3.11+, canonical human-review/recovery tooling, canonical renderer readiness, the complete reference-wrapper chain, pinned Unity/UniVRM/package/toolchain authority and only the pinned Unity Android SDK `adb.exe`. It optionally binds a real Quest/Oculus serial and writes no acceptance evidence.

`reference-renderer/build-reference-renderer.ps1` independently fails closed before Unity launch on project-version, application-id, deformation-sequence or UniVRM pin drift.

`high-fidelity-physical-status.ps1` is the single recommended next-action source. It revalidates high-fidelity + reference policy, enforces checkout/revision authority, routes invalid human review through the preserving recovery gate when safe, converts raw physical state into canonical reference-wrapper commands, injects pinned Unity SDK adb into the Quest reference command and carries optional Quest serial.

## Rig entry

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
git status --short
git fetch origin
git switch agent/high-fidelity-integration-20260904
git pull --ff-only origin agent/high-fidelity-integration-20260904
git status --short
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1
pwsh -NoProfile -File .\list-high-fidelity-previews.ps1 -SucceededOnly
$preview = 'hfpreview-0123456789abcdef0123456789abcdef'
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview
```

Run exactly one printed next command, perform any required real human review, then run status again.

If status exposes `high_fidelity_human_review_recovery`, run only its printed archive command, rerun status, and then perform the newly-required explicit review. The archive action itself is not PASS authority.

For multiple adb devices:

```powershell
$questSerial = '<serial>'
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected -Serial $questSerial
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview -Serial $questSerial
```

Once fresh Gate A is created, **freeze the checkout**: no pull, branch switch or tracked-file edit until the exact acceptance chain is complete or deliberately abandoned.

Do not hand-edit evidence JSON, manually delete/overwrite package human-review receipts, delete create-only acceptance output to retry, use `accept-reconciled-physical-clone.ps1`, substitute PATH adb, bypass a printed reference wrapper with its inner core script, or treat CI/screenshots as physical PASS.

## Verification

Latest recovery/operator hardening code head before this documentation-only update:

- `f8d9731a333670f2b76f8c4f53c4211d8dcc85d9`: `ci` #1728 **SUCCESS**, `windows-log-handle-regression` #900 **SUCCESS**.

Recent independently green authority heads:

- package-review placeholder/runtime hardening `ed23055c4b0ad2b4602262d8969e2a3296bbdd42`: `ci` #1714 **SUCCESS**, log #886 **SUCCESS**;
- renderer-attestation placeholder rejection `307fb7767d42c71123306731539f344b44984aaf`: `ci` #1711 **SUCCESS**, log #883 **SUCCESS**;
- canonical post-Gate-A status-loop routing `0a4e99cc7ecd7475936a7d34d8c61955b0ca5f61`: `ci` #1709 **SUCCESS**, log #881 **SUCCESS**;
- Gate-A Python runtime parity `d9eb8d54cafa4596613c6c3b1a06ea35ed5d2ff1`: `ci` #1706 **SUCCESS**, log #878 **SUCCESS**;
- pre-Gate-A minimum ancestry floor `440bef06fb9bb6efca8b0daf8b6eb025cb381031`: `ci` #1704 **SUCCESS**, log #876 **SUCCESS**;
- strict post-release reference-policy code `ed3bb6cd0329b26fc4771ed7bda02964b42e9fa7`: `ci` #1685 **SUCCESS**, log #857 **SUCCESS**;
- earlier final-release compatibility PR #87 head `3c61f235e5a31ec2be6c52737565376ed5f94ad0`: `ci` #1653 **SUCCESS**, log #825 **SUCCESS**.

Automated CI is **not** target-device evidence. No actual final package human PASS, WindowsPlayer physical PASS, Quest physical PASS or production activation was produced here.

## Remaining real work

There is no currently known software-only acceptance gap. Remaining authority is deliberately physical/manual:

1. rig preflight;
2. choose the intended persisted high-fidelity preview;
3. recover invalid package review only if status explicitly offers that gate;
4. perform final package-bound human review if required;
5. fresh promoted-package Gate A;
6. real reference-wrapped Windows probe + human attestation;
7. real reference-wrapped Quest probe + headset attestation;
8. `complete-reference-acceptance.ps1`;
9. final status must report both `production_ready=true` and `production_activation=true`.

Keep PR #83 draft. Do not merge to `main` merely because software CI is green.
