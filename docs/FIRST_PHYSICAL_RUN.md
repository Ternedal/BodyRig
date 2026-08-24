# First physical BodyRig run

This is the shortest canonical operator path for the first real local Stash → high-fidelity `.mrbody` acceptance run.

It does **not** replace the hard evidence gates. It exists to remove operator guesswork around Stash performer ids, the local alias, the derived portable body identity and the exact next acceptance command.

## 0. Start from the verified operator checkout

Use the V1 branch that PR #1 identifies as the current exact CI-green authority. Before starting a production-valid physical session:

```powershell
git status --porcelain
git rev-parse HEAD
```

`git status --porcelain` must be empty. Do not use `-AllowDirty` for production evidence; that switch is diagnostics-only and produces non-authoritative session state.

The BodyRig Python used by the ready launcher must import `bodyrig` from this exact checkout. The launcher verifies that automatically before creating session evidence.

## 1. Configure local Stash transport

Keep Stash credentials in process environment rather than command history:

```powershell
$env:STASH_URL = "http://127.0.0.1:9999"
$env:STASH_API_KEY = "<local Stash API key if required>"
```

If the local Stash instance does not require an API key, leave `STASH_API_KEY` unset/empty.

The API key is transport-only configuration. It must not appear in source manifests, portable identity, `.mrbody` provenance or runtime assets.

## 2. Prove Stash is reachable

```powershell
bodyrig-stash-sources health
```

A successful call prints a small JSON object containing `ok=true` and the Stash version. Do not continue to a long physical clone while this probe fails.

## 3. Find the performer id

Search by performer name:

```powershell
bodyrig-stash-sources search "<performer name>" --limit 10
```

The search result is deliberately minimal and returns only:

- `id`
- `name`
- `disambiguation`

Choose the intended Stash performer and copy the exact `id`. That value is the `-PerformerId` input to the production launcher.

Example result:

```json
[
  {
    "id": "123",
    "name": "Example Performer",
    "disambiguation": ""
  }
]
```

The Stash performer id is a **source-selection identifier**, not the portable BodyRig runtime identity.

## 4. Choose a local operator alias

`-BodyId` on `clone-body-from-stash-ready.ps1` is an operator/session alias. Use a stable lowercase value that matches:

```text
^[a-z0-9æøå_-]{1,160}$
```

For the first run a simple alias tied to the Stash id is fine:

```text
performer-123
```

Do not expect this alias to become the `.mrbody` manifest id. The clone derives a separate canonical portable identity:

```text
bodyid-<24 lowercase hex>
```

See `docs/PORTABLE_IDENTITY.md` for the identity authority and source-byte TOCTOU rules.

## 5. Run the production clone

After `setup-rig-windows.ps1` has produced a valid rig setup report, run:

```powershell
.\clone-body-from-stash-ready.ps1 `
  -PerformerId "123" `
  -BodyId "performer-123"
```

The ready launcher performs, in order:

1. exact Git HEAD + clean-checkout authority;
2. checkout-bound BodyRig Python authority;
3. rig-setup / SiTH-setup validation;
4. fresh recovery + SiTH/OpenPose/model + Stash readiness;
5. SHA-256 binding of the readiness report into the physical session;
6. local Stash source selection and private observation-segment path;
7. recovery + visual identity + source-byte TOCTOU check;
8. create-only portable identity receipt and derived canonical `bodyid-*`;
9. built-in `sith-smplx-vrm` high-fidelity fitting/package generation;
10. a second exact Git HEAD + clean-checkout check before session PASS.

By default clone artifacts are written outside the repository under:

```text
%LOCALAPPDATA%\BodyRig\physical-clones
```

and session/readiness evidence under:

```text
%LOCALAPPDATA%\BodyRig\physical-clone-sessions
```

A successful clone session is still **not** final production acceptance.

## 6. Inspect the physical session before doing anything else

Use the session report path printed by the ready launcher:

```powershell
.\physical-acceptance-status.ps1 `
  -SessionReport "C:\path\to\bodyrig-physical-clone-session.json"
```

For a production-valid completed clone, status should point to Gate A and print the exact next command. Prefer that emitted `Next command` rather than reconstructing paths manually.

If the session is failed, incomplete, dirty-checkout-bound or has mismatched readiness evidence, stop there. Do not manufacture or edit evidence to advance the state machine.

## 7. Promote the exact clone bytes into high-fidelity Gate A

The expected next command is equivalent to:

```powershell
.\accept-physical-clone.ps1 `
  -SessionReport "C:\path\to\bodyrig-physical-clone-session.json"
```

Gate A does not refit the avatar. It revalidates and promotes the exact high-fidelity clone bytes, re-binds the portable identity receipt to the persistent recovery/visual evidence, verifies `sith-smplx-vrm` v1 provenance, runs anatomical skin QA and materializes runtime from the accepted `.mrbody`.

After Gate A, the accepted package/runtime identity is the canonical `bodyid-*`, not the original operator alias.

## 8. Resume through Windows, Quest and final release only via status

Once Gate A exists:

```powershell
.\physical-acceptance-status.ps1 `
  -AcceptanceDir "C:\path\to\acceptance"
```

The canonical remaining sequence is:

```text
Windows reference machine + deformation probe
→ Windows human bodyrig-human-quality-v1 attestation
→ Quest reference machine + deformation probe
→ Quest human bodyrig-human-quality-v1 attestation
→ complete-reference-acceptance.ps1
```

Human renderer attestation requires `-ConfirmQualityChecklist`. It is not optional shorthand for a free-text quality note.

The same canonical body id, accepted package bytes and runtime identity must survive every physical renderer gate.

## 9. What counts as the first real PASS

The first run is useful physical evidence only if all of the following are true:

- real local Stash performer/video sources were used;
- source-byte TOCTOU binding held through clone;
- the create-only portable identity receipt is present and canonical;
- the `.mrbody` manifest uses the derived `bodyid-*`;
- Gate A accepts the exact clone bytes without refit/substitution;
- source identity/texture/geometry are physically acceptable;
- skin/deformation review shows no unacceptable cross-limb leakage;
- WindowsPlayer and Quest use the same accepted body/package/runtime identity;
- final release gate is the only step that sets `production_activation=true`.

CI, fixtures, a procedural placeholder or a successful Stash search do not satisfy these physical gates.
