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


def test_spatial_materializer_routes_exact_p0_replay_into_png_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_key = "scene:42:E:/spatial.mp4"
    expected_frame_sha = "e" * 64
    projection_authority = {
        "format": "bodyrig-photoreal-projection-authority",
        "version": 1,
        "mode": "vr180-equirectangular",
    }
    request = {
        "format": tool.REQUEST_FORMAT,
        "version": tool.REQUEST_VERSION,
        "benchmark_plan_sha256": "a" * 64,
        "teacher_input_sha256": "b" * 64,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "upstream_commit": tool.UPSTREAM_COMMIT,
        "source": {
            "source_key": source_key,
            "source_sha256": "c" * 64,
            "resolved_path": "/mnt/e/spatial.mp4",
            "kind": "video",
            "projection": "equi",
            "stereo_layout": "side-by-side",
            "decode_mode": "spatial-deprojection-required",
            "normalization_action": "exact-authorized-deprojection",
            "projection_authority": projection_authority,
        },
        "observations": [
            {
                "source_key": source_key,
                "frame_sha256": expected_frame_sha,
                "timestamp_seconds": 2.5,
                "eye": "left",
            }
        ],
        "held_out_evaluation_disclosed": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }

    class Image:
        shape = (4, 6, 3)

    image = Image()
    seen: dict[str, object] = {}

    class Base:
        @staticmethod
        def _frame_sha(value):
            assert value is image
            return expected_frame_sha

    class Adapter:
        base = Base()

    class FakeCv2:
        IMWRITE_PNG_COMPRESSION = 16

        @staticmethod
        def imwrite(path, value, params):
            assert value is image
            assert params == [16, 3]
            Path(path).write_bytes(b"png")
            return True

    runtime = type("Runtime", (), {"cv2": FakeCv2()})()

    def reproduce(adapter, supplied_runtime, source, observation, *, mesh_cache):
        seen["adapter"] = adapter
        seen["runtime"] = supplied_runtime
        seen["source"] = source
        seen["observation"] = observation
        seen["mesh_cache"] = mesh_cache
        return image

    replay = type(
        "Replay",
        (),
        {
            "adapter": Adapter(),
            "runtime": runtime,
            "reproduce": staticmethod(reproduce),
        },
    )()

    monkeypatch.setattr(tool, "_load_replay_runtime", lambda: (replay, runtime.cv2))

    output = tmp_path / "out"
    output.mkdir()
    receipt = tool.materialize(request, output)

    assert seen["source"]["projection"] == "equi"
    assert seen["source"]["decode_mode"] == "spatial-deprojection-required"
    assert seen["source"]["projection_authority"] == projection_authority
    assert seen["observation"] == {
        "source_key": source_key,
        "frame_sha256": expected_frame_sha,
        "timestamp_seconds": 2.5,
        "eye": "left",
    }
    assert receipt["frame_count"] == 1
    assert receipt["exact_p0_frame_hashes_reproduced"] is True
    assert receipt["held_out_evaluation_disclosed"] is False
    assert receipt["original_video_copied"] is False
    assert receipt["frames"][0]["source_frame_sha256"] == expected_frame_sha
    assert receipt["frames"][0]["eye"] == "left"
    assert (output / "frames" / "0.png").read_bytes() == b"png"
    assert (output / "frame_list_test.txt").read_text(encoding="utf-8") == ""
