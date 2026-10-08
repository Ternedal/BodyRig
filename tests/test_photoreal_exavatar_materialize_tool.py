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


def test_spatial_materialization_rejects_mixed_stereo_eyes() -> None:
    request = _request(
        [
            {
                "source_key": "scene:42:E:/stereo.mp4",
                "frame_sha256": "d" * 64,
                "timestamp_seconds": 1.25,
                "eye": "left",
            },
            {
                "source_key": "scene:42:E:/stereo.mp4",
                "frame_sha256": "e" * 64,
                "timestamp_seconds": 1.25,
                "eye": "right",
            },
        ]
    )
    request["source"]["projection"] = "equi"
    request["source"]["decode_mode"] = "spatial-deprojection-required"
    request["source"]["projection_authority"] = {
        "format": "bodyrig-explicit-projection-authority",
        "version": 1,
        "projection_type": "equi",
        "deprojection_authority": False,
        "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "equirectangular_bounds_fraction": {
            "top": 0.0,
            "bottom": 0.5,
            "left": 0.0,
            "right": 0.5,
        },
    }

    with pytest.raises(
        tool.ExAvatarMaterializeError,
        match="requires a single stereo eye",
    ):
        tool._validate_request(request)


def test_exact_same_stereo_observation_is_still_rejected() -> None:
    observation = {
        "source_key": "scene:42:E:/stereo.mp4",
        "frame_sha256": "d" * 64,
        "timestamp_seconds": 1.25,
        "eye": "left",
    }

    request = _request([observation, dict(observation)])
    request["source"].update({
        "projection": "equi",
        "decode_mode": "spatial-deprojection-required",
        "projection_authority": {"format": "bodyrig-explicit-projection-authority"},
    })
    with pytest.raises(tool.ExAvatarMaterializeError, match="repeats observation"):
        tool._validate_request(request)



def test_materializer_does_not_replace_reference_cv2_capture_lifetime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_key = "scene:42:E:/flat.mp4"
    expected_frame_sha = "e" * 64
    request = _request(
        [
            {
                "source_key": source_key,
                "frame_sha256": expected_frame_sha,
                "timestamp_seconds": 2.5,
                "eye": "mono",
            }
        ]
    )
    request["source"].update(
        {
            "source_key": source_key,
            "projection": "flat",
            "stereo_layout": "mono",
            "decode_mode": "rectilinear-mono",
            "normalization_action": "preserve-flat-mono-video",
            "projection_authority": None,
        }
    )

    class Image:
        shape = (4, 6, 3)

    image = Image()

    class Base:
        @staticmethod
        def _frame_sha(value):
            assert value is image
            return expected_frame_sha

    class Adapter:
        base = Base()

        @staticmethod
        def _read_frame_sample(runtime, source, sample):
            assert runtime.cv2 is original_cv2
            return image, False

    class FakeCv2:
        IMWRITE_PNG_COMPRESSION = 16

        @staticmethod
        def imwrite(path, value, params):
            assert value is image
            Path(path).write_bytes(b"png")
            return True

    class FakeNp:
        @staticmethod
        def ascontiguousarray(value):
            return value

    runtime = type("Runtime", (), {"cv2": FakeCv2(), "np": FakeNp()})()
    original_cv2 = runtime.cv2
    replay = type(
        "Replay",
        (),
        {
            "adapter": Adapter(),
            "runtime": runtime,
        },
    )()

    monkeypatch.setattr(tool, "_load_replay_runtime", lambda: (replay, runtime.cv2))
    output = tmp_path / "out"
    output.mkdir()

    receipt = tool.materialize(request, output)

    assert runtime.cv2 is original_cv2
    assert receipt["frames"][0]["camera"] is None



def test_spatial_materializer_routes_exact_p0_replay_into_png_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_key = "scene:42:E:/spatial.mp4"
    expected_frame_sha = "e" * 64
    projection_authority = {
        "format": "bodyrig-explicit-projection-authority",
        "version": 1,
        "projection_type": "equi",
        "deprojection_authority": False,
        "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "equirectangular_bounds_fraction": {
            "top": 0.0,
            "bottom": 0.5,
            "left": 0.0,
            "right": 0.75,
        },
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
        shape = (768, 768, 3)

    source_image = object()
    image = Image()

    class Base:
        @staticmethod
        def _frame_sha(value):
            assert value is image
            return expected_frame_sha

        @staticmethod
        def deproject_equirectangular_views(runtime, source_value, authority):
            assert source_value is source_image
            assert authority == projection_authority
            return [("v00", image)]

    class Adapter:
        base = Base()

        @staticmethod
        def _read_frame_sample(runtime, source, sample):
            assert source["projection"] == "equi"
            assert sample == {"timestamp_seconds": 2.5, "eye": "left"}
            return source_image, True

    class FakeCv2:
        IMWRITE_PNG_COMPRESSION = 16

        @staticmethod
        def imwrite(path, value, params):
            assert value is image
            assert params == [16, 3]
            Path(path).write_bytes(b"png")
            return True

    class FakeNp:
        @staticmethod
        def ascontiguousarray(value):
            return value

    runtime = type("Runtime", (), {"cv2": FakeCv2(), "np": FakeNp()})()
    replay = type("Replay", (), {"adapter": Adapter(), "runtime": runtime})()
    monkeypatch.setattr(tool, "_load_replay_runtime", lambda: (replay, runtime.cv2))

    output = tmp_path / "out"
    output.mkdir()
    receipt = tool.materialize(request, output)

    frame = receipt["frames"][0]
    assert receipt["frame_count"] == 1
    assert receipt["exact_p0_frame_hashes_reproduced"] is True
    assert frame["source_frame_sha256"] == expected_frame_sha
    assert frame["eye"] == "left"
    assert frame["camera"]["format"] == "bodyrig-exavatar-tangent-camera"
    assert frame["camera"]["viewport_id"] == "v00"
    assert frame["camera"]["horizontal_fov_degrees"] == 90.0
    assert frame["camera"]["focal"] == [384.0, 384.0]
    assert frame["camera"]["princpt"] == [384.0, 384.0]
    assert frame["camera"]["translation_authority"] is False
    assert (output / "frames" / "0.png").read_bytes() == b"png"
    assert (output / "frame_list_test.txt").read_text(encoding="utf-8") == ""

