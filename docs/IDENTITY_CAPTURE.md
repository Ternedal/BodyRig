# BodyRig automatic visual identity capture

This stage turns the same local source clips used for recovery into a strict `bodyrig-visual-identity` profile plus a **private, non-portable workspace** for a high-fidelity fitter.

## Boundary

BodyRig core validates the selected recovery proof and source files, then launches an operator-configured capture adapter out-of-process with `shell=False`.

Source paths are passed only as repeated process arguments:

```text
--bodyrig-source <local file>
```

They are never written into the capture request, visual-identity profile, `.mrbody` provenance or runtime package.

The metadata request contains only:

```text
bodyrig-identity-capture-request v1
  adapter
  revision
  source_count
  subject_track_id
  observed_frames
```

The adapter receives a newly-created private workspace. It may place derived face crops, segmentation, reconstruction intermediates or other engine-private data there. BodyRig never copies those files into the portable package.

The ephemeral result directory may contain **exactly one file**:

```text
identity.json
```

Any extra result artifact is rejected. On failed capture, BodyRig removes the newly-created private workspace.

## Config

Example local config:

```json
{
  "format": "bodyrig-identity-capture-config",
  "version": 1,
  "adapter": "example-identity-capture",
  "revision": "pinned-adapter-revision",
  "command": [
    "C:\\path\\to\\python.exe",
    "C:\\path\\to\\capture_adapter.py"
  ],
  "timeout_seconds": 3600
}
```

This file is local operator configuration and must not be embedded in `.mrbody`.

## Run capture

```powershell
bodyrig-capture-identity `
  .\bodyrig-recovery-proof.json `
  C:\video\person-1.mp4 `
  C:\video\person-2.mp4 `
  --config .\identity-capture-config.json `
  --workspace C:\private\BodyRig\person-a-identity `
  --out .\bodyrig-visual-identity.json
```

The workspace and output are create-only for a run. Existing workspaces are refused to prevent cross-run identity contamination; existing identity evidence is not overwritten.

BodyRig then validates that:

- source count equals the recovery proof;
- returned profile adapter/revision matches the selected capture adapter;
- returned subject track id equals the recovery proof track id;
- frame observation counts are bounded and internally valid;
- coverage/quality fields are finite normalized values;
- the profile says it contains neither source media nor biometric templates.

## Fit the identity

Use the resulting profile and the same private workspace:

```powershell
bodyrig-fit-avatar-external `
  .\bodyrig-recovery-proof.json `
  --identity-profile .\bodyrig-visual-identity.json `
  --identity-workspace C:\private\BodyRig\person-a-identity `
  --config .\high-fidelity-fitter-config.json `
  --body-id person-a `
  --name "Person A" `
  --out .\person-a.mrbody
```

The high-fidelity fitter sees the private workspace, but BodyRig only accepts `result.json`, `avatar.vrm` and `thumbnail.png` back across the trust boundary. All returned bytes are independently validated and hashed before normal `.mrbody` packaging.

## Current proof level

CI can prove the full non-physical contract:

```text
source fixtures
  -> isolated identity capture
  -> strict visual identity profile
  -> private workspace
  -> isolated high-fidelity fitter
  -> VRM 1.0 validation
  -> .mrbody validation
```

This does not replace the physical gates. Issue #2 still requires real video recovery on the target rig; issue #3/#4 still require a real high-fidelity adapter output loaded and visually accepted on built Windows and Quest-class renderers.
