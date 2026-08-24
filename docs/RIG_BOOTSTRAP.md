# One-command BodyRig rig bootstrap

For a new Windows BodyRig machine, the preferred setup entry point is `setup-rig-windows.ps1`. It provisions and verifies both build stacks in order:

```text
Windows recovery
  4D-Humans + PHALP + recovery Python + neutral SMPL

WSL high fidelity
  SiTH + OpenPose + SMPL-X + local diffusion model

        ↓
bodyrig-rig-setup v1
```

Example:

```powershell
.\setup-rig-windows.ps1 `
  -SmplModelPath "C:\licensed-assets\basicModel_neutral_lbs_10_207_0_v1.0.0.pkl" `
  -SmplxSource "C:\licensed-assets\smplx" `
  -DiffusionModel "/home/<user>/.cache/bodyrig/sith-diffusion" `
  -ProvisionOpenPose `
  -DownloadPublicCheckpoints `
  -PersistUserEnvironment
```

Prerequisites that BodyRig deliberately does not silently install or redistribute:

- Miniconda/Conda or Mamba on Windows for the pinned recovery environment;
- WSL Ubuntu with CUDA visible;
- `git`, `cmake`, `make` and `nvcc` in WSL when `-ProvisionOpenPose` is used;
- the neutral SMPL asset supplied with `-SmplModelPath`;
- the required SMPL-X assets supplied with `-SmplxSource`;
- a local SiTH diffusion-model directory supplied with `-DiffusionModel`.

`-DownloadPublicCheckpoints` only concerns the two public SiTH checkpoints expected by the pinned upstream revision. It does not download SMPL/SMPL-X assets or the diffusion-model directory.

## Evidence output

The bootstrap requires the existing recovery provisioner to produce:

```text
%LOCALAPPDATA%\BodyRig\recovery\bodyrig-recovery-environment.json
%LOCALAPPDATA%\BodyRig\recovery\bodyrig-recovery-preflight.json
```

and the high-fidelity provisioner to produce:

```text
%LOCALAPPDATA%\BodyRig\sith\setup-report.json
```

It then writes:

```text
%LOCALAPPDATA%\BodyRig\bodyrig-rig-setup.json
```

The final report records SHA-256 for all three nested evidence files and the exact Windows recovery paths needed by the physical clone flow. `bodyrig.rig_setup` re-opens and verifies the nested reports, pinned 4D-Humans/PHALP revisions, recovery `ok=true`, SMPL presence and the strict SiTH/OpenPose setup report before the master report is committed.

With `-PersistUserEnvironment`, `BODYRIG_RIG_SETUP_REPORT` and the existing `BODYRIG_SITH_*` settings are saved for the current Windows user.

## First clone

After bootstrap completes with `READY`, use the recovery paths printed by the script:

```powershell
.\clone-body-from-stash.ps1 `
  -PerformerId <stash-performer-id> `
  -ExternalPython "<recovery python from bootstrap>" `
  -FourDHumansRepo "<4D-Humans repo from bootstrap>" `
  -BodyId <body-id>
```

The clone path still runs live recovery/SiTH/model-integrity preflights. The master setup report is evidence and convenience; it never bypasses the physical gates.
