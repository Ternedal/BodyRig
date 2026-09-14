from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from bodyrig.photoreal_identity_extractor_runner import (
    PhotorealIdentityExtractorError,
    build_identity_extractor_request,
    load_identity_extractor_config,
    run_external_identity_extractor,
    validate_identity_extractor_result,
)


def _bootstrap() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-bootstrap-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "sources": [
            {
                "source_key": "scene:s1:E:/a.mp4",
                "source_sha256": "a" * 64,
                "resolved_path": r"\\stash\VR_E\a.mp4",
                "kind": "video",
                "group_id": "scene:s1",
                "source_binding": "scene-performer",
                "performer_count": 1,
                "projection": "flat",
                "stereo_layout": "mono",
                "decode_mode": "rectilinear-mono",
                "reference_sample_count": 3,
                "reference_samples": [
                    {"timestamp_seconds": 1.0, "eye": "mono"},
                    {"timestamp_seconds": 2.0, "eye": "mono"},
                    {"timestamp_seconds": 3.0, "eye": "mono"},
                ],
            },
            {
                "source_key": "image:i1:F:/portrait.jpg",
                "source_sha256": "b" * 64,
                "resolved_path": r"\\stash\VR_F\portrait.jpg",
                "kind": "image",
                "group_id": "image:i1",
                "source_binding": "direct-performer",
                "performer_count": 1,
                "projection": "flat",
                "stereo_layout": "mono",
                "decode_mode": "image-direct",
                "reference_sample_count": 1,
                "reference_samples": [{"timestamp_seconds": None, "eye": "mono"}],
            },
        ],
        "train_only": True,
        "evaluation_source_count": 0,
        "source_bytes_bound": True,
        "identity_bank_build_authorized": True,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
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


def _result() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-reference-observations",
        "version": 1,
        "performer_id": "42",
        "extractor": "identity-test",
        "extractor_revision": "r1",
        "model_set_sha256": "c" * 64,
        "embedding_dimension": 32,
        "observations": [
            {
                "source_key": "scene:s1:E:/a.mp4",
                "source_sha256": "a" * 64,
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "frame_sha256": "1" * 64,
                "embedding": [1.0] + [0.0] * 31,
            }
        ],
        "build_only": True,
        "production_activation": False,
    }


def test_build_identity_extractor_request_is_measurement_only() -> None:
    request = build_identity_extractor_request(
        _bootstrap(),
        _model_set(),
        adapter="identity-test",
        revision="r1",
        expected_model_set_sha256="c" * 64,
    )

    assert request["adapter"] == "identity-test"
    assert request["revision"] == "r1"
    assert request["model_set_sha256"] == "c" * 64
    assert request["measurement_only"] is True
    assert request["train_only"] is True
    assert request["identity_matching_authority"] is False
    assert request["teacher_training_authority"] is False
    assert request["photoreal_acceptance_authority"] is False
    assert request["production_activation"] is False


def test_identity_extractor_config_loader_is_exact_and_model_bound(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "format": "bodyrig-photoreal-identity-extractor-config",
                "version": 1,
                "adapter": "identity-test",
                "revision": "r1",
                "model_set_sha256": "c" * 64,
                "command": [sys.executable, "adapter.py"],
                "timeout_seconds": 30,
            }
        ),
        encoding="utf-8",
    )
    config = load_identity_extractor_config(path)
    assert config["adapter"] == "identity-test"
    assert config["model_set_sha256"] == "c" * 64

    value = json.loads(path.read_text(encoding="utf-8"))
    value["version"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PhotorealIdentityExtractorError, match="format/version"):
        load_identity_extractor_config(path)


def test_request_rejects_config_model_set_mismatch() -> None:
    with pytest.raises(PhotorealIdentityExtractorError, match="different model set"):
        build_identity_extractor_request(
            _bootstrap(),
            _model_set(),
            adapter="identity-test",
            revision="r1",
            expected_model_set_sha256="d" * 64,
        )


def test_result_rejects_provenance_mismatch() -> None:
    result = _result()
    result["extractor_revision"] = "wrong"

    with pytest.raises(PhotorealIdentityExtractorError, match="provenance mismatch"):
        validate_identity_extractor_result(
            result,
            performer_id="42",
            adapter="identity-test",
            revision="r1",
            model_set_sha256="c" * 64,
        )


def test_external_identity_extractor_enforces_real_process_contract(tmp_path: Path) -> None:
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
sample = source['reference_samples'][0]
result = {
    'format': 'bodyrig-photoreal-identity-reference-observations',
    'version': 1,
    'performer_id': request['performer_id'],
    'extractor': a.bodyrig_adapter,
    'extractor_revision': a.bodyrig_revision,
    'model_set_sha256': a.bodyrig_model_set_sha256,
    'embedding_dimension': 32,
    'observations': [{
        'source_key': source['source_key'],
        'source_sha256': source['source_sha256'],
        'timestamp_seconds': sample['timestamp_seconds'],
        'eye': sample['eye'],
        'frame_sha256': '1' * 64,
        'embedding': [1.0] + [0.0] * 31,
    }],
    'build_only': True,
    'production_activation': False,
}
out = Path(a.bodyrig_output)
(out / 'identity-observations.json').write_text(json.dumps(result), encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = {
        "adapter": "identity-test",
        "revision": "r1",
        "model_set_sha256": "c" * 64,
        "command": [sys.executable, str(adapter_script)],
        "timeout_seconds": 30,
    }

    result = run_external_identity_extractor(
        config,
        _bootstrap(),
        _model_set(),
        workspace=tmp_path / "workspace",
    )

    assert result["extractor"] == "identity-test"
    assert result["extractor_revision"] == "r1"
    assert result["model_set_sha256"] == "c" * 64
    assert (tmp_path / "workspace" / "request.json").is_file()
    assert (tmp_path / "workspace" / "output" / "identity-observations.json").is_file()
    assert (tmp_path / "workspace" / "adapter.log").is_file()


def test_external_identity_extractor_rejects_extra_output_file(tmp_path: Path) -> None:
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
(out / 'identity-observations.json').write_text('{}', encoding='utf-8')
(out / 'extra.txt').write_text('no', encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = {
        "adapter": "identity-test",
        "revision": "r1",
        "model_set_sha256": "c" * 64,
        "command": [sys.executable, str(adapter_script)],
        "timeout_seconds": 30,
    }

    with pytest.raises(PhotorealIdentityExtractorError, match="exactly identity-observations.json"):
        run_external_identity_extractor(
            config,
            _bootstrap(),
            _model_set(),
            workspace=tmp_path / "workspace",
        )
