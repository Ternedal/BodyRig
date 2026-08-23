# HMR2 / 4D-Humans recovery bridge

BodyRig V1 uses 4D-Humans/HMR2 + PHALP as the first concrete video recovery candidate, but keeps it outside the stable BodyRig Python runtime.

## Pinned upstream revisions

- `shubham-goel/4D-Humans`: `efe18deff163b29dff87ddbd575fa29b716a356c`
- `brjathu/PHALP`: `96f7e6c09fb858ec3f597d59246c151ab4394bc3`
- expected Git blob for `phalp/trackers/PHALP.py`: `f4258ab37f2cf034e7321f7ec48ef61be6001785`

The bridge requires the 4D-Humans checkout to be at the exact commit **and have no modified tracked files**. The installed PHALP tracker source must match the pinned Git blob; CRLF↔LF working-tree normalization is the only tolerated byte-level difference for Windows compatibility.

4D-Humans documents Python 3.10/conda or pip setup, automatically downloaded checkpoints, an additionally required neutral SMPL model, and `track.py video.source=...` for video tracking. BodyRig does **not** redistribute the separately licensed SMPL model asset.

## Preflight

```powershell
bodyrig-recovery-preflight `
  --python "C:\path\to\4dh-python.exe" `
  --repo "C:\path\to\4D-Humans" `
  --out ".\bodyrig-recovery-preflight.json"
```

The preflight fails closed unless the Git pin/cleanliness, neutral SMPL file, external imports, PHALP source identity and CUDA gate all pass (`--allow-cpu` explicitly relaxes only CUDA).

## Process boundary

The bridge lives inside the installable BodyRig package at `bodyrig/bridges/hmr2_4dhumans_bridge.py`. It can be executed by the external Python directly from disk and bootstraps the surrounding BodyRig pure-Python modules.

For each source the bridge creates a private temporary output directory, invokes upstream `track.py`, and loads only the result pickle generated there by that invocation. Arbitrary user-supplied pickle input is never accepted.

## Joint mapping

4D-Humans' SMPL wrapper maps the first 25 returned joints into OpenPose BODY_25 order. BodyRig uses head-reference/nose (0), shoulders (2/5), wrists (4/7), hips (9/12) and ankles (11/14). The nose is not treated as absolute top-of-head height, so V1 derives normalized proportions rather than absolute height. PHALP prediction frames with `tracked_time != 0` are excluded from learning.

## First physical proof command

```powershell
bodyrig-recover `
  --python "C:\path\to\4dh-python.exe" `
  --repo "C:\path\to\4D-Humans" `
  --out ".\bodyrig-recovery-proof.json" `
  "C:\video\person.mp4"
```

For multiple tracked people the command fails closed and lists candidate ids; rerun with `--track-id s00-tN`.

## Remaining physical gate

The bridge/conversion logic is CI-testable without the ML runtime, but the feature is not accepted until the target Windows/NVIDIA rig proves a real video can execute through the pinned environment and produce the proof JSON.
