# HMR2 / 4D-Humans recovery bridge

BodyRig V1 uses 4D-Humans/HMR2 + PHALP as the first concrete video recovery candidate, but keeps it outside the stable BodyRig Python runtime.

## Pinned upstream revisions

- `shubham-goel/4D-Humans`: `efe18deff163b29dff87ddbd575fa29b716a356c`
- `brjathu/PHALP`: `96f7e6c09fb858ec3f597d59246c151ab4394bc3`
- expected Git blob for `phalp/trackers/PHALP.py`: `f4258ab37f2cf034e7321f7ec48ef61be6001785`

The bridge requires the 4D-Humans checkout to be exactly pinned and independently computes Git's blob SHA-1 for the installed PHALP tracker source. A merely claimed PHALP version is not accepted.

4D-Humans documents Python 3.10/conda or pip setup, automatically downloaded checkpoints, an additionally required neutral SMPL model, and `track.py video.source=...` for video tracking. BodyRig does **not** redistribute the separately licensed SMPL model asset.

## Preflight

Before using a real video, validate the external recovery environment:

```powershell
bodyrig-recovery-preflight `
  --python "C:\path\to\4dh-python.exe" `
  --repo "C:\path\to\4D-Humans" `
  --out ".\bodyrig-recovery-preflight.json"
```

The preflight fails closed unless:

- the 4D-Humans checkout is at the pinned Git commit;
- the required neutral SMPL file exists under `data/`;
- `torch`, `cv2`, `joblib`, `hmr2` and `phalp` import in the external Python;
- the installed PHALP tracker source hashes to the pinned Git blob;
- CUDA is available (unless `--allow-cpu` is explicitly supplied).

## Process boundary

The bridge lives inside the installable BodyRig package at `bodyrig/bridges/hmr2_4dhumans_bridge.py`. It can be executed by the external Python directly from disk; it bootstraps the surrounding BodyRig pure-Python modules without requiring the full BodyRig service dependencies to be installed in the heavy recovery environment.

BodyRig core uses `JsonCommandRecoveryAdapter`: request JSON arrives on stdin, canonical recovery JSON leaves on stdout, and upstream progress goes to stderr.

For each source the bridge creates a private temporary output directory, invokes upstream `track.py`, and loads only the result pickle generated there by that invocation. Arbitrary user-supplied pickle input is never accepted.

## Joint mapping

Upstream PHALP stores each detection's `3d_joints`. 4D-Humans' `SMPL` wrapper explicitly maps the first 25 returned joints into OpenPose BODY_25 order. BodyRig consumes only this stable subset:

```text
BODY_25 0  -> head reference (nose)
BODY_25 2  -> right_shoulder
BODY_25 4  -> right_wrist
BODY_25 5  -> left_shoulder
BODY_25 7  -> left_wrist
BODY_25 9  -> right_hip
BODY_25 11 -> right_ankle
BODY_25 12 -> left_hip
BODY_25 14 -> left_ankle
```

The nose is a head reference, not absolute top-of-head height. V1 therefore derives normalized proportions, not absolute height, from this monocular path. PHALP frames with `tracked_time != 0` are tracker predictions and are excluded from bodyprint learning.

## First physical proof command

```powershell
bodyrig-recover `
  --python "C:\path\to\4dh-python.exe" `
  --repo "C:\path\to\4D-Humans" `
  --out ".\bodyrig-recovery-proof.json" `
  "C:\video\person.mp4"
```

For multiple tracked people the command fails closed and lists candidate ids; rerun with `--track-id s00-tN`.

The proof contains no source filename, only source count, pinned adapter identity, selected track id, observed frame count and extracted bodyprint.

## Remaining physical gate

The bridge and conversion logic are CI-testable without the ML runtime, but the feature is not accepted until the target Windows/NVIDIA rig proves a real video can execute through the pinned environment and produce the proof JSON.
