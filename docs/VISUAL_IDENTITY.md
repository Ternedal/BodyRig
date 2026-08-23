# BodyRig visual identity and high-fidelity fitting

BodyRig separates **body/motion identity** from **visual identity**.

The existing recovery path already owns source-derived body proportions and motion style. High-fidelity fitting adds recognizable face/head, hair or scalp, skin/materials and clothing without changing ModelRig BodyCue, BodyRig Motor State, `.mrbody`, or renderer contracts.

## Non-negotiable boundary

High-fidelity reconstruction is a **build-time adapter**.

Research checkpoints, Python environments, SMPL/SMPL-X-family assets, source frames and engine-specific intermediate files must not become `.mrbody` payloads or runtime dependencies.

The portable output remains:

```text
.mrbody
  avatar.vrm
  bodyprint.json
  provenance.json
  thumbnail.png
  checksums.json
  manifest.json
```

## Visual identity profile v1

`bodyrig-visual-identity` is metadata-only evidence describing what an identity-capture stage actually observed.

It records:

- capture adapter + pinned revision;
- source count;
- exact recovery subject track id;
- observed/face/full-body/side/rear frame counts;
- normalized coverage for face, hair-or-scalp, skin, clothing, full body and back;
- normalized sharpness, lighting and visibility quality;
- explicit privacy flags proving the profile itself contains neither source media nor a biometric template.

It deliberately does **not** contain:

- source filenames or paths;
- raw/extracted frames;
- face embeddings;
- identity vectors;
- model checkpoints;
- engine-specific tensors.

BodyRig binds the profile to the same `source_count` and `track_id` as `bodyrig-recovery-proof.json`. A profile from another tracked person fails closed.

## Fitter registry

Builtin fitters advertise explicit capabilities:

```text
visual_identity
textures
hair
clothing
```

`procedural-vrm1` advertises all four as false. If an identity profile is supplied to it, BodyRig refuses the build. This prevents a placeholder avatar from being presented as an identity clone.

## Isolated external fitter transport

A high-fidelity engine runs out-of-process. BodyRig creates a strict metadata request:

```text
bodyrig-avatar-fit-request v1
  name
  bodyprint
  visual_identity
```

The private identity workspace is passed separately as a process argument and is never serialized into the request or provenance.

The external engine receives these fixed arguments after its operator-configured argv:

```text
--bodyrig-request <request.json>
--bodyrig-workspace <private workspace>
--bodyrig-output <empty output directory>
--bodyrig-adapter <adapter id>
--bodyrig-revision <pinned revision>
```

The process is launched with `shell=False`.

### Required output

The output directory must contain exactly:

```text
result.json
avatar.vrm
thumbnail.png
```

No pickle, checkpoint, debug tensor, script or other research artifact is accepted.

`result.json` must identify the exact adapter/revision, report `visual_identity=source-derived`, and contain SHA-256 values for `avatar.vrm` and `thumbnail.png`.

BodyRig then independently:

1. recomputes both hashes;
2. validates `avatar.vrm` as VRM 1.0;
3. validates the thumbnail PNG signature;
4. rejects any extra output file;
5. builds `.mrbody` through the normal package validator;
6. records only capture/fitting adapter provenance, never the command or private workspace path.

## Operator configuration

External engines use a local, non-portable config:

```json
{
  "format": "bodyrig-external-fitter-config",
  "version": 1,
  "adapter": "example-high-fidelity",
  "revision": "pinned-engine-or-adapter-revision",
  "command": [
    "C:\\path\\to\\python.exe",
    "C:\\path\\to\\bodyrig_adapter.py"
  ],
  "capabilities": {
    "visual_identity": true,
    "textures": true,
    "hair": true,
    "clothing": true
  },
  "timeout_seconds": 3600
}
```

The command is operator-supplied local configuration. It can never be supplied by `.mrbody` content.

The generic invocation is:

```powershell
bodyrig-fit-avatar-external `
  .\bodyrig-recovery-proof.json `
  --identity-profile .\bodyrig-visual-identity.json `
  --identity-workspace C:\private\bodyrig-identity-workspace `
  --config .\my-fitter-config.json `
  --body-id person-a `
  --name "Person A" `
  --out .\person-a.mrbody
```

## Engine candidates

The adapter boundary is intentionally engine-neutral.

Current research candidates include ECON-family reconstruction and SiTH-style textured human reconstruction. They are **evaluation candidates, not BodyRig dependencies**. Repository licenses, model licenses, SMPL/SMPL-X terms, supported operating systems and practical GPU requirements must be evaluated independently before an adapter is accepted.

A visually impressive demo is not enough to make an engine the BodyRig default.

## High-fidelity acceptance

A real high-fidelity adapter is not accepted merely because it exits successfully.

It must eventually prove:

1. real user video generated the recovery proof and identity capture;
2. both artifacts bind to the same tracked subject;
3. the external fitter output passes the strict byte/VRM boundary;
4. the resulting `.mrbody` contains no source media or research runtime dependency;
5. the same package/runtime passes the existing built-WindowsPlayer and Quest-class renderer probes;
6. human visual acceptance confirms the claimed identity fidelity;
7. final release evidence remains bound to the exact package/runtime/avatar/bodyprint hashes.
