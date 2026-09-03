from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bodyrig.bridges import hmr2_checkpoint_bridge as bridge
from bodyrig.bridges.hmr2_config import (
    ADAPTER_REVISION,
    FOUR_D_HUMANS_REVISION,
    NMR_REVISION,
    PHALP_REVISION,
    RECOVERY_MAX_FPS,
    RECOVERY_TEMPORAL_SAMPLING_POLICY,
    RECOVERY_TEMPORAL_SAMPLING_REVISION,
)


@pytest.mark.parametrize(
    ("source_fps", "expected_stride", "expected_effective_fps"),
    [
        (10.0, 1, 10.0),
        (15.0, 1, 15.0),
        (25.0, 2, 12.5),
        (29.97, 2, 14.985),
        (30.0, 2, 15.0),
        (60.0, 4, 15.0),
    ],
)
def test_recovery_sampling_caps_only_phalp_temporal_rate(
    monkeypatch: pytest.MonkeyPatch,
    source_fps: float,
    expected_stride: int,
    expected_effective_fps: float,
) -> None:
    monkeypatch.setattr(bridge.base, "_video_fps", lambda _source: source_fps)
    actual_fps, stride, effective_fps = bridge._sampling_details(Path("segment.mp4"))
    assert actual_fps == source_fps
    assert stride == expected_stride
    assert effective_fps == pytest.approx(expected_effective_fps)
    assert effective_fps <= RECOVERY_MAX_FPS


def test_observation_segment_materialization_remains_native() -> None:
    source = Path(__file__).resolve().parents[1] / "bodyrig" / "observation.py"
    text = source.read_text(encoding="utf-8")
    assert "OBSERVATION_SEGMENT_FPS" not in text
    assert "fps='min(" not in text
    assert '"-vf"' not in text


def test_recovery_sampling_materializes_only_every_nth_frame(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "segment.mp4"
    source.write_bytes(b"source-segment-bytes")
    destination = tmp_path / "sampled"

    class FakeCapture:
        def __init__(self, _path: str) -> None:
            self.index = 0

        def isOpened(self) -> bool:
            return self.index < 10

        def read(self):
            if self.index >= 10:
                return False, None
            frame = {"index": self.index}
            self.index += 1
            return True, frame

        def release(self) -> None:
            return None

    class FakeCv2:
        @staticmethod
        def VideoCapture(path: str) -> FakeCapture:
            return FakeCapture(path)

        @staticmethod
        def imwrite(path: str, frame) -> bool:
            Path(path).write_bytes(str(frame["index"]).encode("ascii"))
            return True

        @staticmethod
        def destroyAllWindows() -> None:
            return None

    monkeypatch.setitem(sys.modules, "cv2", FakeCv2)
    saved = bridge._materialize_recovery_frames(source, destination, sampling_stride=2)

    assert saved == 5
    assert [item.read_bytes() for item in sorted(destination.glob("*.jpg"))] == [b"0", b"2", b"4", b"6", b"8"]
    assert source.read_bytes() == b"source-segment-bytes"


def test_sampled_directory_still_uses_low_vram_phalp_launcher(tmp_path: Path) -> None:
    repo = tmp_path / "4D-Humans"
    sampled = tmp_path / "sampled-frames"
    output = tmp_path / "output"
    command = bridge._recovery_directory_track_command(repo, sampled, output)

    assert command[:3] == [sys.executable, "-c", bridge.base._PHALP_MP4_LOW_VRAM_LAUNCHER]
    assert str(repo / "track.py") in command
    assert any(str(sampled).replace("\\", "/") in item for item in command)
    assert "render.enable=false" in command
    assert "overwrite=true" in command


def test_sampling_policy_has_compact_versioned_adapter_identity() -> None:
    # The descriptive policy remains available in checkpoint/cache metadata.
    assert RECOVERY_TEMPORAL_SAMPLING_POLICY == "phalp-frame-stride-max-15fps-v1"
    # The wire revision must remain inside recovery-v1's 160-char contract while
    # preserving every exact dependency revision and a versioned sampling id.
    assert len(ADAPTER_REVISION) <= 160
    assert FOUR_D_HUMANS_REVISION in ADAPTER_REVISION
    assert PHALP_REVISION in ADAPTER_REVISION
    assert NMR_REVISION in ADAPTER_REVISION
    assert f"s:{RECOVERY_TEMPORAL_SAMPLING_REVISION}" in ADAPTER_REVISION
