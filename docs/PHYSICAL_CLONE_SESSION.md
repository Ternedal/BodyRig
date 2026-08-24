# Physical clone session evidence

`clone-body-from-stash-ready.ps1` is the canonical launcher for the first real high-fidelity BodyRig clone on the target rig.

The launcher now writes two local, immutable evidence artifacts in addition to the normal clone output:

1. a `bodyrig-rig-readiness` v1 report from `check-rig-ready.ps1`;
2. a `bodyrig-physical-clone-session` v1 report that binds the run together.

The session report is deliberately local operator evidence. It is not part of `.mrbody` and must never become a runtime dependency.

## Default operator path

```powershell
.\clone-body-from-stash-ready.ps1 `
  -PerformerId 123 `
  -BodyId "performer-123"
```

The launcher resolves the existing master rig setup report, starts a create-only session report, runs live readiness, hashes the resulting readiness report, then starts the existing Stash clone pipeline.

If `-OutputDir` is omitted, a unique timestamped clone output directory is chosen in the current working directory. If `-SessionReport` is omitted, the local session report is written below `%LOCALAPPDATA%\BodyRig\physical-clone-sessions` (or the system temporary directory when `LOCALAPPDATA` is unavailable).

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

A successful clone finishes as:

```text
status=pass
stage=complete
```

Any failure before completion is recorded as `status=fail` with the failing stage (`initializing`, `readiness`, or `clone`) and a bounded diagnostic message.

A passed session is impossible without readiness evidence. A clone-stage failure is also impossible to record unless readiness evidence was already bound.

## Trust and privacy boundary

The session report contains only:

- session UUID and timestamps;
- performer id and BodyRig body id;
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

The validator is strict about exact v1 fields, lowercase SHA-256 values, state transitions, timestamps and BodyRig body-id syntax.

## Relationship to release acceptance

A successful physical clone session is evidence that the canonical ready-launcher reached a real source-derived clone output after a fresh rig-readiness check. It is not production activation.

The same source-derived `.mrbody` still has to pass the existing physical WindowsPlayer and Quest-class renderer probes, human visual-quality attestations and `complete-acceptance.ps1` before `production_activation=true` is allowed.
