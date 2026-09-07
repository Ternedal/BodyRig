from __future__ import annotations

from pathlib import Path

import bodyrig.bridges.hmr2_checkpoint_bridge as checkpoint_bridge
from bodyrig.bridges.hmr2_config import bridge_script_path


SOURCE_FPS = 30.0
SAMPLING_STRIDE = 2
EFFECTIVE_FPS = 15.0


def _tracks():
    return [
        {
            "track_id": "s00-t1",
            "frames": [
                {
                    "timestamp_ms": 0,
                    "confidence": 1.0,
                    "joints": {"head": [0.0, 1.0, 0.0]},
                },
                {
                    "timestamp_ms": 67,
                    "confidence": 1.0,
                    "joints": {"head": [0.0, 1.0, 0.0]},
                },
            ],
        }
    ]


def test_production_bridge_routes_through_resume_and_checkpoint_layers():
    assert bridge_script_path().name == "hmr2_resume_bridge.py"


def test_completed_segment_is_reused_without_restarting_4d_humans(monkeypatch, tmp_path):
    source = tmp_path / "segment-01.mp4"
    source.write_bytes(b"stable observation bytes")
    root = checkpoint_bridge._checkpoint_root(source)
    source_sha256 = checkpoint_bridge.base._sha256_file(source)
    expected = _tracks()
    monkeypatch.setattr(checkpoint_bridge.base, "_video_fps", lambda _source: SOURCE_FPS)

    checkpoint_bridge._publish_canonical_checkpoint(
        root,
        source_index=0,
        source_sha256=source_sha256,
        source_fps=SOURCE_FPS,
        sampling_stride=SAMPLING_STRIDE,
        effective_fps=EFFECTIVE_FPS,
        tracks=expected,
    )

    def forbidden_run(*args, **kwargs):
        raise AssertionError("4D-Humans must not run when a valid checkpoint exists")

    monkeypatch.setattr(checkpoint_bridge.subprocess, "run", forbidden_run)

    recovered = checkpoint_bridge._checkpointing_run_source(
        Path("/unused/4D-Humans"),
        source,
        0,
        {},
    )

    assert recovered == expected
    status = checkpoint_bridge._read_json(root / "segment-01.status.json")
    assert status is not None
    assert status["state"] == "complete"
    assert status["sampling_stride"] == SAMPLING_STRIDE
    assert status["effective_fps"] == EFFECTIVE_FPS
    assert "reused canonical checkpoint" in status["detail"]


def test_checkpoint_is_invalidated_when_source_bytes_change(tmp_path):
    source = tmp_path / "segment-01.mp4"
    source.write_bytes(b"version one")
    root = checkpoint_bridge._checkpoint_root(source)
    first_hash = checkpoint_bridge.base._sha256_file(source)

    checkpoint_bridge._publish_canonical_checkpoint(
        root,
        source_index=0,
        source_sha256=first_hash,
        source_fps=SOURCE_FPS,
        sampling_stride=SAMPLING_STRIDE,
        effective_fps=EFFECTIVE_FPS,
        tracks=_tracks(),
    )
    assert checkpoint_bridge._load_canonical_checkpoint(
        root,
        source_index=0,
        source_sha256=first_hash,
        sampling_stride=SAMPLING_STRIDE,
    ) is not None

    source.write_bytes(b"version two")
    second_hash = checkpoint_bridge.base._sha256_file(source)
    assert second_hash != first_hash
    assert checkpoint_bridge._load_canonical_checkpoint(
        root,
        source_index=0,
        source_sha256=second_hash,
        sampling_stride=SAMPLING_STRIDE,
    ) is None


def test_checkpoint_is_invalidated_when_sampling_stride_changes(tmp_path):
    source = tmp_path / "segment-01.mp4"
    source.write_bytes(b"stable")
    root = checkpoint_bridge._checkpoint_root(source)
    source_sha256 = checkpoint_bridge.base._sha256_file(source)

    checkpoint_bridge._publish_canonical_checkpoint(
        root,
        source_index=0,
        source_sha256=source_sha256,
        source_fps=SOURCE_FPS,
        sampling_stride=SAMPLING_STRIDE,
        effective_fps=EFFECTIVE_FPS,
        tracks=_tracks(),
    )

    assert checkpoint_bridge._load_canonical_checkpoint(
        root,
        source_index=0,
        source_sha256=source_sha256,
        sampling_stride=1,
    ) is None


def test_raw_phalp_output_is_published_with_matching_metadata(tmp_path):
    source = tmp_path / "segment-01.mp4"
    source.write_bytes(b"observation")
    source_sha256 = checkpoint_bridge.base._sha256_file(source)
    root = checkpoint_bridge._checkpoint_root(source)
    raw_source = tmp_path / "result.pkl"
    raw_source.write_bytes(b"raw-phalp-result")

    published = checkpoint_bridge._publish_raw_checkpoint(
        root,
        source_index=0,
        source_sha256=source_sha256,
        source_fps=SOURCE_FPS,
        sampling_stride=SAMPLING_STRIDE,
        effective_fps=EFFECTIVE_FPS,
        source_pkl=raw_source,
    )

    assert published.read_bytes() == b"raw-phalp-result"
    meta = checkpoint_bridge._read_json(root / "segment-01.phalp.json")
    assert meta is not None
    assert meta["source_sha256"] == source_sha256
    assert meta["source_index"] == 0
    assert meta["sampling_stride"] == SAMPLING_STRIDE
    assert meta["effective_fps"] == EFFECTIVE_FPS
    assert meta["format"] == checkpoint_bridge.RAW_META_FORMAT
