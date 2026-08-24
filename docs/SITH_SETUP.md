# SiTH WSL provisioning for BodyRig

BodyRig's built-in high-fidelity Stash path uses a pinned SiTH checkout in WSL. The normal clone path does not accept a floating SiTH `main` branch or an unverified research environment.

Pinned SiTH revision:

```text
6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d
```

Upstream SiTH documents Ubuntu 22.04, PyTorch 2.1.0, CUDA 12.1 and RTX 3090 as its tested setup. BodyRig's preflight additionally verifies the pinned executable scripts, critical Python versions, CUDA availability, required checkpoints, SMPL-X assets and OpenPose before a clone may start.

## What BodyRig can provision

`setup-sith-wsl.ps1` can:

- create or verify a pinned SiTH checkout inside WSL;
- refuse to overwrite modified tracked SiTH files;
- create a dedicated `.bodyrig-venv`;
- install SiTH's pinned `requirements.txt` plus `xatlas`;
- optionally download SiTH's two public upstream checkpoints directly from the URLs in the pinned `tools/download.sh`;
- copy an operator-supplied SMPL-X directory into the SiTH checkout;
- run `bodyrig.sith_preflight`;
- compute the deterministic local diffusion-model tree digest;
- export the exact `BODYRIG_SITH_*` settings consumed by `clone-body-from-stash.ps1`.

The setup script does not run upstream shell scripts and does not use `bash -c`/`sh -c`.

## Assets BodyRig does not silently obtain

The following remain explicit local prerequisites:

1. **SMPL-X model assets.** Supply a directory containing all six required files:

```text
SMPLX_NEUTRAL.pkl
SMPLX_NEUTRAL.npz
SMPLX_MALE.pkl
SMPLX_MALE.npz
SMPLX_FEMALE.pkl
SMPLX_FEMALE.npz
```

2. **OpenPose.** Pass the absolute Linux path to `openpose.bin`.
3. **SiTH diffusion model.** Pass an already-local absolute Linux model directory. BodyRig hashes the complete directory tree and uses that digest as execution authority.

The two public SiTH reconstruction checkpoints are also not downloaded unless `-DownloadPublicCheckpoints` is explicitly supplied.

## Provision

Example:

```powershell
.\setup-sith-wsl.ps1 `
  -Distribution "Ubuntu-22.04" `
  -OpenPose "/opt/openpose/build/examples/openpose/openpose.bin" `
  -DiffusionModel "/opt/models/sith-diffusion" `
  -SmplxSource "C:\BodyRigAssets\smplx" `
  -DownloadPublicCheckpoints `
  -PersistUserEnvironment
```

If `-InstallRoot` is omitted, BodyRig installs the checkout below the WSL user's home directory:

```text
~/.local/share/bodyrig/sith
```

The dedicated interpreter becomes:

```text
~/.local/share/bodyrig/sith/.bodyrig-venv/bin/python
```

`-PersistUserEnvironment` writes these settings for the current Windows user:

```text
BODYRIG_SITH_DISTRIBUTION
BODYRIG_SITH_REPO
BODYRIG_SITH_PYTHON
BODYRIG_SITH_OPENPOSE
BODYRIG_SITH_DIFFUSION_MODEL
BODYRIG_SITH_DIFFUSION_SHA256
```

Without that switch, the settings are only exported to the PowerShell process that ran setup.

## Final gate

Provisioning only reports `PASS` after the same fail-closed SiTH preflight used by the built-in Stash clone succeeds and the diffusion-model tree digest is valid.

That means a `PASS` requires, among other things:

- exact SiTH Git revision;
- clean tracked checkout;
- pinned SiTH execution-file blobs;
- Torch 2.1.0;
- Torchvision 0.16.0;
- Kaolin 0.15.0;
- NumPy 1.24.1;
- CUDA visible from the SiTH Python environment;
- OpenCV, PIL, SMPL-X, Diffusers, Transformers, Trimesh, xatlas and nvdiffrast imports;
- both SiTH reconstruction checkpoints;
- all six SMPL-X files;
- OpenPose executable.

## Clone from Stash

After a successful persisted setup, the built-in high-fidelity path no longer needs hand-written identity/fitter configs:

```powershell
.\clone-body-from-stash.ps1 `
  -PerformerId 123 `
  -ExternalPython "C:\...\recovery\python.exe" `
  -FourDHumansRepo "C:\...\4D-Humans" `
  -BodyId "performer-123"
```

The default path is then:

```text
Stash performer
  -> ranked source files
  -> sparse observation selection
  -> hash-bound private segments
  -> recovery / BodyPrint
  -> built-in source-derived identity capture
  -> pinned SiTH stage + OpenPose + SMPL-X fit
  -> offline fixed-seed back-view diffusion
  -> textured UV reconstruction
  -> SMPL-X LBS transfer + inverse skinning
  -> VRM 1.0
  -> validated .mrbody
```

Private video segments, RGBA identity frames, SiTH staging data, model paths and SMPL-X working data remain build-time material and are not `.mrbody` payloads.
