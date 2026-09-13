# BodyRig high-fidelity physical acceptance runbook

Updated: 2026-09-13.

This is the operator path from a persisted high-fidelity continuation to canonical production release. It deliberately does **not** manufacture human or hardware evidence. Run exactly one gate at a time and re-read status after every gate.

For a **new** physical acceptance session, canonical software authority is the exact clean current `main` revision. The minimum safe fresh physical handoff includes the mandatory source-grounded hands/feet/nails (HFN) continuation and persisted-authority hardening. Historical physical evidence remains bound to the exact revision recorded in that evidence.

## 0. Synchronize and preflight the operator checkout

Do this **before** a fresh promoted-package Gate A exists:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
git status --short
git fetch origin
git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1
```

Both `git status --short` calls must be empty. The revision printed by `git rev-parse HEAD` is the software revision that a new Gate A may bind if the later status/preparation checks still accept it. The preflight must end in `PASS` before creating Gate A. It verifies the exact clean checkout, the HFN-safe minimum handoff ancestry and checkout-bound Python, then delegates renderer authority to the canonical `check-reference-renderer-ready.ps1` checker. That checker cross-validates the renderer contract against Unity `ProjectVersion.txt`, the complete pinned package manifest, UniVRM revision, Unity Android SDK/NDK/OpenJDK and the pinned Unity-SDK `adb.exe`. The high-fidelity preflight uses that same pinned `adb.exe` for device discovery; an arbitrary `adb` from `PATH` is not physical authority.

Preflight also requires the complete HFN continuation, package-review/recovery and canonical reference-wrapper chain to be present:

- `prepare-hands-feet-nails-source-capture.ps1`;
- `prepare-hands-feet-nails-landmark-evidence.ps1`;
- `prepare-hands-feet-nails-uv-domain-evidence.ps1`;
- `prepare-hands-feet-nails-detail-candidate.ps1`;
- `prepare-hands-feet-nails-render-review.ps1`;
- `record-high-fidelity-hfn-review.ps1`;
- `record-high-fidelity-human-review.ps1`;
- `archive-invalid-high-fidelity-human-review.ps1`;
- `run-reference-windows-renderer-probe.ps1`;
- `record-reference-renderer-acceptance.ps1`;
- `run-reference-quest-renderer-probe.ps1`;
- `complete-reference-acceptance.ps1`.

The lower-level `run-windows-renderer-probe.ps1`, `record-renderer-acceptance.ps1`, `run-quest-renderer-probe.ps1` and `complete-acceptance.ps1` remain implementation dependencies. Do not call them directly in the high-fidelity physical session unless you are deliberately diagnosing the low-level implementation outside canonical release authority.

A Quest does not have to be connected for this first preflight. If you want to prove the headset/ADB path before starting the acceptance chain, connect the Quest and run:

```powershell
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected
```

If several adb devices are online, select the intended headset explicitly and keep its serial for the later status command:

```powershell
$questSerial = '<serial>'
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected -Serial $questSerial
```

**Freeze rule:** once `prepare-high-fidelity-physical-acceptance.ps1` has created the fresh Gate A, do not pull, switch branches, edit tracked files, or otherwise change the BodyRig checkout until that acceptance chain is complete or deliberately abandoned. Windows, Quest and final release evidence are exact-revision bound.

## 1. Find the persisted high-fidelity preview id

```powershell
pwsh -NoProfile -File .\list-high-fidelity-previews.ps1 -SucceededOnly
```

Pick the intended `hfpreview-...` row by person/body revision and keep it in a variable:

```powershell
$preview = 'hfpreview-0123456789abcdef0123456789abcdef'
```

The listing is read-only. It does not reconcile, rerun or mutate preview jobs.

## 2. Use one status command as the source of the next operator action

```powershell
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview
```

Run this again **after every successful command below**. Before any fresh Gate A can be created, status requires the promoted high-fidelity component chain to pass through the source-grounded HFN detail-bearing candidate, canonical four-view HFN render and package-bound HFN human review. It then validates the exact current package, package-wide review, transitive handoff authority, fresh Gate A/QA/runtime hashes, source Gate A lineage, canonical reference-renderer policy, physical evidence and the clean operator checkout before it exposes an executable next command.

The status layer receives raw physical state from the low-level state machine, but it never exposes those low-level physical commands directly. It rewrites physical progression onto the same canonical reference wrappers used by BodyRig V1 and blocks if `reference_acceptance_policy` rejects legacy layout or renderer-contract drift.

If you selected an explicit Quest serial, carry it on the status command. It is ignored for non-Quest actions and inserted only when the Quest reference probe is the next gate:

```powershell
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview -Serial $questSerial
```

For machine-readable troubleshooting:

```powershell
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview -Json
```

If status is `BLOCKED` with no recovery command, stop. Do not delete/recreate evidence or skip the gate. Preserve the output and logs for diagnosis.

## 3. Possible next gates

### `hfn_detail_candidate`

This is the first mandatory HFN gate after face-secondary promotion. The exact face-secondary promoted package remains the source package until a source-grounded HFN detail-bearing candidate has been materialized. Status will print a command based on:

```powershell
.\prepare-hands-feet-nails-detail-candidate.ps1 -Root '<person-library>' -PersonId '<person-id>' -BodyRevision '<body-revision>' -CaptureId <CAPTURE_ID> -UvEvidence <UV_EVIDENCE_PATH> -PackagePath '<exact-face-secondary-package>'
```

Select only exact source capture / landmark / UV evidence for the same Person, body revision, package and BodyRig revision. If usable source detail is unavailable, this gate must remain unresolved; do not invent identity-specific nail or hand/foot detail. The candidate application is bounded to exact HFN UV/skin domains, preserves protected anatomy/rig fingerprints, requires a clean appearance-only A/B and remains `production_activation=false`.

After candidate creation, rerun status. From this point onward, the HFN detail-bearing `.mrbody` bytes are the continuation package that later review and physical handoff must bind.

### `hfn_render_review`

Once the detail-bearing candidate exists, status will require the canonical four-view HFN render from those exact candidate bytes and expose a command equivalent to:

```powershell
.\prepare-hands-feet-nails-render-review.ps1 -PackagePath '<exact-hfn-candidate>' -OutputDir '<continuation-hfn-render-dir>'
```

The render authority is comparison-only and must contain exactly the canonical `left_hand`, `right_hand`, `left_foot`, `right_foot` 1024x1024 views bound to the exact body id, candidate package SHA-256 and BodyRig revision. It does not grant human or physical PASS and cannot activate production.

Rerun status after the render completes.

### `hfn_human_review`

Review the exact HFN candidate against all four canonical renders and the source closeups. The package-bound M2 checklist covers hand/finger geometry, foot/toe geometry, skin detail, fingernails, toenails and left/right source/render consistency. Use only the command emitted by status; it routes through:

```powershell
.\record-high-fidelity-hfn-review.ps1 ... -ConfirmDetailChecklist -QualityNote <QUALITY_NOTE>
```

Replace `<QUALITY_NOTE>` with a real observation. Every canonical M2 checklist item must pass. This review is source-grounded and package-bound but still review-only: `package_application_authority=false` for the human receipt and `production_activation=false`.

Only after `hfn_detail_candidate`, `hfn_render_review` and `hfn_human_review` all pass does continuation re-audit the exact HFN candidate package and allow the broader package-wide high-fidelity review path to proceed.

### `high_fidelity_human_review_recovery`

This gate appears only when the exact promoted HFN-reviewed package is still high-fidelity-ready but an existing create-only package-wide human-review sidecar is present and the current canonical `read_review()` rejects it (for example because it is stale, tampered or still contains a generated placeholder).

Do **not** delete or edit that sidecar. Run only the exact recovery command printed by status. It will route through:

```powershell
.\archive-invalid-high-fidelity-human-review.ps1 -PackagePath '<exact-promoted-package>'
```

Recovery first re-proves the current package audit, proves that the current receipt is invalid, hashes the exact invalid receipt bytes, and preserves them under a content-addressed `.invalid-<receipt-sha256>.json` archive. A valid receipt cannot be archived by this path, conflicting archive bytes fail closed, package bytes are not changed, and `production_activation` remains false.

After recovery completes, rerun status. The expected next state is ordinary `high_fidelity_human_review` for the same exact package bytes. Recovery is not a human PASS and does not create or infer review authority.

### `high_fidelity_human_review`

Review the exact HFN-reviewed promoted package evidence in Person Studio. The package-wide review must cover source identity, anatomy, skin, hair, eyes/iris, face-secondary, hands/feet/nails, full-body multiview and face close-up. Then use the exact command printed by the status tool and replace only the quality-note placeholder with what you actually reviewed.

This gate is package-bound and non-activating. A generated `<...>` quality-note placeholder is rejected by both the PowerShell wrapper and the canonical Python review writer/reader.

### `physical_gate_a`

Run the printed command. It will be equivalent to:

```powershell
.\prepare-high-fidelity-physical-acceptance.ps1 -PreviewJobId $preview
```

The command creates a new acceptance directory atomically from the exact HFN-reviewed promoted package, reuses only hash-bound physical session/readiness as source lineage, recomputes skin/topology QA, materializes a fresh runtime and stops at Windows probe. It does not reuse old package/runtime authority. Before fresh Gate A can be created, both the status CLI and preparation wrapper require the HFN-safe minimum physical-handoff revision to be an ancestor of the current clean checkout.

**The checkout freeze starts here.**

### `physical_windows_acceptance` — machine probe

The printed command must route through:

```powershell
.\run-reference-windows-renderer-probe.ps1 -AcceptanceDir '<acceptance-dir>'
```

The reference wrapper stages the low-level Windows probe into a non-canonical temporary directory, revalidates the pair against `renderer-contract.json`, then atomically commits the canonical `windows-evidence/` directory. The renderer build itself independently fails closed if the Unity project version, renderer application id, deformation-sequence contract or UniVRM package pin drifts before Unity is started.

After it completes, run the status command again before doing anything else.

### `physical_windows_acceptance` — human attestation

Before executing the attestation command, physically inspect the complete Windows sequence and explicitly verify:

- the full deformation sequence was reviewed;
- source identity/texture is acceptable;
- geometry/proportions are acceptable;
- upper-body deformation is acceptable;
- lower-body deformation is acceptable;
- no cross-limb leakage is visible;
- skin QA was considered.

The printed command must route through `record-reference-renderer-acceptance.ps1`. That wrapper revalidates the canonical evidence pair and renderer contract, supplies the exact contracted renderer identity to the core recorder, and requires `-ConfirmQualityChecklist`. Replace only the quality-note placeholder with a real observation. Do not attest PASS if any item is uncertain or failed.

Then rerun status.

### `physical_quest_acceptance` — machine probe

Before the Quest step, connect the headset and rerun the preflight. With one headset/device:

```powershell
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected
```

With several adb devices, keep the intended Quest serial explicit:

```powershell
$questSerial = '<serial>'
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1 -RequireQuestConnected -Serial $questSerial
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview -Serial $questSerial
```

The printed command must route through `run-reference-quest-renderer-probe.ps1`. The status layer injects the `adb.exe` from the pinned Unity Android SDK automatically and adds `-Serial` when you supplied one. Do **not** replace it with an arbitrary PATH adb or manually rewrite the generated command.

The reference wrapper lets the low-level Quest probe stage into a unique non-canonical directory, revalidates the pair against the renderer contract and only then commits `quest-evidence/`. Evidence must come from an actual Quest/Oculus-class device and remain bound to the exact package/runtime/revision.

Then rerun status.

### `physical_quest_acceptance` — human attestation

Review the complete six-pose sequence **in the headset** against the same quality checklist used on Windows. The printed command again routes through `record-reference-renderer-acceptance.ps1`, which revalidates the Quest evidence pair and exact renderer contract before the core human attestation is written. Replace only the headset quality-note placeholder with what you actually observed.

Then rerun status.

### `final_release`

Only after both reference-wrapped physical attestations validate will status expose:

```powershell
.\complete-reference-acceptance.ps1 -AcceptanceDir '<acceptance-dir>'
```

The reference release wrapper revalidates renderer contract, evidence layout and structured human quality review before delegating to core `complete-acceptance.ps1`. The core final gate independently requires current HEAD to equal the exact Gate A revision and all physical evidence to bind to the same revision/package/runtime. Run exactly the generated command, then rerun status once more.

## 4. Definition of done

The session is complete only when:

```powershell
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview
```

prints `PRODUCTION READY` with no next gate, and the JSON form reports both:

```text
production_ready=true
production_activation=true
```

Those flags are valid only because the exact source-grounded HFN detail-bearing package and handoff chain have passed canonical HFN four-view review, package-bound HFN human review, package-wide human review, fresh Gate A, canonical reference-policy Windows physical acceptance, canonical reference-policy Quest physical acceptance and canonical final release.

## 5. Things not to do during this run

- Do not rerun retained reconstruction just to create new authority.
- Do not invent HFN detail when exact source evidence is missing or insufficient.
- Do not bypass `hfn_detail_candidate`, `hfn_render_review` or `hfn_human_review` to create Gate A from face-secondary-only bytes.
- Do not point an old Gate A/package/runtime receipt at promoted bytes.
- Do not use `accept-reconciled-physical-clone.ps1` for this flow.
- Do not edit JSON evidence by hand.
- Do not manually delete or overwrite an HFN review or high-fidelity human-review sidecar; use only the status-exposed create-only/recovery path.
- Do not manually delete a create-only acceptance directory to make a command rerunnable.
- Do not pull/switch/edit the repo after fresh Gate A creation.
- Do not substitute a PATH `adb` for the pinned Unity Android SDK adb in the Quest evidence path.
- Do not call the low-level renderer/core acceptance scripts directly when the status tool has supplied a reference-wrapper command.
- Do not treat CI, screenshots or component review as Windows/Quest PASS.
- Do not execute an attestation command until the physical visual review was actually performed.

If anything fails closed, keep the exact directory and terminal output intact. The failure is evidence about where authority diverged; it is safer to diagnose that state than to erase it.
