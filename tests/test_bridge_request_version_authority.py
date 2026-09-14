from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from bodyrig.bridges import hmr2_4dhumans_bridge as hmr2_bridge
from bodyrig.bridges.opencv_identity_capture import _read_request as read_identity_request


INVALID_V1_VALUES = (True, False, "1", None, 2)
VALID_V1_VALUES = (1, 1.0)


def _identity_request(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-identity-capture-request",
        "version": version,
        "adapter": "opencv-identity-rgba",
        "revision": "1",
        "source_count": 1,
        "subject_track_id": "track-7",
        "observed_frames": 100,
    }


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_identity_capture_request_rejects_noncanonical_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_identity_request(version)), encoding="utf-8")

    with pytest.raises(RuntimeError, match="unsupported identity capture request"):
        read_identity_request(path, "opencv-identity-rgba", "1")


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_identity_capture_request_accepts_numeric_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_identity_request(version)), encoding="utf-8")

    loaded = read_identity_request(path, "opencv-identity-rgba", "1")
    assert loaded["version"] == 1


def _recovery_request(version: object, source: Path) -> dict[str, object]:
    return {
        "format": "bodyrig-recovery-request",
        "version": version,
        "sources": [str(source)],
    }


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_hmr2_recovery_request_rejects_noncanonical_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: object,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not-decoded-at-request-boundary")
    monkeypatch.setattr(
        hmr2_bridge.sys,
        "stdin",
        io.StringIO(json.dumps(_recovery_request(version, source))),
    )

    with pytest.raises(RuntimeError, match="unsupported recovery request"):
        hmr2_bridge._read_request()


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_hmr2_recovery_request_accepts_numeric_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: object,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not-decoded-at-request-boundary")
    monkeypatch.setattr(
        hmr2_bridge.sys,
        "stdin",
        io.StringIO(json.dumps(_recovery_request(version, source))),
    )

    assert hmr2_bridge._read_request() == [source.resolve()]
