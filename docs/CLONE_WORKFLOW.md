# BodyRig one-command clone workflow

`clone-body.ps1` is the normal Windows build path for a high-fidelity BodyRig profile.

The operator supplies source clips and the locally configured recovery/capture/fitter environments; BodyRig handles the intermediate contracts.

## Run

```powershell
.\clone-body.ps1 `
  -Source "C:\video\person-1.mp4","C:\video\person-2.mp4" `
  -ExternalPython "C:\Users\you\AppData\Local\BodyRig\recovery\conda-env\python.exe" `
  -FourDHumansRepo "C:\Users\you\AppData\Local\BodyRig\recovery\4D-Humans" `
  -IdentityCaptureConfig ".\identity-capture-config.json" `
  -FitterConfig ".\high-fidelity-fitter-config.json" `
  -BodyId "person-a" `
  -Name "Person A"
```

When more than one person is detected, rerun with the explicit recovery track:

```powershell
-TrackId "7"
```

## Internal flow

The command executes:

```text
1. pinned recovery preflight
2. source video -> recovery proof / BodyPrint
3. same source files + selected track -> visual identity capture
4. private identity workspace -> isolated high-fidelity fitter
5. returned VRM/thumbnail -> BodyRig byte + VRM validation
6. normal .mrbody package build + final package validation
```

The portable output directory contains only bounded BodyRig artifacts such as:

```text
bodyrig-recovery-preflight.json
bodyrig-recovery-proof.json
bodyrig-visual-identity.json
person-a.mrbody
```

Source filenames are not written into the recovery proof, visual identity profile or `.mrbody` provenance.

## Private workspace lifecycle

Identity capture can require derived face crops, segmentation, texture observations or other engine-private files. These live in a separate private workspace, never in `.mrbody`.

By default `clone-body.ps1` deletes the private workspace after **both success and failure**.

Use this only when development/debugging genuinely requires the intermediates:

```powershell
-KeepPrivateWorkspace
```

A custom new workspace may be supplied with:

```powershell
-PrivateWorkspace "D:\Private\BodyRig\person-a-run-001"
```

An existing workspace is refused to prevent identity material from two runs/subjects being mixed.

## Output safety

The clone output directory is also create-only. BodyRig refuses an existing output directory rather than mixing evidence from separate clone attempts.

The final `.mrbody` is re-opened through BodyRig's normal package validator before the command reports PASS.

## What the command does not hide

The command makes the UX simple; it does not pretend the external research stack disappeared.

A high-fidelity fitter still has to be installed/configured separately, and its software/model/body-model licensing remains its own dependency concern. BodyRig stores only adapter/revision provenance in the portable profile — not the local command, Python environment, checkpoint path or private workspace.

Until a real identity adapter has passed issue #4 and the Windows/Quest physical gates, the existing `procedural-vrm1` path remains the only built-in fitter and is explicitly a placeholder rather than an identity clone.
