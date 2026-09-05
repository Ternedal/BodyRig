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

`bodyrig.high_fidelity_release_gate` re-proves final release invariants on the **final promoted bytes** rather than copying historical PASS booleans. It requires unchanged body identity/BodyPrint/source count, source-derived shape/motion authority, recovery and visual-identity provenance, exact `sith-smplx-vrm` revision `1` fitting provenance and final promoted VRM 1.0 validation.

Fresh Gate A then materializes the canonical recovery/package/runtime fields and checks expected by the core release gate.

## Reference-renderer authority

A command-contract audit found that high-fidelity's custom operator CLI was exposing raw low-level physical commands instead of the canonical BodyRig V1 reference-policy wrappers. That bypass is fixed.

Canonical high-fidelity physical progression uses:

1. `run-reference-windows-renderer-probe.ps1`;
2. `record-reference-renderer-acceptance.ps1`;
3. `run-reference-quest-renderer-probe.ps1`;
4. `complete-reference-acceptance.ps1`.

The inner `run-windows-renderer-probe.ps1`, `record-renderer-acceptance.ps1`, `run-quest-renderer-probe.ps1` and `complete-acceptance.ps1` remain implementation dependencies only.

The reference wrappers stage evidence outside the canonical directory, validate it against `reference-renderer/renderer-contract.json`, and only then commit canonical evidence or delegate to the core recorder/release gate.

`bodyrig.reference_acceptance_policy` is enforced inside the high-fidelity audited physical-status path. Legacy root evidence or renderer-contract drift fails closed before Windows, Quest or release progression is exposed.

Canonical V1 intentionally leaves already-complete historical releases readable. Fresh high-fidelity is stricter: `reference_policy_violation(...)` is re-run on every high-fidelity status read **including after an activating release**. A manually core-completed/legacy/non-reference release therefore cannot later surface as high-fidelity `PRODUCTION READY`.

## Transitive audit

`bodyrig.high_fidelity_physical_acceptance_audit` revalidates canonical reference policy, promoted package bytes, package-bound human review, source physical lineage, fresh QA/runtime hashes, handoff/Gate A bindings, source Gate A authority and final promoted BodyPrint/provenance/fitting/VRM lineage on every status read.

Any drift returns an invalid `physical-gate-a`, removes the next command and forces `production_activation=false`, including after an apparently complete release.

## Rig tooling

`high-fidelity-rig-preflight.ps1` requires Windows + PowerShell 7+, clean exact checkout, checkout-bound BodyRig Python 3.11+, canonical renderer readiness, the complete reference-wrapper chain, pinned Unity/UniVRM/package/toolchain authority and only the pinned Unity Android SDK `adb.exe`. It optionally binds a real Quest/Oculus serial and writes no acceptance evidence.

`reference-renderer/build-reference-renderer.ps1` independently fails closed before Unity launch on project-version, application-id, deformation-sequence or UniVRM pin drift.

`high-fidelity-physical-status.ps1` is the single recommended next-action source. It revalidates high-fidelity + reference policy, enforces checkout/revision authority, converts raw physical state into canonical reference-wrapper commands, injects pinned Unity SDK adb into the Quest reference command and carries optional Quest serial.

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

For multiple adb devices:

```powershell
$questSerial = '<serial>'
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected -Serial $questSerial
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview -Serial $questSerial
```

Once fresh Gate A is created, **freeze the checkout**: no pull, branch switch or tracked-file edit until the exact acceptance chain is complete or deliberately abandoned.

Do not hand-edit evidence JSON, delete create-only acceptance output to retry, use `accept-reconciled-physical-clone.ps1`, substitute PATH adb, bypass a printed reference wrapper with its inner core script, or treat CI/screenshots as physical PASS.

## Verification

- Reference-wrapper/policy integration: exact head `90bf045bf8bed1cc3fda8b867ad7d15eed578212`, `ci` #1680 **SUCCESS**, log regression #852 **SUCCESS**.
- Strict post-release reference-policy code: exact head `ed3bb6cd0329b26fc4771ed7bda02964b42e9fa7`, `ci` #1685 **SUCCESS**, log regression #857 **SUCCESS**.
- Documentation-complete head `a9f75749737a560aa9c97ccd7ec7421ee4cc2644`: `ci` #1686 **SUCCESS**, log regression #858 **SUCCESS**.
- Verification-note head `19454b9212766fdf26f3fde5d9cf2c6d8c088246`: `ci` #1687 **SUCCESS**, log regression #859 **SUCCESS**.
- Earlier final-release compatibility: PR #87 head `3c61f235e5a31ec2be6c52737565376ed5f94ad0`, `ci` #1653 **SUCCESS**, log regression #825 **SUCCESS**.

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
