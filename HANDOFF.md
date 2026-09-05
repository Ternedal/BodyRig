# BodyRig high-fidelity integration handoff

Updated: 2026-09-05.

## Authority

- Canonical trunk remains `main`; this work is **not** merged there.
- Draft PR #83 / `agent/high-fidelity-integration-20260904` is the single high-fidelity integration candidate.
- PR #83 remains stacked on `agent/person-studio-photoreal-20260902`, exact base `a33372de359a24b3daffae4649a06008d00179bd`.
- Historical physical evidence retains its original exact revision. Nothing here rebinds old Gate A/package/runtime PASS to promoted bytes.
- `production_activation=false` remains mandatory until the exact fresh physical chain reaches canonical final release.

## Integrated chain

Stash/SiTH physical source → anatomy → hair → eyes/iris → face-secondary → exact package-bound final human review → fresh promoted-package Gate A → reference-wrapped Windows acceptance → reference-wrapped Quest acceptance → reference-wrapped final release.

Fresh promoted-package Gate A:

- revalidates original physical Gate A and canonical body identity;
- reuses only hash-bound physical session/readiness as source lineage;
- copies exact final promoted `.mrbody` plus exact package-bound human-review receipt;
- hash-binds that copied review into the handoff/Gate A authority;
- recomputes skin QA and mesh-topology QA;
- freshly materializes runtime from the promoted package;
- is create-only and atomically committed;
- stops at Windows probe with `production_activation=false`.

## Human-review authority boundary

The package-bound human review is a hard gate **before** fresh Gate A.

Before Gate A:

- the live package-side review receipt is review authority;
- writer and reader reject generated `<...>` quality-note placeholders;
- `.venv\Scripts\python.exe` is preferred, with checkout `PYTHONPATH` and exact `bodyrig.__file__` binding;
- invalid/stale/tampered create-only review can use the narrow preserving recovery gate only while the exact package remains high-fidelity-ready.

The pre-Gate-A recovery path:

`high_fidelity_human_review_recovery` → `archive-invalid-high-fidelity-human-review.ps1`

- preserves exact invalid bytes as `.invalid-<receipt-sha256>.json`;
- refuses valid receipts and conflicting archive bytes;
- never changes package bytes or creates PASS;
- remains `production_activation=false`;
- is bound to the exact `PreviewJobId` and package SHA.

**Fresh Gate A is the authority switch.** Once canonical `physical-acceptance/` exists, the copied/hash-bound review inside that acceptance directory is the only human-review authority for the physical chain. The live source-side review receipt must no longer reopen review or recovery.

Post-Gate-A rules:

- readiness does not read the live source review as current authority;
- the frozen review is revalidated through the transitive Gate A audit;
- source-side review deletion/tamper cannot produce a new review or recovery command;
- invalid frozen review/Gate A authority blocks the chain and exposes no recovery;
- a recovery command printed before Gate A carries `PreviewJobId`, and both its PowerShell wrapper and Python CLI refuse execution if Gate A now exists.

This closes the status→execution race where a previously printed pre-Gate-A recovery command could otherwise outlive the authority switch.

Do not manually delete, overwrite or recreate review evidence after Gate A.

## Reference-renderer authority

Canonical physical progression uses only:

1. `run-reference-windows-renderer-probe.ps1`;
2. `record-reference-renderer-acceptance.ps1`;
3. `run-reference-quest-renderer-probe.ps1`;
4. `complete-reference-acceptance.ps1`.

Inner probe/attestation/release scripts remain implementation dependencies. Reference wrappers stage/revalidate evidence before canonical commit. `bodyrig.reference_acceptance_policy` is enforced by high-fidelity audited status before and after release.

Windows and Quest core probes independently require current HEAD == exact Gate A revision plus a clean checkout before evidence can be committed. Canonical final release binds all physical evidence to that same revision/package/runtime.

Quest adb authority is fail-closed in both the reference wrapper and core Quest probe: neither defaults to PATH `adb`; both derive the permitted `adb.exe` from `reference-renderer/renderer-contract.json` → pinned Unity editor → AndroidPlayer SDK; an explicit `-AdbExe` must resolve to that exact executable. The core Quest probe now also directs successful runs to `record-reference-renderer-acceptance.ps1`, never the low-level attestation writer.

Renderer human-note authority is fail-closed at write, final-write and strict readback boundaries: `record-renderer-acceptance.ps1` rejects a trimmed pure `<...>` placeholder before evidence creation; `complete-acceptance.ps1` independently rejects placeholder quality notes before any release with `production_activation=true` can be written; and the strict `reference_policy_violation()` readback rejects missing or placeholder human notes even after an activating release artifact exists. Strict high-fidelity readback also requires explicit `attestation="operator-supplied"` provenance. Generic V1 reference-policy behavior remains compatible, while high-fidelity audited status calls the strict helper before and after release. `person_release_status` retains its own hard provenance error contract, so stale/synthetic renderer PASS evidence cannot surface as trusted human authority.

## Checkout / runtime authority

Before Gate A, preflight/status/direct Gate-A preparation require a clean checkout containing minimum-safe handoff revision:

`ed3bb6cd0329b26fc4771ed7bda02964b42e9fa7`

as an ancestor. After Gate A, the minimum floor no longer substitutes for authority: exact Gate A revision freeze is mandatory.

Preflight, package review, review recovery, status and Gate-A preparation use checkout-bound Python. Preflight validates canonical reference tooling, Unity/UniVRM pins and only the pinned Unity Android SDK `adb.exe`; optional Quest serial is carried into the canonical Quest command.

## Transitive audit

`bodyrig.high_fidelity_physical_acceptance_audit` revalidates reference policy, promoted package bytes, frozen package-bound review, source physical lineage, fresh QA/runtime hashes, Gate A/handoff bindings and final promoted release lineage on every physical status read.

Any drift blocks progression, removes the next physical command and forces `production_activation=false`, including after an apparently complete release.

## Operator loop

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

Run exactly one printed next command, perform any required real human review, then rerun status.

If status offers `high_fidelity_human_review_recovery`, it is necessarily pre-Gate-A. Run only the exact printed command; the command is itself Gate-A-aware and will fail closed if the authority switch happened after status was printed.

Once fresh Gate A exists, **freeze the checkout**: no pull, branch switch or tracked-file edit until the acceptance chain completes or is deliberately abandoned.

Never hand-edit evidence JSON, delete create-only acceptance output to retry, use `accept-reconciled-physical-clone.ps1`, substitute PATH adb, bypass reference wrappers, or treat CI/screenshots as physical PASS.

## Verification

Current authority code head before this documentation commit:

- `50ad00dee8bc90d18f248e53b2aa4ee1ac3e3032`: `ci` #1759 **SUCCESS**, `windows-log-handle-regression` #931 **SUCCESS**.
  - Python 3.11: SUCCESS.
  - Python 3.12: SUCCESS.
  - PowerShell parsing/contracts: SUCCESS.
  - managed physical wrapper: SUCCESS.
  - Windows final-acceptance job: SUCCESS.

Final documentation head:

- `00bd6e2c1c53bd29bd018d18f39e549a2973c8c5`: `ci` #1760 **SUCCESS**, `windows-log-handle-regression` #932 **SUCCESS**.

Relevant earlier green heads:

- strict renderer human-note readback `e611741eac29a30b28a42e7a07fd179f619466ce`: `ci` #1754 / log #926 SUCCESS;
- renderer human-note write/final-read hardening `7b16b7b21b289a415c7dcff279bab5f7621099dd`: `ci` #1751 / log #923 SUCCESS;
- canonical Quest operator handoff `69e028dcbd23527df0a3d9700458c9ccd7dc6ead`: `ci` #1747 / log #919 SUCCESS;
- Quest adb authority `3d010727687356e69a8104290cfa6f109a689fc8`: `ci` #1743 / log #915 SUCCESS;
- Gate-A frozen-review authority `3aa388b10dbf2a4776163c032a75f52d87fa5c52`: `ci` #1739 / log #911 SUCCESS;
- recovery/operator hardening `f8d9731a333670f2b76f8c4f53c4211d8dcc85d9`: `ci` #1728 / log #900 SUCCESS;
- package-review placeholder/runtime hardening `ed23055c4b0ad2b4602262d8969e2a3296bbdd42`: `ci` #1714 / log #886 SUCCESS;
- renderer-attestation placeholder rejection `307fb7767d42c71123306731539f344b44984aaf`: `ci` #1711 / log #883 SUCCESS;
- canonical post-Gate-A status routing `0a4e99cc7ecd7475936a7d34d8c61955b0ca5f61`: `ci` #1709 / log #881 SUCCESS;
- Gate-A Python parity `d9eb8d54cafa4596613c6c3b1a06ea35ed5d2ff1`: `ci` #1706 / log #878 SUCCESS;
- pre-Gate-A ancestry floor `440bef06fb9bb6efca8b0daf8b6eb025cb381031`: `ci` #1704 / log #876 SUCCESS;
- strict post-release reference policy `ed3bb6cd0329b26fc4771ed7bda02964b42e9fa7`: `ci` #1685 / log #857 SUCCESS.

Automated CI is **not** target-device evidence. No final package human PASS, WindowsPlayer physical PASS, Quest physical PASS or production activation was produced by CI.

## Remaining real work

There is no currently known software-only acceptance blocker. Remaining authority is deliberately physical/manual:

1. rig preflight;
2. choose intended persisted high-fidelity preview;
3. pre-Gate-A review recovery only if status explicitly offers it;
4. perform final package-bound human review if required;
5. create fresh promoted-package Gate A;
6. run real reference-wrapped Windows probe + human attestation;
7. run real reference-wrapped Quest probe + headset attestation;
8. run `complete-reference-acceptance.ps1`;
9. require final status `production_ready=true` and `production_activation=true`.

Keep PR #83 draft. Do not merge to `main` merely because software CI is green.
