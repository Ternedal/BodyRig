# Physical clone session evidence

`clone-body-from-stash-ready.ps1` is the canonical launcher for the first real high-fidelity BodyRig clone on the target rig.

The launcher writes two local evidence artifacts in addition to the normal clone output:

1. a create-only `bodyrig-rig-readiness` v1 report from `check-rig-ready.ps1`;
2. a `bodyrig-physical-clone-session` v1 report that binds the run together.

The session report is deliberately local operator evidence. It is not part of `.mrbody` and must never become a runtime dependency.

## Default operator path

```powershell
.\clone-body-from-stash-ready.ps1 `
  -PerformerId 123 `
  -BodyId "performer-123"
```

Before creating session evidence, the launcher resolves the exact BodyRig Git HEAD and checks `git status --porcelain`. The default physical-clone path refuses a dirty checkout. `-AllowDirty` exists only as an explicit diagnostic escape hatch, and the session records `bodyrig_checkout_clean=false` whenever that switch is used, even if the checkout happened to be clean at launch. A dirty/diagnostic run may exercise readiness and clone execution, but it cannot become `status=pass`: both the session transition and strict v1 validator reject non-authoritative PASS evidence. It therefore also cannot satisfy the high-fidelity production Gate A.

The selected `BodyRigPython` is also proven before the session file is created. The interpreter must import `bodyrig` from exactly `<checkout>\bodyrig\__init__.py`; a global wheel or another checkout is rejected before `physical_session start`, so session evidence cannot be stamped with one Git revision while executing BodyRig Python from somewhere else.

The launcher then resolves the master rig setup report, starts a create-only session report, runs live readiness, hashes the resulting readiness report, and starts the existing Stash clone pipeline. Before a PASS session is written, Git HEAD **and** `git status --porcelain` are checked again. If HEAD changed or the default production checkout became dirty during the potentially long clone, PASS evidence is refused. This means an edit made while the clone is running cannot silently retain the launch-time clean-checkout claim.

If `-OutputDir` is omitted, a unique timestamped clone output directory is written outside the Git checkout under `%LOCALAPPDATA%\BodyRig\physical-clones` (or the system temporary directory when `LOCALAPPDATA` is unavailable). If `-SessionReport` is omitted, the local session report is written below `%LOCALAPPDATA%\BodyRig\physical-clone-sessions` with the same run suffix. Keeping generated artifacts outside the checkout prevents the operator flow itself from making later clean-checkout gates fail.

Both locations can be supplied explicitly:

```powershell
.\clone-body-from-stash-ready.ps1 `
  -PerformerId 123 `
  -BodyId "performer-123" `
  -OutputDir "D:\BodyRig\physical\performer-123" `
  -SessionReport "D:\BodyRig\evidence\performer-123-session.json"
```

## Session state machine

A session starts as:

```text
status=running
stage=initializing
```

A successful live readiness check stores the SHA-256 of the immutable readiness report and advances the session to:

```text
status=running
stage=clone
```

A successful clone from a clean checkout finishes as:

```text
status=pass
stage=complete
```

Any failure before completion is recorded as `status=fail` with the failing stage (`initializing`, `readiness`, or `clone`) and a bounded diagnostic message.

A passed session is impossible without readiness evidence and a clean checkout. A clone-stage failure is also impossible to record unless readiness evidence was already bound.

## Trust and privacy boundary

The session report contains only:

- session UUID and timestamps;
- performer id and BodyRig body id;
- exact 40-character BodyRig Git revision and whether the checkout was authoritative/clean for production;
- master rig setup SHA-256;
- live readiness report SHA-256;
- final local clone output path on success;
- status/stage and bounded failure text.

It does not define fields for Stash API keys, Stash URL, source video paths, private observation segments, captured identity frames, SiTH workspaces or research-model paths.

Those remain build-time/private data and do not become portable `.mrbody` metadata.

## Validation

Validate an existing session report with:

```powershell
python -m bodyrig.physical_session validate "C:\path\to\session.json"
```

The validator is strict about exact v1 fields, Git revision syntax, boolean checkout status, lowercase SHA-256 values, state transitions, timestamps and BodyRig body-id syntax. A `status=pass` report additionally requires `bodyrig_checkout_clean=true`; hand-edited or replayed dirty PASS JSON fails closed. The JSON shape and the same conditional rule are documented in `contracts/physical-clone-session-v1.schema.json`.

## Promote a PASS clone into production Gate A

A successful physical clone session proves that one exact, clean BodyRig revision reached a real source-derived clone after a fresh rig-readiness check. It is not yet renderer acceptance.

Promote the exact resulting `.mrbody` bytes with:

```powershell
.\accept-physical-clone.ps1 `
  -SessionReport "C:\path\to\physical-clone-session.json"
```

That bridge revalidates the session/readiness lineage, recovery proof, visual-identity binding, built-in `sith-smplx-vrm` v1 provenance and non-placeholder VRM 1.0 package. It also independently binds its selected BodyRig Python import back to the same checkout. It then copies the exact `.mrbody` bytes into a write-once Gate A bundle and materializes renderer runtime from that package; it does not refit or rebuild the avatar.

The same accepted high-fidelity `.mrbody` must then pass physical WindowsPlayer and Quest-class renderer probes, human visual-quality attestations and `complete-acceptance.ps1` before `production_activation=true` is allowed.
