# BodyRig high-fidelity physical acceptance runbook

Updated: 2026-09-05.

This is the operator path from a persisted high-fidelity continuation to canonical production release. It deliberately does **not** manufacture human or hardware evidence. Run exactly one gate at a time and re-read status after every gate.

## 0. Synchronize the operator checkout before starting

Do this **before** a fresh promoted-package Gate A exists:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
git status --short
git fetch origin
git switch agent/high-fidelity-integration-20260904
git pull --ff-only origin agent/high-fidelity-integration-20260904
git status --short
git rev-parse HEAD
```

Both `git status --short` calls must be empty.

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

Run this again **after every successful command below**. It validates the current promoted package, package-bound review, transitive handoff authority, fresh Gate A/QA/runtime hashes, source Gate A lineage, physical evidence and the clean operator checkout before it exposes an executable next command.

For machine-readable troubleshooting:

```powershell
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview -Json
```

If the status is `BLOCKED`, stop. Do not delete/recreate evidence or skip the gate. Preserve the output and logs for diagnosis.

## 3. Possible next gates

### `high_fidelity_human_review`

Review the exact promoted package evidence in Person Studio. The review must cover source identity, anatomy, skin, hair, eyes/iris, face-secondary, full-body multiview and face close-up. Then use the exact command printed by the status tool and replace only the quality-note placeholder with what you actually reviewed.

This gate is package-bound and non-activating.

### `physical_gate_a`

Run the printed command. It will be equivalent to:

```powershell
.\prepare-high-fidelity-physical-acceptance.ps1 -PreviewJobId $preview
```

The command creates a new acceptance directory atomically from the exact promoted package, reuses only hash-bound physical session/readiness as source lineage, recomputes skin/topology QA, materializes a fresh runtime and stops at Windows probe. It does not reuse old package/runtime authority.

**The checkout freeze starts here.**

### `physical_windows_acceptance` — machine probe

Run the exact command printed by status. It starts the canonical built WindowsPlayer machine + six-pose deformation probe and persists the exact evidence pair.

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

The operator status tool reads the exact renderer name/version from the committed Windows probe and inserts `-ConfirmQualityChecklist` into the generated attestation command. Replace only the quality-note placeholder with a real observation. Do not attest PASS if any item is uncertain or failed.

Then rerun status.

### `physical_quest_acceptance` — machine probe

Put the exact same accepted runtime through the canonical Quest-class/Android probe using the command printed by status. The evidence must come from an actual Quest/Oculus-class device; the canonical validator checks the platform/device identity and exact package/runtime/revision lineage.

Then rerun status.

### `physical_quest_acceptance` — human attestation

Review the complete six-pose sequence **in the headset** against the same quality checklist used on Windows. The status tool fills the renderer identity and required checklist switch from exact probe evidence. Replace only the headset quality-note placeholder with what you actually observed.

Then rerun status.

### `final_release`

Only after both physical attestations validate will status expose `complete-acceptance.ps1`. Run exactly that generated command, then rerun status once more.

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

Those flags are valid only because the exact promoted package and handoff chain have passed package-bound human review, fresh Gate A, Windows physical acceptance, Quest physical acceptance and canonical final release.

## 5. Things not to do during this run

- Do not rerun retained reconstruction just to create new authority.
- Do not point an old Gate A/package/runtime receipt at promoted bytes.
- Do not use `accept-reconciled-physical-clone.ps1` for this flow.
- Do not edit JSON evidence by hand.
- Do not manually delete a create-only acceptance directory to make a command rerunnable.
- Do not pull/switch/edit the repo after fresh Gate A creation.
- Do not treat CI, screenshots or component review as Windows/Quest PASS.
- Do not execute an attestation command until the physical visual review was actually performed.

If anything fails closed, keep the exact directory and terminal output intact. The failure is evidence about where authority diverged; it is safer to diagnose that state than to erase it.
