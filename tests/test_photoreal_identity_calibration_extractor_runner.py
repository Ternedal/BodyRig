from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from bodyrig.photoreal_identity_calibration_extractor_runner import (
    PhotorealIdentityCalibrationExtractorError,
    build_calibration_extractor_request,
    run_external_calibration_extractor,
    validate_calibration_extractor_result,
)


def _config(command: list[str]) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-extractor-config",
        "version": 1,
        "adapter": "identity-test",
        "revision": "r1",
        "model_set_sha256": "c" * 64,
        "command": command,
        "timeout_seconds": 30,
    }


def _model_set() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-analyzer-model-set",
        "version": 1,
        "model_set_sha256": "c" * 64,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-calibration-plan",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": "d" * 64,
        "model_set_sha256": "c" * 64,
        "extractor": "identity-test",
        "extractor_revision": "r1",
        "embedding_dimension": 32,
        "sources": [
            {
                "source_key": "scene:s7:E:/p7.mp4",
                "source_sha256": "7" * 64,
                "resolved_path": r"\\stash\VR_E\p7.mp4",
                "subject_performer_id": "7",
                "subject_performer_name": "P7",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "video",
                "source_binding": "scene-single-performer",
                "projection": "flat",
                "stereo_layout": "mono",
                "decode_mode": "rectilinear-mono",
                "sample_count": 1,
                "samples": [{"timestamp_seconds": 1.0, "eye": "mono"}],
            }
        ],
        "negative_embedding_extraction_required": True,
        "calibration_only": True,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _result() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-negative-observations",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": "d" * 64,
        "extractor": "identity-test",
        "extractor_revision": "r1",
        "model_set_sha256": "c" * 64,
        "embedding_dimension": 32,
        "observations": [
            {
                "source_key": "scene:s7:E:/p7.mp4",
                "source_sha256": "7" * 64,
                "subject_performer_id": "7",
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "frame_sha256": "1" * 64,
                "embedding": [0.0, 1.0] + [0.0] * 30,
            }
        ],
        "calibration_only": True,
        "build_only": True,
        "production_activation": False,
    }


def test_calibration_request_is_measurement_only_and_same_model_bound() -> None:
    request = build_calibration_extractor_request(_config(["python"]), _plan(), _model_set())

    assert request["identity_bank_sha256"] == "d" * 64
    assert request["model_set_sha256"] == "c" * 64
    assert request["measurement_only"] is True
    assert request["calibration_only"] is True
    assert request["identity_matching_authority"] is False
    assert request["teacher_training_authority"] is False
    assert request["photoreal_acceptance_authority"] is False
    assert request["production_activation"] is False


def test_calibration_request_rejects_different_model_set() -> None:
    config = _config(["python"])
    config["model_set_sha256"] = "f" * 64

    with pytest.raises(PhotorealIdentityCalibrationExtractorError, match="different model set"):
        build_calibration_extractor_request(config, _plan(), _model_set())


def test_calibration_result_rejects_wrong_bank() -> None:
    result = _result()
    result["identity_bank_sha256"] = "e" * 64

    with pytest.raises(PhotorealIdentityCalibrationExtractorError, match="bank mismatch"):
        validate_calibration_extractor_result(result, plan=_plan(), config=_config(["python"]))


def test_calibration_result_accepts_complete_additive_quality_metadata() -> None:
    result = _result()
    result.update(
        {
            "identity_matching_authority": False,
            "teacher_training_authorized": False,
            "photoreal_acceptance_authority": False,
        }
    )
    result["observations"][0].update(
        {
            "candidate_id": "person-000",
            "candidate_count": 1,
            "person_detected": True,
            "width": 1920,
            "height": 1080,
            "view_bin": "front",
            "face_visibility": 0.9,
            "full_body_visibility": 0.8,
            "person_fraction": 0.25,
            "sharpness": 0.7,
            "motion": 0.0,
            "occlusion": 0.1,
            "identity_measurement_status": "available",
            "identity_measurement_reason": "embedding-available",
        }
    )

    validated = validate_calibration_extractor_result(
        result,
        plan=_plan(),
        config=_config(["python"]),
    )

    assert validated["observations"][0]["candidate_count"] == 1
    assert validated["identity_matching_authority"] is False
    assert validated["teacher_training_authorized"] is False
    assert validated["photoreal_acceptance_authority"] is False


def test_calibration_result_rejects_partial_quality_metadata() -> None:
    result = _result()
    result["observations"][0]["candidate_id"] = "person-000"

    with pytest.raises(
        PhotorealIdentityCalibrationExtractorError,
        match="quality metadata is incomplete",
    ):
        validate_calibration_extractor_result(
            result,
            plan=_plan(),
            config=_config(["python"]),
        )


def test_calibration_result_rejects_quality_authority_escalation() -> None:
    result = _result()
    result["identity_matching_authority"] = True

    with pytest.raises(
        PhotorealIdentityCalibrationExtractorError,
        match="crossed identity_matching_authority",
    ):
        validate_calibration_extractor_result(
            result,
            plan=_plan(),
            config=_config(["python"]),
        )


def test_external_calibration_extractor_enforces_real_process_contract(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        """
import argparse
import json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
p.add_argument('--bodyrig-model-set-sha256', required=True)
p.add_argument('--bodyrig-identity-bank-sha256', required=True)
a = p.parse_args()
request = json.loads(Path(a.bodyrig_request).read_text(encoding='utf-8'))
source = request['sources'][0]
sample = source['samples'][0]
result = {
    'format': 'bodyrig-photoreal-identity-negative-observations',
    'version': 1,
    'target_performer_id': request['target_performer_id'],
    'identity_bank_sha256': a.bodyrig_identity_bank_sha256,
    'extractor': a.bodyrig_adapter,
    'extractor_revision': a.bodyrig_revision,
    'model_set_sha256': a.bodyrig_model_set_sha256,
    'embedding_dimension': request['embedding_dimension'],
    'observations': [{
        'source_key': source['source_key'],
        'source_sha256': source['source_sha256'],
        'subject_performer_id': source['subject_performer_id'],
        'timestamp_seconds': sample['timestamp_seconds'],
        'eye': sample['eye'],
        'frame_sha256': '1' * 64,
        'embedding': [0.0, 1.0] + [0.0] * 30,
    }],
    'calibration_only': True,
    'build_only': True,
    'production_activation': False,
}
out = Path(a.bodyrig_output)
(out / 'negative-observations.json').write_text(json.dumps(result), encoding='utf-8')
""".strip() + "\n",
        encoding="utf-8",
    )
    config = _config([sys.executable, str(adapter)])

    result = run_external_calibration_extractor(
        config,
        _plan(),
        _model_set(),
        workspace=tmp_path / "workspace",
    )

    assert result["extractor"] == "identity-test"
    assert result["identity_bank_sha256"] == "d" * 64
    assert (tmp_path / "workspace" / "request.json").is_file()
    assert (tmp_path / "workspace" / "output" / "negative-observations.json").is_file()
    assert (tmp_path / "workspace" / "adapter.log").is_file()


def test_external_calibration_extractor_rejects_extra_output(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter-extra.py"
    adapter.write_text(
        """
import argparse
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
p.add_argument('--bodyrig-model-set-sha256', required=True)
p.add_argument('--bodyrig-identity-bank-sha256', required=True)
a = p.parse_args()
out = Path(a.bodyrig_output)
(out / 'negative-observations.json').write_text('{}', encoding='utf-8')
(out / 'extra.txt').write_text('no', encoding='utf-8')
""".strip() + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PhotorealIdentityCalibrationExtractorError, match="exactly negative-observations.json"):
        run_external_calibration_extractor(
            _config([sys.executable, str(adapter)]),
            _plan(),
            _model_set(),
            workspace=tmp_path / "workspace",
        )
