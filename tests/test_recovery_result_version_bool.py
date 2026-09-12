from __future__ import annotations

import pytest

from bodyrig.recovery import RecoveryError, parse_recovery_result


def _result(*, version: object = 1) -> dict[str, object]:
    return {
        "format": "bodyrig-recovery",
        "version": version,
        "adapter": "fixture",
        "revision": "r1",
        "tracks": [
            {
                "track_id": "track-1",
                "frames": [
                    {"timestamp_ms": 0, "joints": {"head": [0, 1, 0]}},
                    {"timestamp_ms": 1, "joints": {"head": [0, 1, 0]}},
                ],
            }
        ],
    }


def test_recovery_result_rejects_boolean_version() -> None:
    with pytest.raises(RecoveryError, match="unsupported recovery format/version"):
        parse_recovery_result(_result(version=True))


def test_recovery_result_preserves_numeric_v1_compatibility() -> None:
    parsed = parse_recovery_result(_result(version=1.0), expected_adapter="fixture")

    assert parsed.adapter == "fixture"
    assert parsed.revision == "r1"
    assert len(parsed.tracks) == 1
    assert len(parsed.tracks[0].frames) == 2
