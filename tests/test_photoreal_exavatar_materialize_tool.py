from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_exavatar_materialize.py"
SPEC = importlib.util.spec_from_file_location("bodyrig_test_exavatar_materialize_tool", TOOL)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def _request(observations: list[dict[str, object]]) -> dict[str, object]:
    return {
        "format": tool.REQUEST_FORMAT,
        "version": tool.REQUEST_VERSION,
        "benchmark_plan_sha256": "a" * 64,
        "teacher_input_sha256": "b" * 64,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "upstream_commit": tool.UPSTREAM_COMMIT,
        "source": {
            "source_key": "scene:42:E:/stereo.mp4",
            "source_sha256": "c" * 64,
            "resolved_path": "/mnt/e/stereo.mp4",
            "kind": "video",
            "projection": "flat",
            "stereo_layout": "side-by-side",
            "decode_mode": "rectilinear-stereo-split",
            "normalization_action": "exact-authorized-deprojection",
            "projection_authority": None,
        },
        "observations": observations,
        "held_out_evaluation_disclosed": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }


def test_same_frame_and_timestamp_remain_distinct_across_stereo_eyes() -> None:
    observations = [
        {
            "source_key": "scene:42:E:/stereo.mp4",
            "frame_sha256": "d" * 64,
            "timestamp_seconds": 1.25,
            "eye": "left",
        },
        {
            "source_key": "scene:42:E:/stereo.mp4",
            "frame_sha256": "d" * 64,
            "timestamp_seconds": 1.25,
            "eye": "right",
        },
    ]

    _source, normalized = tool._validate_request(_request(observations))

    assert [(item["eye"], item["frame_sha256"]) for item in normalized] == [
        ("left", "d" * 64),
        ("right", "d" * 64),
    ]


def test_exact_same_stereo_observation_is_still_rejected() -> None:
    observation = {
        "source_key": "scene:42:E:/stereo.mp4",
        "frame_sha256": "d" * 64,
        "timestamp_seconds": 1.25,
        "eye": "left",
    }

    with pytest.raises(tool.ExAvatarMaterializeError, match="repeats observation"):
        tool._validate_request(_request([observation, dict(observation)]))


def test_materializer_capture_pool_reuses_capture_until_batch_close() -> None:
    class RawCapture:
        def __init__(self) -> None:
            self.release_count = 0

        def isOpened(self) -> bool:
            return True

        def set(self, *_args):
            return True

        def read(self):
            return True, object()

        def release(self) -> None:
            self.release_count += 1

    class BaseCv2:
        def __init__(self) -> None:
            self.created: list[RawCapture] = []

        def VideoCapture(self, _path):
            capture = RawCapture()
            self.created.append(capture)
            return capture

    base = BaseCv2()
    pool = tool._CaptureReuseCv2(base)

    first = pool.VideoCapture("/video/source.mp4")
    first.release()
    second = pool.VideoCapture("/video/source.mp4")

    assert first is second
    assert len(base.created) == 1
    assert base.created[0].release_count == 0

    pool.close()

    assert base.created[0].release_count == 1


def test_materializer_capture_pool_invalidates_failed_capture() -> None:
    class RawCapture:
        def __init__(self, *, ok: bool) -> None:
            self.ok = ok
            self.release_count = 0

        def isOpened(self) -> bool:
            return True

        def set(self, *_args):
            return True

        def read(self):
            return (self.ok, object() if self.ok else None)

        def release(self) -> None:
            self.release_count += 1

    class BaseCv2:
        def __init__(self) -> None:
            self.created: list[RawCapture] = []

        def VideoCapture(self, _path):
            capture = RawCapture(ok=bool(self.created))
            self.created.append(capture)
            return capture

    base = BaseCv2()
    pool = tool._CaptureReuseCv2(base)

    first = pool.VideoCapture("/video/source.mp4")
    assert first.read() == (False, None)
    assert base.created[0].release_count == 1

    second = pool.VideoCapture("/video/source.mp4")
    assert second is not first
    assert second.read()[0] is True
    assert len(base.created) == 2

    pool.close()
    assert base.created[1].release_count == 1
