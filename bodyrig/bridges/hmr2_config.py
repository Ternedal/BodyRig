from __future__ import annotations

from pathlib import Path

FOUR_D_HUMANS_REVISION = "efe18deff163b29dff87ddbd575fa29b716a356c"
PHALP_REVISION = "96f7e6c09fb858ec3f597d59246c151ab4394bc3"
# Git blob identity of phalp/trackers/PHALP.py at the pinned PHALP revision.
PHALP_TRACKER_BLOB_SHA1 = "f4258ab37f2cf034e7321f7ec48ef61be6001785"
NMR_REVISION = "e990b3c70f48d39231f607c79d76ce3db4bf7483"
NMR_REMOTE = "https://github.com/shubham-goel/NMR.git"
RECOVERY_MAX_FPS = 15.0
RECOVERY_TEMPORAL_SAMPLING_POLICY = "phalp-frame-stride-max-15fps-v1"
ADAPTER_NAME = "4dhumans-hmr2-phalp"
ADAPTER_REVISION = (
    f"4dh:{FOUR_D_HUMANS_REVISION};phalp:{PHALP_REVISION};nmr:{NMR_REVISION};"
    f"sampling:{RECOVERY_TEMPORAL_SAMPLING_POLICY}"
)


def bridge_script_path() -> Path:
    # Production recovery remains routed through the cross-job resume layer.
    # The resume wrapper delegates per-source execution to the checkpoint layer,
    # whose revision above also binds the recovery-only temporal sampling policy.
    return Path(__file__).with_name("hmr2_resume_bridge.py")
