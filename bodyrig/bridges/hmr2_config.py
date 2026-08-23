from __future__ import annotations

from pathlib import Path

FOUR_D_HUMANS_REVISION = "efe18deff163b29dff87ddbd575fa29b716a356c"
PHALP_REVISION = "96f7e6c09fb858ec3f597d59246c151ab4394bc3"
ADAPTER_NAME = "4dhumans-hmr2-phalp"
ADAPTER_REVISION = f"4dh:{FOUR_D_HUMANS_REVISION};phalp:{PHALP_REVISION}"


def bridge_script_path() -> Path:
    return Path(__file__).with_name("hmr2_4dhumans_bridge.py")
