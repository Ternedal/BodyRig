# First physical BodyRig run

This is the shortest canonical operator path for the first real local Stash → high-fidelity `.mrbody` acceptance run.

It does **not** replace the hard evidence gates. It exists to remove operator guesswork around Stash performer ids, the local alias, the derived portable body identity and the exact next acceptance command.

## 0. Start from the verified operator checkout

Use exact clean current `main` as the normal software authority. If a historical or frozen physical procedure explicitly names an exact BodyRig SHA, use that SHA only for that evidence path; never discover current authority through PR #1. The production physical path is intentionally standardized on **PowerShell 7+ (`pwsh`)**, matching the tested operator/CI runtime. Do not use Windows PowerShell 5.1 for the physical acceptance run.

Verify the shell and checkout before starting:

```powershell
$PSVersionTable.PSVersion
git status --porcelain
git rev-parse HEAD
```

PowerShell major version must be `7` or newer, and `Get-Command pwsh` must resolve successfully. `git status --porcelain` must be empty. Do not use `-AllowDirty` for production evidence; that switch is diagnostics-only and produces non-authoritative session state.

The BodyRig Python used by the ready launcher must import `bodyrig` from this exact checkout. The launcher verifies that automatically before creating session evidence.

### Require current rig / SiTH setup authority

Before source discovery or any physical session, the active master rig setup must contain a strict **`bodyrig-sith-setup` v4** high-fidelity report. Existing v1/v2/v3 SiTH setup evidence is not valid authority for a new canonical physical run; rerun `setup-rig-windows.ps1` to regenerate the master report and its nested SiTH setup evidence before continuing.

Version 4 binds the exact provisioned `checkpoints/recon_model.pth` and `checkpoints/save_smplerx.pth` bytes by SHA-256 + byte count. Those checkpoint bytes are revalidated during live readiness and again at fitter **point-of-use** immediately before private staging/reconstruction. Do not edit or re-hash an old report by hand to migrate it.

The pre-session doctor validates the master rig report and its nested SiTH v4 report **before** it spends time on Unity/Quest toolchain or live readiness checks. A stale setup therefore fails early and creates no physical evidence.

## 1. Configure local Stash transport with the fresh test token

For the first physical acceptance run, create/use a **fresh local Stash API token** for BodyRig and put it only in the current PowerShell process environment. Do not paste the token into GitHub, chat, command arguments or evidence files.

```powershell
$env:STASH_URL = "http://127.0.0.1:9999"
$env:STASH_API_KEY = "<fresh local Stash API key>"
```

If the local Stash instance truly does not require authentication, `STASH_API_KEY` may be unset/empty. Otherwise the fresh token is a hard prerequisite for the physical test.

The API key is transport-only configuration. It must not appear in source manifests, portable identity, `.mrbody` provenance or runtime assets.

## 2. Prove the fresh Stash token works before search or clone

Use the checkout-bound PowerShell wrapper:

```powershell
.\stash-sources.ps1 health
```

This `health` call is the authentication/capability gate for the future physical test. **Do not continue to performer search or clone unless it succeeds with the fresh token.** If it fails because the token is invalid, expired, revoked, missing or lacks performer-read access, replace/fix the token and repeat `health`; do not work around the failure by editing evidence or bypassing readiness.

Do not rely on `bodyrig-stash-sources` being present on the shell `PATH`. A repo-local `.venv\Scripts\python.exe` is not automatically added to `PATH` by `setup-rig-windows.ps1`, so the wrapper resolves the same repo-local Python authority used by the physical launcher, verifies that `bodyrig.__file__` points at this checkout and then invokes `python -m bodyrig.stash_cli`.

A successful call prints a small JSON object containing `ok=true`, the Stash version and **`performer_read=true`**. `health` proves the same read capability used by the following performer-search step while discarding the probe result and reading no media. Do not continue to a long physical clone unless all of those fields indicate PASS.

## 3. Find and preflight the performer id

Only after the token-backed `health` gate is green, search by performer name:

```powershell
.\stash-sources.ps1 search "<performer name>" -Limit 10
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

Before starting a physical session, prove that the exact selected performer still resolves and has at least one **locally decodable** ranked video source:

```powershell
.\stash-sources.ps1 probe -PerformerId "123"
```

The wrapper resolves the local FFmpeg executable and the probe attempts to decode exactly one video frame from each ranked candidate using the `ffmpeg-one-frame-v1` gate. A candidate only counts as usable if that decode exits successfully. A timeout, unreadable/corrupt file, missing video stream, permissions problem or unsupported media failure therefore cannot produce a pre-session PASS merely because the path exists.

The probe is read-only/pre-session. It does **not** write a source manifest, segment, clone output or acceptance evidence. Its output is metadata-only: Stash version, performer `id`/`name`/`disambiguation`, total candidate count, rankable local-source count, decodable/usable local-source count and the decode-gate id. It deliberately does **not** print local source paths or FFmpeg stderr containing those paths.

Do not continue if `ok=true` is absent, the returned performer id differs, `decode_gate` is not `ffmpeg-one-frame-v1`, or `usable_source_count` is below `1`. The pre-session doctor repeats this same exact selected-performer/source-decode gate automatically when `-PerformerId` and `-BodyId` are supplied.

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

## 5. Run the pre-session doctor before creating physical evidence

Before the production launcher creates a `bodyrig-physical-clone-session`, run the read-only/pre-session doctor from **PowerShell 7+ (`pwsh`)**:

```powershell
.\prepare-first-physical-run.ps1 `
  -PerformerId "123" `
  -BodyId "performer-123"
```

The doctor verifies PowerShell 7+, exact clean checkout, checkout-bound BodyRig Python and the existing master rig setup. It first validates the master report and nested `bodyrig-sith-setup` v4 evidence, including the byte-bound checkpoint authority, before running Unity/Quest or live readiness checks. It then runs live recovery/SiTH/OpenPose/checkpoint/model/Stash readiness. When the performer/body pair is supplied, it resolves the local FFmpeg executable and repeats the selected-performer probe, requiring at least one local source that passes `ffmpeg-one-frame-v1`. It also verifies that the probe explicitly reports that canonical decode gate. It deliberately calls `check-rig-ready.ps1` **without** `-Out` and the performer probe without a source-manifest output, so it does not create authoritative readiness evidence, source manifests, physical clone session state, clone output or acceptance evidence.

A successful run ends with:

```text
BodyRig pre-session doctor: READY
```

and prints the canonical `clone-body-from-stash-ready.ps1` command for the selected performer/alias. That emitted command carries forward the exact rig-setup report, checkout-bound BodyRig Python, resolved Stash URL, API-key environment-variable name, resolved WSL executable and resolved FFmpeg executable that the doctor just proved. Use that emitted command verbatim rather than reconstructing a shorter equivalent by hand.

If the doctor fails, fix that prerequisite and rerun it. If it reports stale v1/v2/v3 SiTH setup evidence, rerun `setup-rig-windows.ps1`; do not patch the JSON evidence manually. This keeps setup/auth/environment/source-decode/source-selection failures out of the create-only physical session history. The production launcher repeats the trust checks and creates fresh session-bound readiness/source evidence; the doctor is not a substitute for those gates.

You can also run the doctor before choosing a performer:

```powershell
.\prepare-first-physical-run.ps1
```

In that mode it proves the general rig/Stash capability is ready and points you to the performer-search step, but still creates no physical evidence and cannot prove a specific performer's local source pool.

## 6. Run the production clone

After `setup-rig-windows.ps1` has produced a valid master rig setup with nested `bodyrig-sith-setup` v4 evidence, the fresh-token `health` gate has passed with `performer_read=true`, the selected performer probe has at least one FFmpeg-decodable local video, and the PowerShell-7 pre-session doctor is READY, run the **exact command printed by the doctor**. Its shape is:

```powershell
.\clone-body-from-stash-ready.ps1 `
  -PerformerId "123" `
  -BodyId "performer-123" `
  -RigSetupReport "<doctor-proven rig setup report>" `
  -BodyRigPython "<doctor-proven checkout Python>" `
  -StashUrl "<doctor-proven Stash URL>" `
  -ApiKeyEnv "STASH_API_KEY" `
  -WslExe "<doctor-proven WSL executable>" `
  -Ffmpeg "<doctor-proven FFmpeg executable>"
```

The normal production Stash selection uses the **same resolved FFmpeg executable** for source decode qualification and observation selection. The same WSL executable used by pre-session/readiness is also propagated into the actual SiTH clone path. `stash_cli select` applies the one-frame decode gate by default. `--skip-decode-probe` exists only behind the explicit diagnostics path associated with skipping observation selection; it is not part of the canonical production run.

The ready launcher performs, in order:

1. exact Git HEAD + clean-checkout authority;
2. checkout-bound BodyRig Python authority;
3. rig-setup / strict SiTH-setup v4 validation, including checkpoint-bound setup evidence;
4. fresh recovery + SiTH/OpenPose/checkpoint/model + Stash readiness, including performer-read capability and live checkpoint re-hash;
5. SHA-256 binding of the readiness report into the physical session;
6. local Stash source ranking + one-frame FFmpeg decode qualification + private observation-segment path;
7. recovery + visual identity + source-byte TOCTOU check;
8. create-only portable identity receipt and derived canonical `bodyid-*`;
9. built-in `sith-smplx-vrm` high-fidelity fitting/package generation, with checkpoint point-of-use re-hash before private staging/reconstruction;
10. exact Git HEAD + clean-checkout + rig-setup SHA-256 revalidation before session PASS publication;
11. a second exact Git HEAD + clean-checkout + rig-setup SHA-256 revalidation **after** session PASS publication and before the launcher may return success.

If authority drifts in the post-PASS publication window, the launcher removes the just-published `SessionReport` fail-closed. Clone/readiness output can remain for diagnostics, but no terminal production PASS is left for Gate A to consume.

By default clone artifacts are written outside the repository under:

```text
%LOCALAPPDATA%\BodyRig\physical-clones
```

and session/readiness evidence under:

```text
%LOCALAPPDATA%\BodyRig\physical-clone-sessions
```

A successful clone session is still **not** final production acceptance.

## 7. Inspect the physical session before doing anything else

Use the session report path printed by the ready launcher:

```powershell
.\physical-acceptance-status.ps1 `
  -SessionReport "C:\path\to\bodyrig-physical-clone-session.json"
```

For a production-valid completed clone, status should point to Gate A and print the exact next command. Prefer that emitted `Next command` rather than reconstructing paths manually.

If the session is failed, incomplete, dirty-checkout-bound or has mismatched readiness evidence, stop there. Do not manufacture or edit evidence to advance the state machine.

## 8. Promote the exact clone bytes into high-fidelity Gate A

The expected next command is equivalent to:

```powershell
.\accept-physical-clone.ps1 `
  -SessionReport "C:\path\to\bodyrig-physical-clone-session.json"
```

Gate A does not refit the avatar. It revalidates and promotes the exact high-fidelity clone bytes, re-binds the portable identity receipt to the persistent recovery/visual evidence, verifies `sith-smplx-vrm` v1 provenance, runs anatomical skin QA and materializes runtime from the accepted `.mrbody`.

After Gate A, the accepted package/runtime identity is the canonical `bodyid-*`, not the original operator alias.

## 9. Resume through Windows, Quest and final release only via status

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

## 10. What counts as the first real PASS

The first run is useful physical evidence only if all of the following are true:

- PowerShell 7+ (`pwsh`) was used for the canonical pre-session path;
- the master rig setup contained strict `bodyrig-sith-setup` v4 evidence rather than stale v1/v2/v3 evidence;
- `recon_model.pth` and `save_smplerx.pth` remained byte-bound through setup, live readiness and fitter point-of-use revalidation;
- the fresh Stash token passed the checkout-bound `health` gate with `ok=true` and `performer_read=true` before source discovery/clone;
- the exact selected performer passed the metadata-only source probe with at least one local video that passed `ffmpeg-one-frame-v1` before session creation;
- the pre-session doctor repeated the same decode-qualified source gate without creating physical evidence;
- the doctor-emitted production command preserved the same rig-setup, checkout-Python, Stash transport, WSL and FFmpeg authorities into the actual clone;
- real local Stash performer/video sources were used;
- normal production source selection reused the same resolved FFmpeg authority and did not skip the decode gate;
- the same WSL authority survived readiness and the actual built-in SiTH execution path;
- source-byte TOCTOU binding held through clone;
- the create-only portable identity receipt is present and canonical;
- the `.mrbody` manifest uses the derived `bodyid-*`;
- terminal physical-session PASS survived both pre-publication and post-publication HEAD/clean/rig-setup authority revalidation;
- Gate A accepts the exact clone bytes without refit/substitution;
- source identity/texture/geometry are physically acceptable;
- skin/deformation review shows no unacceptable cross-limb leakage;
- WindowsPlayer and Quest use the same accepted body/package/runtime identity;
- final release gate is the only step that sets `production_activation=true`.

CI, fixtures, a procedural placeholder, a successful Stash search or a file that merely exists on disk do not satisfy these physical gates.
