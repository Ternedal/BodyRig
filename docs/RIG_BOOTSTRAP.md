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

## Canonical Windows BodyRig Python runtime

`pyproject.toml` intentionally keeps compatibility ranges for normal development and packaging. The physical Windows rig uses the stricter operator lock in `requirements/windows-python.lock.txt`.

After checking out the exact target revision, `update-windows.ps1` verifies the repo-local `.venv` before deciding whether package installation is necessary. `bodyrig.runtime_lock` proves CPython 3.11 plus every exact locked distribution version. On revisions that contain `bodyrig.install_authority`, a second probe proves that the installed BodyRig distribution is editable-bound to this exact checkout and that its installed version + console-script metadata exactly match the active `pyproject.toml`.

If both probes pass, the updater skips the redundant `pip install -e ".[test]"`. If either probe fails, it refreshes the `.venv` using `requirements/windows-python.lock.txt` as the pip constraints authority. The runtime lock is always revalidated after this decision, and new revisions always revalidate editable-install authority before service launch. Historical evidence revisions that predate the install-authority probe use the conservative locked pip-install path rather than being made unrecoverable by newer tooling.

`check-rig-ready.ps1` repeats the runtime-lock validation immediately before live recovery/SiTH/Stash readiness. A later package upgrade or a different Python minor therefore blocks canonical physical work even if an older rig-setup report still exists.

The lock and editable-install checks are software/runtime authority only. They do not turn CI into physical or human fidelity evidence.

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

The bootstrap also rehydrates the validated `BODYRIG_SITH_*` values into its own PowerShell environment after the isolated high-fidelity setup process returns. With `-PersistUserEnvironment`, the SiTH settings plus `BODYRIG_RIG_SETUP_REPORT` are saved for the current Windows user.

## Normal clone after bootstrap

After bootstrap completes with `READY`, the shortest Stash path is:

```powershell
.\clone-body-from-stash-ready.ps1 `
  -PerformerId <stash-performer-id> `
  -BodyId <body-id>
```

The ready-rig launcher resolves `BODYRIG_RIG_SETUP_REPORT` (or `%LOCALAPPDATA%\BodyRig\bodyrig-rig-setup.json`), revalidates all nested byte-bound setup evidence, rehydrates the SiTH settings and then invokes the existing `clone-body-from-stash.ps1` with the recovery Python and 4D-Humans checkout from the verified master report.

It is deliberately only a launcher. Recovery, observation selection, identity capture, high-fidelity fitting and `.mrbody` packaging still happen in the single existing Stash clone pipeline.

If a non-default master report is required:

```powershell
.\clone-body-from-stash-ready.ps1 `
  -RigSetupReport "D:\BodyRig\bodyrig-rig-setup.json" `
  -PerformerId <stash-performer-id> `
  -BodyId <body-id>
```

The clone path still runs live recovery/SiTH/model-integrity preflights. The master setup report is evidence and convenience; it never bypasses the physical gates.
