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
- the local diffusion-model tree by SHA-256 over relative path, size and file bytes.

Both Git checkouts must have clean tracked files when they are accepted. `bodyrig-sith-preflight` verifies the pinned OpenPose checkout when `--openpose-repo` is supplied.

## OpenPose

`-ProvisionOpenPose` invokes `setup-openpose-wsl.ps1`. It clones/checks out the pinned OpenPose revision, initializes submodules, configures CUDA + BODY_25 + face + hand models, builds the examples and requires:

```text
<openpose repo>/build/examples/openpose/openpose.bin
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

A successful setup atomically writes a strict `bodyrig-sith-setup` v1 report. Default Windows location:

```text
%LOCALAPPDATA%\BodyRig\sith\setup-report.json
```

The report contains only local build configuration and integrity data:

```json
{
  "format": "bodyrig-sith-setup",
  "version": 1,
  "distribution": "Ubuntu-22.04",
  "sith": {
    "repository": "/home/user/.local/share/bodyrig/sith",
    "revision": "6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d",
    "python": "/home/user/.local/share/bodyrig/sith/.bodyrig-venv/bin/python"
  },
  "openpose": {
    "repository": "/home/user/.local/share/bodyrig/openpose-v1.7.0",
    "revision": "8ca5c1d95a42340b323e9273654d1db98bec779c",
    "executable": "/home/user/.local/share/bodyrig/openpose-v1.7.0/build/examples/openpose/openpose.bin"
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

With `-PersistUserEnvironment`, setup also persists the `BODYRIG_SITH_*` values consumed by `clone-body-from-stash.ps1`, including `BODYRIG_SITH_SETUP_REPORT` and the pinned OpenPose repository path. No Stash key or source-media path is written to this report.

## Normal clone after setup

After the one-time setup, the built-in Stash path needs no identity/fitter config:

```powershell
.\clone-body-from-stash.ps1 `
  -PerformerId 123 `
  -ExternalPython "C:\...\recovery\python.exe" `
  -FourDHumansRepo "C:\...\4D-Humans" `
  -BodyId "performer-123"
```

The wrapper still re-runs the SiTH preflight and re-digests the diffusion model before source discovery. The setup report is therefore convenience + authority evidence, not a bypass around live validation.
