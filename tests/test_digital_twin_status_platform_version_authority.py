from __future__ import annotations

import pytest

from bodyrig.digital_twin_status import _platform_acceptance_gate


INVALID_V1_VALUES = (True, False, "1", None, 2)
VALID_V1_VALUES = (1, 1.0)


def _m5_status(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-digital-twin-platform-status",
        "version": version,
        "m5_ready": True,
        "digital_twin_ready": False,
        "production_activation": False,
        "platforms": {
            "windows-unity-univrm": {
                "ready": True,
                "state": "complete",
                "realization_sha256": "a" * 64,
            },
            "android-quest-class": {
                "ready": True,
                "state": "complete",
                "realization_sha256": "b" * 64,
            },
        },
    }


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_m5_platform_status_rejects_noncanonical_v1(version: object) -> None:
    gate = _platform_acceptance_gate(_m5_status(version))

    assert gate == {
        "ready": False,
        "state": "blocked",
        "blockers": ["M5 platform acceptance status format/version is invalid"],
    }


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_m5_platform_status_accepts_numeric_v1(version: object) -> None:
    gate = _platform_acceptance_gate(_m5_status(version))

    assert gate == {
        "ready": True,
        "state": "complete",
        "blockers": [],
        "windows_realization_sha256": "a" * 64,
        "quest_realization_sha256": "b" * 64,
    }
