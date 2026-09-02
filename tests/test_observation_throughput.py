from __future__ import annotations

from pathlib import Path

from bodyrig.observation import OBSERVATION_SEGMENT_FPS, materialize_segments


def test_materialized_observation_segments_cap_temporal_rate_without_scaling(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    workspace = tmp_path / "segments"
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> int:
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"segment")
        return 0

    manifest = materialize_segments(
        sources=[
            {
                "source_id": "s001",
                "scene_id": "scene-1",
                "path": str(source),
                "duration": 60.0,
            }
        ],
        selection_manifest={
            "format": "bodyrig-observation-selection",
            "version": 1,
            "source_manifest_sha256": "a" * 64,
            "adapter": "fixture",
            "revision": "r1",
            "selected": [
                {
                    "source_id": "s001",
                    "scene_id": "scene-1",
                    "start_seconds": 3.0,
                    "duration_seconds": 12.0,
                    "target_confidence": 0.9,
                    "target_screen_fraction": 0.8,
                    "face_visibility": 0.9,
                    "full_body_visibility": 0.9,
                    "sharpness": 0.9,
                    "occlusion": 0.0,
                    "motion": 0.5,
                    "view": "front",
                    "base_score": 0.9,
                }
            ],
        },
        workspace=workspace,
        runner=runner,
    )

    assert OBSERVATION_SEGMENT_FPS == 15
    assert len(calls) == 1
    argv = calls[0]
    filter_index = argv.index("-vf")
    assert argv[filter_index + 1] == "fps='min(15,source_fps)'"
    assert "scale=" not in " ".join(argv)
    assert argv[argv.index("-t") + 1] == "12.000"
    assert manifest["segments"][0]["duration_seconds"] == 12.0


def test_segment_fps_cap_never_requests_temporal_upsampling() -> None:
    source = Path(__file__).resolve().parents[1] / "bodyrig" / "observation.py"
    text = source.read_text(encoding="utf-8")
    assert "source_fps" in text
    assert "min({OBSERVATION_SEGMENT_FPS},source_fps)" in text
    assert 'f"fps={OBSERVATION_SEGMENT_FPS}"' not in text


def test_segment_fps_cap_is_not_a_spatial_quality_tradeoff() -> None:
    # This guard is intentionally about the command contract: BodyRig may drop
    # redundant temporal frames for PHALP throughput, but must not downscale the
    # selected observation bytes used by identity capture/high-fidelity fitting.
    source = Path(__file__).resolve().parents[1] / "bodyrig" / "observation.py"
    text = source.read_text(encoding="utf-8")
    assert 'f"fps=\'min({OBSERVATION_SEGMENT_FPS},source_fps)\'"' in text
    assert '"scale=' not in text
