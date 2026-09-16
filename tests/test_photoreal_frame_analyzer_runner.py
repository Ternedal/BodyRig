from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from bodyrig.photoreal_frame_analyzer_runner import (
    PhotorealFrameAnalyzerError,
    build_analyzer_request,
    load_analyzer_config,
    run_external_frame_analyzer,
    validate_analyzer_result,
)

MODEL_SET_SHA = "c" * 64
IDENTITY_DIMENSION = 32


def _scan_plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-scan-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "strategy": "uniform-midpoint-scout-v1",
        "sources": [
            {
                "source_key": "scene:s1:E:/source.mp4",
                "source_sha256": "a" * 64,
                "resolved_path": r"\\stash\VR_E\source.mp4",
                "kind": "video",
                "split": "train",
                "group_id": "scene:s1",
                "projection": "flat",
                "stereo_layout": "mono",
                "decode_mode": "rectilinear-mono",
                "sample_count": 1,
                "samples": [{"timestamp_seconds": 1.0, "eye": "mono"}],
            }
        ],
        "all_sources_sha256_bound": True,
        "train_evaluation_assignment_inherited": True,
        "frame_analyzer_required": True,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _result(
    adapter: str = "test-analyzer",
    revision: str = "r1",
    model_set_sha256: str = MODEL_SET_SHA,
) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-observations",
        "version": 1,
        "performer_id": "42",
        "analyzer": adapter,
        "analyzer_revision": revision,
        "analyzer_model_set_sha256": model_set_sha256,
        "identity_embedding_dimension": IDENTITY_DIMENSION,
        "observations": [
            {
                "source_key": "scene:s1:E:/source.mp4",
                "source_sha256": "a" * 64,
                "kind": "video",
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "projection": "flat",
                "frame_sha256": "b" * 64,
                "perceptual_hash": "0123456789abcdef",
                "candidate_id": "person-0",
                "person_detected": True,
                "width": 1920,
                "height": 1080,
                "view_bin": "front",
                "face_visibility": 0.9,
                "full_body_visibility": 0.9,
                "person_fraction": 0.8,
                "sharpness": 0.8,
                "motion": 0.1,
                "occlusion": 0.1,
                "identity_measurement_status": "available",
                "identity_embedding": [1.0] + [0.0] * 31,
            }
        ],
        "build_only": True,
        "production_activation": False,
    }


def _validate_result(result: dict[str, object]) -> dict[str, object]:
    return validate_analyzer_result(
        result,
        performer_id="42",
        adapter="test-analyzer",
        revision="r1",
        model_set_sha256=MODEL_SET_SHA,
        scan_plan=_scan_plan(),
    )


def test_build_request_keeps_adapter_measurement_only() -> None:
    request = build_analyzer_request(
        _scan_plan(),
        adapter="test-analyzer",
        revision="r1",
        model_set_sha256=MODEL_SET_SHA,
    )
    assert request["measurement_only"] is True
    assert request["identity_measurement_only"] is True
    assert request["identity_matching_authority"] is False
    assert request["train_evaluation_authority"] is False
    assert request["photoreal_acceptance_authority"] is False
    assert request["production_activation"] is False


def test_config_loader_is_exact_and_bool_safe(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "format": "bodyrig-photoreal-frame-analyzer-config",
                "version": 1,
                "adapter": "test-analyzer",
                "revision": "r1",
                "model_set_sha256": MODEL_SET_SHA,
                "command": [sys.executable, "adapter.py"],
                "timeout_seconds": 30,
            }
        ),
        encoding="utf-8",
    )
    loaded = load_analyzer_config(path)
    assert loaded["adapter"] == "test-analyzer"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["version"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PhotorealFrameAnalyzerError, match="format/version"):
        load_analyzer_config(path)


def test_result_rejects_revision_provenance_mismatch() -> None:
    with pytest.raises(PhotorealFrameAnalyzerError, match="provenance mismatch"):
        _validate_result(_result(revision="wrong"))


def test_result_rejects_model_set_provenance_mismatch() -> None:
    with pytest.raises(PhotorealFrameAnalyzerError, match="model-set provenance mismatch"):
        _validate_result(_result(model_set_sha256="d" * 64))


def test_result_requires_exact_scan_plan() -> None:
    with pytest.raises(PhotorealFrameAnalyzerError, match="requires the exact scan plan"):
        validate_analyzer_result(
            _result(),
            performer_id="42",
            adapter="test-analyzer",
            revision="r1",
            model_set_sha256=MODEL_SET_SHA,
        )


def test_result_rejects_external_identity_authority_assertion() -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["target_identity_verified"] = True
    with pytest.raises(PhotorealFrameAnalyzerError, match="attempted to assert identity authority"):
        _validate_result(result)


def test_result_requires_explicit_candidate_id_and_person_detection() -> None:
    result = copy.deepcopy(_result())
    del result["observations"][0]["candidate_id"]
    with pytest.raises(PhotorealFrameAnalyzerError, match="candidate_id is invalid"):
        _validate_result(result)

    result = copy.deepcopy(_result())
    del result["observations"][0]["person_detected"]
    with pytest.raises(PhotorealFrameAnalyzerError, match="person_detected must be boolean"):
        _validate_result(result)


def test_result_requires_available_embedding_dimension() -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["identity_embedding"] = [1.0, 0.0]
    with pytest.raises(PhotorealFrameAnalyzerError, match="wrong dimension"):
        _validate_result(result)


def test_result_allows_no_person_placeholder_only_without_identity_embedding() -> None:
    result = copy.deepcopy(_result())
    row = result["observations"][0]
    row["candidate_id"] = "none-0"
    row["person_detected"] = False
    row["identity_measurement_status"] = "unavailable"
    row["identity_embedding"] = None
    validated = _validate_result(result)
    assert validated["observations"][0]["person_detected"] is False

    bad = copy.deepcopy(_result())
    bad["observations"][0]["person_detected"] = False
    with pytest.raises(PhotorealFrameAnalyzerError, match="requires a detected person"):
        _validate_result(bad)


def test_result_rejects_duplicate_candidate_id_in_same_sample() -> None:
    result = copy.deepcopy(_result())
    result["observations"].append(copy.deepcopy(result["observations"][0]))
    with pytest.raises(PhotorealFrameAnalyzerError, match="repeated candidate_id"):
        _validate_result(result)


def test_external_runner_enforces_real_process_contract(tmp_path: Path) -> None:
    adapter_script = tmp_path / "adapter.py"
    adapter_script.write_text(
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
a = p.parse_args()
request = json.loads(Path(a.bodyrig_request).read_text(encoding='utf-8'))
source = request['sources'][0]
result = {
    'format': 'bodyrig-photoreal-frame-observations',
    'version': 1,
    'performer_id': request['performer_id'],
    'analyzer': a.bodyrig_adapter,
    'analyzer_revision': a.bodyrig_revision,
    'analyzer_model_set_sha256': a.bodyrig_model_set_sha256,
    'identity_embedding_dimension': 32,
    'observations': [{
        'source_key': source['source_key'], 'source_sha256': source['source_sha256'], 'kind': source['kind'],
        'timestamp_seconds': 1.0, 'eye': 'mono', 'projection': 'flat', 'frame_sha256': 'b' * 64,
        'perceptual_hash': '0123456789abcdef', 'candidate_id': 'person-0', 'person_detected': True,
        'width': 1920, 'height': 1080, 'view_bin': 'front', 'face_visibility': 0.9,
        'full_body_visibility': 0.9, 'person_fraction': 0.8, 'sharpness': 0.8, 'motion': 0.1,
        'occlusion': 0.1, 'identity_measurement_status': 'available',
        'identity_embedding': [1.0] + [0.0] * 31,
    }],
    'build_only': True, 'production_activation': False,
}
out = Path(a.bodyrig_output)
(out / 'observations.json').write_text(json.dumps(result), encoding='utf-8')
""".strip() + "\n",
        encoding="utf-8",
    )
    config = {
        "adapter": "test-analyzer",
        "revision": "r1",
        "model_set_sha256": MODEL_SET_SHA,
        "command": [sys.executable, str(adapter_script)],
        "timeout_seconds": 30,
    }
    result = run_external_frame_analyzer(config, _scan_plan(), workspace=tmp_path / "workspace")
    assert result["observations"][0]["candidate_id"] == "person-0"
    assert (tmp_path / "workspace" / "request.json").is_file()
    assert (tmp_path / "workspace" / "output" / "observations.json").is_file()
    assert (tmp_path / "workspace" / "adapter.log").is_file()


def test_external_runner_rejects_extra_output_file(tmp_path: Path) -> None:
    adapter_script = tmp_path / "adapter-extra.py"
    adapter_script.write_text(
        """
import argparse
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
p.add_argument('--bodyrig-model-set-sha256', required=True)
a = p.parse_args()
out = Path(a.bodyrig_output)
(out / 'observations.json').write_text('{}', encoding='utf-8')
(out / 'extra.txt').write_text('no', encoding='utf-8')
""".strip() + "\n",
        encoding="utf-8",
    )
    config = {
        "adapter": "test-analyzer", "revision": "r1", "model_set_sha256": MODEL_SET_SHA,
        "command": [sys.executable, str(adapter_script)], "timeout_seconds": 30,
    }
    with pytest.raises(PhotorealFrameAnalyzerError, match="exactly observations.json"):
        run_external_frame_analyzer(config, _scan_plan(), workspace=tmp_path / "workspace")
