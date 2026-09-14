from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from bodyrig import photoidentity_evidence as evidence


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)


def _observations(version: Any) -> dict[str, Any]:
    value = evidence.build_observation_evidence(
        performer_id="performer-test",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter="test-adapter",
        analyzer_revision="test-revision",
        analyzer_capabilities=[],
        candidate_scenes=1,
        source_files_scanned=1,
        scan_exhausted=True,
        rows=[
            {
                "scene_id": "scene-1",
                "source_ordinal": 1,
                "start_seconds": 0.0,
                "duration_seconds": 2.0,
                "target_confidence": 0.9,
                "target_screen_fraction": 0.5,
                "face_visibility": 0.9,
                "full_body_visibility": 0.9,
                "sharpness": 0.9,
                "occlusion": 0.1,
                "motion": 0.1,
                "view": "front",
            }
        ],
        detail_evidence={},
    )
    value["version"] = version
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _bundle(tmp_path: Path, version: Any) -> tuple[Path, Path]:
    observations = _observations(1)
    observation_path = tmp_path / "photoidentity-observations.json"
    _write_json(observation_path, observations)
    observation_sha = hashlib.sha256(observation_path.read_bytes()).hexdigest()

    report = {
        **evidence.evaluate_sufficiency(observations),
        "observation_evidence_sha256": observation_sha,
    }
    report["version"] = version
    report_path = tmp_path / "photoidentity-evidence.json"
    _write_json(report_path, report)
    return report_path, observation_path


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_observation_evidence_rejects_boolean_non_numeric_and_wrong_v1(version: Any) -> None:
    with pytest.raises(
        evidence.PhotoIdentityEvidenceError,
        match="photoidentity observation evidence fields/format are invalid",
    ):
        evidence.validate_observation_evidence(_observations(version))


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_observation_evidence_preserves_numeric_v1_and_non_production_authority(version: Any) -> None:
    value = evidence.validate_observation_evidence(_observations(version))

    assert value["version"] == evidence.VERSION
    assert value["generic_guessing_permitted"] is False
    assert value["production_activation"] is False


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_sufficiency_report_rejects_boolean_non_numeric_and_wrong_v1(tmp_path: Path, version: Any) -> None:
    report_path, observation_path = _bundle(tmp_path, version)

    with pytest.raises(
        evidence.PhotoIdentityEvidenceError,
        match="photoidentity sufficiency report format/version is invalid",
    ):
        evidence.validate_bundle(report_path, observation_path)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_sufficiency_report_preserves_numeric_v1_exact_binding_and_non_production_authority(
    tmp_path: Path,
    version: Any,
) -> None:
    report_path, observation_path = _bundle(tmp_path, version)

    value = evidence.validate_bundle(report_path, observation_path)

    assert value["version"] == version
    assert value["observation_evidence_sha256"] == hashlib.sha256(observation_path.read_bytes()).hexdigest()
    assert value["generic_guessing_permitted"] is False
    assert value["production_activation"] is False
