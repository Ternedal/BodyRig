# HMR2 / 4D-Humans recovery bridge

BodyRig V1 uses 4D-Humans/HMR2 + PHALP as the first concrete video recovery candidate, but keeps it outside the stable BodyRig Python runtime.

## Pinned upstream revisions

- `shubham-goel/4D-Humans`: `efe18deff163b29dff87ddbd575fa29b716a356c`
- `brjathu/PHALP`: `96f7e6c09fb858ec3f597d59246c151ab4394bc3`

The bridge refuses a 4D-Humans checkout at another Git HEAD. PHALP is recorded in the adapter revision and must be installed at the pinned revision when the external environment is provisioned.

4D-Humans itself documents Python 3.10/conda or pip setup, automatically downloaded checkpoints, an additionally required neutral SMPL model, and `track.py video.source=...` for video tracking. Its tracking output is a PHALP `.pkl` containing 3D pose/shape. BodyRig does not redistribute that SMPL asset.

## Process boundary

BodyRig core invokes:

```text
<4dh-python> bridges/hmr2_4dhumans_bridge.py --repo <pinned-4D-Humans-checkout>
```

using `JsonCommandRecoveryAdapter`. Request JSON arrives on stdin and canonical recovery JSON leaves on stdout. All upstream progress/logging goes to stderr.

For each source file the bridge creates a private temporary output directory, invokes upstream `track.py`, and loads only the result pickle generated in that directory by that invocation. Arbitrary user-supplied pickle input is never accepted.

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

The nose is deliberately treated as a *head reference*, not a claim about absolute top-of-head height. Therefore V1 derives normalized proportions, not absolute human height, from this monocular path.

PHALP result frames with `tracked_time != 0` are tracker predictions across missed observations and are discarded for bodyprint learning. BodyRig only learns source motion from observed frames.

## Remaining physical gate

This bridge is structurally testable without installing the heavy ML runtime, but it is not accepted until the target Windows/NVIDIA rig proves a real video can run through the pinned external environment and produce canonical BodyRig tracks.
