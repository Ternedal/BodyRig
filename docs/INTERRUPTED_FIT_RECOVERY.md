# Interrupted physical SiTH fit recovery

BodyRig can recover a production physical clone when the physical session failed in the `clone` stage **after a complete SiTH reconstruction authority was written**, without repeating recovery, OpenPose, SMPL-X reconstruction or diffusion reconstruction.

This is operational recovery, not acceptance. The recovered `.mrbody` still requires Gate A and human visual authority exactly like a normal physical clone.

## Why this exists

A production SiTH fit can take hours. The canonical fidelity runner starts the clone with `-KeepPrivateWorkspace`, so an interrupted fit retains the private identity workspace. The Stash clone output also writes the recovery proof, visual identity, portable identity and SiTH fitter config before the external fitter completes.

`resume-interrupted-physical-fit.ps1` verifies those durable artifacts, starts a **new** physical clone session, runs live rig readiness again, and resumes only the existing external SiTH fitter against the retained workspace.

## Hard recovery boundary

Recovery is refused unless all of the following are true:

- the previous physical session strictly validates as `status=fail`, `stage=clone`;
- the failed session belongs to the exact current clean BodyRig Git revision;
- the current rig-setup bytes equal the failed session's rig-setup hash;
- the Stash performer/body binding is unchanged;
- recovery proof, visual identity, portable identity and fitter config strictly validate;
- the fitter is the production `sith-smplx-vrm` revision 1 adapter;
- `<identity-workspace>/sith-input-v1/reconstruction.json` already exists;
- the reconstruction authority hash remains byte-identical before and after the resumed fit;
- no complete package already occupies the canonical package path.

The recovery command never calls the full clone pipeline, recovery model, identity capture or source selection again.

## Operator command

Use the exact failed session, outer Stash clone output and retained identity workspace reported by the failed run:

```powershell
pwsh .\resume-interrupted-physical-fit.ps1 `
  -FailedSessionReport "<failed physical session.json>" `
  -CloneOutput "<rebuild-NN\clone-run>" `
  -IdentityWorkspace "<retained BodyRig identity-workspace>"
```

To run Gate A immediately after successful recovery:

```powershell
pwsh .\resume-interrupted-physical-fit.ps1 `
  -FailedSessionReport "<failed physical session.json>" `
  -CloneOutput "<rebuild-NN\clone-run>" `
  -IdentityWorkspace "<retained BodyRig identity-workspace>" `
  -GateAOutputDir "<rebuild-NN\full\acceptance>"
```

`STASH_URL`, `STASH_API_KEY` (or the selected `-ApiKeyEnv`) and the canonical rig setup must still be available because recovery creates a new physical session and reruns live readiness before resuming the fit.

## Evidence

On success BodyRig writes:

- a new physical clone PASS session bound to the recovered clone output;
- `interrupted-fit-recovery.json`, binding old/new session hashes, package hash, canonical body identity and all recovery-authority hashes;
- optional Gate A evidence when `-GateAOutputDir` is supplied.

The recovery receipt explicitly states:

- `expensive_reconstruction_rerun=false`;
- `resumed_fit_only=true`;
- `human_visual_authority_required=true`;
- `production_activation=false`.

A recovery failure marks the new recovery session FAIL when it has already started. A failed recovery never writes release/Quest/production activation authority.
