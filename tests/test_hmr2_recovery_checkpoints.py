from __future__ import annotations

from pathlib import Path

import bodyrig.bridges.hmr2_checkpoint_bridge as checkpoint_bridge
from bodyrig.bridges.hmr2_config import bridge_script_path


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
                    "timestamp_ms": 40,
                    "confidence": 1.0,
                    "joints": {"head": [0.0, 1.0, 0.0]},
                },
            ],
        }
    ]


def test_production_bridge_routes_through_checkpoint_layer():
    assert bridge_script_path().name == "hmr2_checkpoint_bridge.py"


def test_completed_segment_is_reused_without_restarting_4d_humans(monkeypatch, tmp_path):
    source = tmp_path / "segment-01.mp4"
    source.write_bytes(b"stable observation bytes")
    root = checkpoint_bridge._checkpoint_root(source)
    source_sha256 = checkpoint_bridge.base._sha256_file(source)
    expected = _tracks()

    checkpoint_bridge._publish_canonical_checkpoint(
        root,
        source_index=0,
        source_sha256=source_sha256,
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
        tracks=_tracks(),
    )
    assert checkpoint_bridge._load_canonical_checkpoint(
        root,
        source_index=0,
        source_sha256=first_hash,
    ) is not None

    source.write_bytes(b"version two")
    second_hash = checkpoint_bridge.base._sha256_file(source)
    assert second_hash != first_hash
    assert checkpoint_bridge._load_canonical_checkpoint(
        root,
        source_index=0,
        source_sha256=second_hash,
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
        source_pkl=raw_source,
    )

    assert published.read_bytes() == b"raw-phalp-result"
    meta = checkpoint_bridge._read_json(root / "segment-01.phalp.json")
    assert meta is not None
    assert meta["source_sha256"] == source_sha256
    assert meta["source_index"] == 0
    assert meta["format"] == checkpoint_bridge.RAW_META_FORMAT
