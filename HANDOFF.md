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

The branch now carries the complete software continuation:

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

`bodyrig.high_fidelity_release_gate` re-proves final release invariants on the **final promoted bytes** rather than copying historical PASS booleans. It requires:

- unchanged body identity and BodyPrint;
- unchanged source count;
- source-derived shape and motion authority;
- recovery provenance matching the revalidated source Gate A;
- preserved visual-identity provenance;
- exact `sith-smplx-vrm` revision `1` fitting provenance;
- final promoted VRM 1.0 validation.

Fresh Gate A then materializes the canonical recovery/package/runtime fields and checks expected by the core release gate.

## Reference-renderer authority

A command-contract audit found that high-fidelity's custom operator CLI was exposing the raw low-level physical commands instead of the canonical BodyRig V1 reference-policy wrappers. That bypass is fixed.

Canonical high-fidelity physical progression now uses:

1. `run-reference-windows-renderer-probe.ps1`;
2. `record-reference-renderer-acceptance.ps1`;
3. `run-reference-quest-renderer-probe.ps1`;
4. `complete-reference-acceptance.ps1`.

The inner scripts remain implementation dependencies only:

- `run-windows-renderer-probe.ps1`;
- `record-renderer-acceptance.ps1`;
- `run-quest-renderer-probe.ps1`;
- `complete-acceptance.ps1`.

The reference wrappers stage evidence outside the canonical directory, validate it against `reference-renderer/renderer-contract.json`, and only then commit canonical evidence or delegate to the core recorder/release gate.

`bodyrig.reference_acceptance_policy` is enforced inside the high-fidelity audited physical-status path, not merely at the CLI edge. Legacy root evidence or renderer-contract drift therefore fails closed before Windows, Quest or release progression is exposed.

Canonical V1 intentionally leaves already-complete historical releases readable. Fresh high-fidelity is stricter: `reference_policy_violation(...)` is re-run on every high-fidelity status read **including after an activating release**. A manually core-completed/legacy/non-reference release therefore cannot later surface as high-fidelity `PRODUCTION READY`.

## Transitive audit

`bodyrig.high_fidelity_physical_acceptance_audit` revalidates on every status read:

- canonical reference-renderer policy and dedicated evidence layout;
- exact promoted package bytes;
- exact package-bound final human review;
- source physical session/readiness lineage;
- fresh skin/topology QA hashes;
- fresh runtime-manifest hash;
- handoff receipt ↔ Gate A extension hashes;
- preview/body/source Gate A identity and revision;
- release-compatible Gate A fields;
- promoted BodyPrint/provenance/fitting/VRM lineage.

Any drift returns an invalid `physical-gate-a`, removes the next command and forces `production_activation=false`, including after an apparently complete release.

## Rig tooling

`high-fidelity-rig-preflight.ps1` now:

- requires Windows + PowerShell 7+;
- requires a clean exact Git checkout;
- proves BodyRig Python 3.11+ imports from that checkout;
- delegates renderer readiness to `check-reference-renderer-ready.ps1`;
- cross-validates renderer contract, Unity `ProjectVersion.txt`, UniVRM/package pins and Unity Android SDK/NDK/OpenJDK;
- requires the full canonical reference-wrapper chain and its core dependencies;
- uses only the pinned Unity Android SDK `adb.exe`, never arbitrary PATH adb;
- optionally requires a real Quest/Oculus device and explicit serial;
- creates no acceptance evidence.

`reference-renderer/build-reference-renderer.ps1` independently fails closed before Unity launch on project-version, application-id, deformation-sequence or UniVRM pin drift.

`high-fidelity-physical-status.ps1` is the single recommended next-action source. It:

- revalidates high-fidelity + reference policy;
- enforces clean checkout and exact Gate A revision after Gate A exists;
- converts raw physical state into canonical reference-wrapper commands;
- absolutizes the wrapper path;
- injects pinned Unity SDK adb into the Quest reference command;
- carries optional Quest serial;
- never asks the operator to invent renderer identity.

## Rig entry

Before fresh Gate A:

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

Both `git status --short` outputs must be empty and preflight must PASS.

Then:

```powershell
$preview = 'hfpreview-0123456789abcdef0123456789abcdef'
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview
```

Run exactly one printed next command, perform any required real human review, then run status again.

For multiple adb devices:

```powershell
$questSerial = '<serial>'
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected -Serial $questSerial
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview -Serial $questSerial
```

Once fresh Gate A is created, **freeze the checkout**: no pull, branch switch or tracked-file edit until the exact acceptance chain is complete or deliberately abandoned.

Do not hand-edit evidence JSON, delete create-only acceptance output to retry, use `accept-reconciled-physical-clone.ps1` for this path, substitute PATH adb, bypass a printed reference wrapper with its inner core script, or treat CI/screenshots as physical PASS.

## Verification

Reference-wrapper/policy integration was green on exact head `90bf045bf8bed1cc3fda8b867ad7d15eed578212`:

- `ci` #1680: **SUCCESS**;
- `windows-log-handle-regression` #852: **SUCCESS**.

Strict post-release reference-policy revalidation was then added and validated on exact code head `ed3bb6cd0329b26fc4771ed7bda02964b42e9fa7`:

- `ci` #1685: **SUCCESS** — Python 3.11, Python 3.12, managed physical wrapper and Windows final-acceptance job;
- `windows-log-handle-regression` #857: **SUCCESS**.

Earlier final-release compatibility was independently green on PR #87 exact head `3c61f235e5a31ec2be6c52737565376ed5f94ad0` (`ci` #1653 and log regression #825).

This HANDOFF refresh is documentation-only after `ed3bb6cd...`; the final #83 head must still receive exact-head CI before the branch is called software-ready for the rig.

Automated CI is **not** target-device evidence. No actual final package human PASS, WindowsPlayer physical PASS, Quest physical PASS or production activation was produced here.

## Remaining real work

There is no known software-only acceptance gap after the reference-wrapper and strict post-release policy corrections. Remaining authority is deliberately physical/manual:

1. rig preflight;
2. choose the intended persisted high-fidelity preview;
3. final package-bound human review if required;
4. fresh promoted-package Gate A;
5. real reference-wrapped Windows probe + human attestation;
6. real reference-wrapped Quest probe + headset attestation;
7. `complete-reference-acceptance.ps1`;
8. final status must report both `production_ready=true` and `production_activation=true`.

Keep PR #83 draft. Do not merge to `main` merely because software CI is green.
