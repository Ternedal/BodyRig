from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.observation import (
    ANALYZER_RESULT_FORMAT,
    ObservationError,
    _finite,
    _positive,
    load_stash_source_manifest,
    validate_analyzer_result,
)


def _write_source_manifest(
    tmp_path: Path,
    *,
    version: object = 1,
    duration: object = 60.0,
) -> Path:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    manifest = {
        "format": "bodyrig-stash-source-manifest",
        "version": version,
        "source_kind": "stash-local",
        "selected": [
            {
                "scene_id": "11",
                "path": str(source),
                "duration": duration,
            }
        ],
    }
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _analyzer_payload(*, version: object = 1) -> dict[str, object]:
    return {
        "format": ANALYZER_RESULT_FORMAT,
        "version": version,
        "adapter": "fixture",
        "revision": "r1",
        "observations": [
            {
                "source_id": "s001",
                "start_seconds": 0,
                "duration_seconds": 5,
                "target_confidence": 1,
                "target_screen_fraction": 0.8,
                "face_visibility": 0.9,
                "full_body_visibility": 0.9,
                "sharpness": 0.9,
                "occlusion": 0,
                "motion": 0.5,
                "view": "front",
            }
        ],
    }


def _validate_payload(tmp_path: Path, payload: dict[str, object]):
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return validate_analyzer_result(
        path,
        sources=[{"source_id": "s001", "duration": 60.0}],
        expected_adapter="fixture",
        expected_revision="r1",
    )


def test_numeric_helpers_normalize_arbitrary_precision_overflow() -> None:
    with pytest.raises(ObservationError, match="quality must be a finite number"):
        _finite(10**400, label="quality")
    with pytest.raises(ObservationError, match="duration must be a finite number"):
        _positive(10**400, label="duration", maximum=172800.0)


def test_source_manifest_normalizes_duration_overflow(tmp_path: Path) -> None:
    path = _write_source_manifest(tmp_path, duration=10**400)
    with pytest.raises(ObservationError, match="source duration must be a finite number"):
        load_stash_source_manifest(path)


def test_source_manifest_rejects_boolean_version_but_accepts_numeric_v1(tmp_path: Path) -> None:
    with pytest.raises(ObservationError, match="unsupported Stash source manifest format/version"):
        load_stash_source_manifest(_write_source_manifest(tmp_path, version=True))

    manifest, sources, _ = load_stash_source_manifest(_write_source_manifest(tmp_path, version=1.0))
    assert manifest["version"] == 1.0
    assert sources[0]["duration"] == 60.0


@pytest.mark.parametrize("field", ["start_seconds", "target_confidence"])
def test_analyzer_result_normalizes_numeric_overflow(tmp_path: Path, field: str) -> None:
    payload = _analyzer_payload()
    observation = payload["observations"][0]
    assert isinstance(observation, dict)
    observation[field] = 10**400
    with pytest.raises(ObservationError, match=rf"{field} must be a finite number"):
        _validate_payload(tmp_path, payload)


def test_analyzer_result_rejects_boolean_version_but_accepts_numeric_v1(tmp_path: Path) -> None:
    with pytest.raises(ObservationError, match="unsupported observation analyzer result format/version"):
        _validate_payload(tmp_path, _analyzer_payload(version=True))

    observations = _validate_payload(tmp_path, _analyzer_payload(version=1.0))
    assert len(observations) == 1
    assert observations[0].start_seconds == 0.0
    assert observations[0].duration_seconds == 5.0
    assert observations[0].target_confidence == 1.0
