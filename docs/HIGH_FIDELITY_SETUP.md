# High-fidelity BodyRig setup (Windows + WSL)

BodyRig's built-in high-fidelity Stash path uses a pinned research stack behind WSL. The normal one-time setup entry point is:

```powershell
.\setup-high-fidelity-wsl.ps1 `
  -DiffusionModel "/home/<user>/.cache/bodyrig/sith-diffusion" `
  -SmplxSource "C:\path\to\licensed\SMPL-X-assets" `
  -ProvisionOpenPose `
  -DownloadPublicCheckpoints `
  -PersistUserEnvironment
```

The setup is fail-closed. It does not make the BodyRig runtime depend on the research stack; it only prepares the private build environment used by the built-in `sith-smplx-vrm` fitter.

## Authority pins

BodyRig pins:

- SiTH revision `6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d`;
- OpenPose v1.7.0 revision `8ca5c1d95a42340b323e9273654d1db98bec779c`;
- the individual SiTH scripts/configuration that BodyRig executes;
- the OpenPose v1.7.0 `CMakeLists.txt` Git blob;
- the built OpenPose executable bytes by SHA-256 + byte count;
- the complete OpenPose model tree by deterministic SHA-256 over relative path, size and file bytes;
- the local SiTH diffusion-model tree by the same byte-bound tree-digest principle.

Both Git checkouts must have clean tracked files when they are accepted. `bodyrig-sith-preflight` verifies the pinned OpenPose checkout when `--openpose-repo` is supplied. Setup additionally binds the exact `openpose.bin` and `openpose/models` bytes, so a later rebuild, model replacement or partial re-download cannot pass readiness merely because source control still matches.

## OpenPose

`-ProvisionOpenPose` invokes `setup-openpose-wsl.ps1`. It clones/checks out the pinned OpenPose revision, initializes submodules, configures CUDA + BODY_25 + face + hand models, builds the examples and requires:

```text
<openpose repo>/build/examples/openpose/openpose.bin
<openpose repo>/models/
```

The script deliberately does not run `sudo apt`. Required Ubuntu build tools and CUDA must already be present. Missing `git`, `cmake`, `make` or `nvcc` fails before a build is started.

An existing pinned OpenPose checkout can be used instead:

```powershell
.\setup-high-fidelity-wsl.ps1 `
  -OpenPoseRepo "/opt/openpose" `
  -OpenPoseExecutable "/opt/openpose/build/examples/openpose/openpose.bin" `
  -DiffusionModel "/opt/bodyrig-models/sith-diffusion" `
  -SmplxSource "C:\path\to\licensed\SMPL-X-assets" `
  -PersistUserEnvironment
```

## SMPL-X assets

SMPL-X files remain an explicit local prerequisite. BodyRig never downloads, redistributes or embeds them in `.mrbody`. `-SmplxSource` copies the expected local files into the private SiTH build checkout, after which the SiTH preflight requires all six expected neutral/male/female PKL/NPZ files.

## SiTH checkpoints and diffusion model

`-DownloadPublicCheckpoints` downloads the two public SiTH checkpoints expected by the pinned upstream revision. The diffusion model is different: BodyRig requires an operator-supplied **local directory** and hashes the complete model tree. Reconstruction runs with Hugging Face/Transformers offline mode enabled and a fixed seed by default.

## Setup report

A successful setup atomically writes a strict `bodyrig-sith-setup` v3 report. Default Windows location:

```text
%LOCALAPPDATA%\BodyRig\sith\setup-report.json
```

Version 3 adds the mandatory OpenPose model-tree binding on top of the executable binding introduced by v2. Existing v1/v2 reports must be regenerated with `setup-high-fidelity-wsl.ps1`.

The report contains only local build configuration and integrity data:

```json
{
  "format": "bodyrig-sith-setup",
  "version": 3,
  "distribution": "Ubuntu-22.04",
  "sith": {
    "repository": "/home/user/.local/share/bodyrig/sith",
    "revision": "6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d",
    "python": "/home/user/.local/share/bodyrig/sith/.bodyrig-venv/bin/python"
  },
  "openpose": {
    "repository": "/home/user/.local/share/bodyrig/openpose-v1.7.0",
    "revision": "8ca5c1d95a42340b323e9273654d1db98bec779c",
    "executable": "/home/user/.local/share/bodyrig/openpose-v1.7.0/build/examples/openpose/openpose.bin",
    "sha256": "<64 lowercase hex>",
    "byte_count": 1,
    "models_sha256": "<64 lowercase hex>",
    "models_file_count": 1,
    "models_byte_count": 1
  },
  "diffusion_model": {
    "path": "/home/user/.cache/bodyrig/sith-diffusion",
    "sha256": "<64 lowercase hex>",
    "file_count": 1,
    "byte_count": 1
  }
}
```

The report is validated by `bodyrig.sith_setup` before it replaces the previous setup report.

With `-PersistUserEnvironment`, setup also persists the `BODYRIG_SITH_*` values consumed by the built-in Stash path, including `BODYRIG_SITH_SETUP_REPORT`, `BODYRIG_SITH_OPENPOSE_SHA256` and `BODYRIG_SITH_OPENPOSE_MODELS_SHA256`. No Stash key or source-media path is written to this report.

## Live readiness

`check-rig-ready.ps1` does not trust the setup report by itself. Before a ready-rig clone it:

1. re-runs recovery preflight;
2. re-runs pinned SiTH/OpenPose source preflight;
3. re-hashes `openpose.bin`;
4. re-digests the complete `openpose/models` tree;
5. re-digests the local diffusion-model tree;
6. checks Stash GraphQL health.

All live hashes and counts must match v3 setup evidence exactly. `clone-body-from-stash-ready.ps1` runs this readiness gate before it starts the clone pipeline.

## Normal clone after setup

The safest normal operator path after full rig setup is:

```powershell
.\clone-body-from-stash-ready.ps1 `
  -PerformerId 123 `
  -BodyId "performer-123"
```

The ready launcher reads the master rig setup report, rehydrates the pinned build settings, requires the full live readiness gate and only then invokes the existing Stash clone pipeline. The setup report is therefore authority evidence, not a bypass around live validation.
