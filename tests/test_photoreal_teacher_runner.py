from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from bodyrig.photoreal_teacher_runner import (
    PhotorealTeacherRunnerError,
    build_teacher_request,
    run_external_teacher,
)


def _config(command: list[str]) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-teacher-config",
        "version": 1,
        "adapter": "exavatar-benchmark",
        "revision": "bodyrig-v1",
        "upstream_repository": "https://github.com/mks0601/ExAvatar_RELEASE",
        "upstream_commit": "1" * 40,
        "command": command,
        "timeout_seconds": 30,
    }


def _teacher_input() -> dict[str, object]:
    result: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "training_sources": [
            {
                "source_key": "scene:t:E:/train.mp4",
                "resolved_path": r"\\stash\VR_E\train.mp4",
                "sha256": "b" * 64,
            }
        ],
        "training_observations": [
            {
                "source_key": "scene:t:E:/train.mp4",
                "frame_sha256": "c" * 64,
                "timestamp_seconds": 1.0,
                "eye": "mono",
            }
        ],
        "held_out_evaluation_sources": [
            {
                "source_key": "scene:e:E:/secret-eval.mp4",
                "resolved_path": r"\\stash\VR_E\secret-eval.mp4",
                "sha256": "d" * 64,
            }
        ],
        "held_out_evaluation_observations": [
            {
                "source_key": "scene:e:E:/secret-eval.mp4",
                "frame_sha256": "e" * 64,
                "timestamp_seconds": 2.0,
                "eye": "mono",
            }
        ],
        "held_out_evaluation_source_count": 1,
        "held_out_evaluation_observation_count": 1,
        "held_out_view_coverage_missing": [],
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    encoded = json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    result["teacher_input_sha256"] = hashlib.sha256(encoded).hexdigest()
    return result


def test_teacher_request_never_discloses_held_out_paths_or_frame_hashes() -> None:
    request = build_teacher_request(_config([sys.executable, "adapter.py"]), _teacher_input())
    encoded = json.dumps(request, sort_keys=True)

    assert "secret-eval.mp4" not in encoded
    assert "e" * 64 not in encoded
    assert request["held_out_evaluation_source_count"] == 1
    assert request["held_out_evaluation_observation_count"] == 1
    assert request["held_out_paths_disclosed"] is False
    assert request["held_out_frame_hashes_disclosed"] is False
    assert request["train_evaluation_authority"] is False
    assert request["photoreal_acceptance_authority"] is False
    assert request["production_activation"] is False


def test_teacher_request_rejects_tampered_teacher_input_digest() -> None:
    teacher_input = _teacher_input()
    training_sources = teacher_input["training_sources"]
    assert isinstance(training_sources, list)
    assert isinstance(training_sources[0], dict)
    training_sources[0]["resolved_path"] = r"\\stash\VR_E\tampered.mp4"

    with pytest.raises(PhotorealTeacherRunnerError, match="teacher input digest mismatch"):
        build_teacher_request(_config([sys.executable, "adapter.py"]), teacher_input)


def test_real_child_process_teacher_contract_tracks_exact_training_consumption(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        """
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
p.add_argument('--bodyrig-upstream-commit', required=True)
a = p.parse_args()
request = json.loads(Path(a.bodyrig_request).read_text(encoding='utf-8'))
out = Path(a.bodyrig_output)
artifact = out / 'teacher.bin'
artifact.write_bytes(b'photoreal-teacher-test')
raw = artifact.read_bytes()
obs = request['training_observations'][0]
manifest = {
    'format': 'bodyrig-photoreal-teacher-manifest',
    'version': 1,
    'performer_id': request['performer_id'],
    'selected_epoch_id': request['selected_epoch_id'],
    'teacher_input_sha256': request['teacher_input_sha256'],
    'adapter': request['adapter'],
    'adapter_revision': request['adapter_revision'],
    'upstream_repository': request['upstream_repository'],
    'upstream_commit': request['upstream_commit'],
    'training_complete': True,
    'consumed_training_source_keys': [request['training_sources'][0]['source_key']],
    'consumed_training_observations': [{
        'source_key': obs['source_key'],
        'frame_sha256': obs['frame_sha256'],
        'timestamp_seconds': obs['timestamp_seconds'],
        'eye': obs['eye'],
    }],
    'artifacts': [{
        'kind': 'checkpoint',
        'relative_path': 'teacher.bin',
        'size_bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
    }],
    'photoreal_acceptance_authority': False,
    'human_visual_acceptance_required': True,
    'production_activation': False,
}
(out / 'teacher-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = run_external_teacher(
        _config([sys.executable, str(adapter)]),
        _teacher_input(),
        workspace=tmp_path / "workspace",
    )

    assert result["training_complete"] is True
    assert result["artifacts"][0]["relative_path"] == "teacher.bin"
    assert result["consumed_training_source_keys"] == ["scene:t:E:/train.mp4"]
    assert result["consumed_training_source_count"] == 1
    assert result["training_source_universe_count"] == 1
    assert result["training_source_utilization_fraction"] == 1.0
    assert result["consumed_training_observation_count"] == 1
    assert result["training_observation_utilization_fraction"] == 1.0
    request = json.loads((tmp_path / "workspace" / "request.json").read_text(encoding="utf-8"))
    assert "held_out_evaluation_sources" not in request
    assert "secret-eval.mp4" not in json.dumps(request)
    assert result["photoreal_acceptance_authority"] is False
    assert result["human_visual_acceptance_required"] is True
    assert result["production_activation"] is False


def test_teacher_runner_rejects_unlisted_extra_artifact(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter-extra.py"
    adapter.write_text(
        """
import argparse
import hashlib
import json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
p.add_argument('--bodyrig-upstream-commit', required=True)
a = p.parse_args()
r = json.loads(Path(a.bodyrig_request).read_text(encoding='utf-8'))
out = Path(a.bodyrig_output)
artifact = out / 'teacher.bin'
artifact.write_bytes(b'x')
(out / 'unlisted.bin').write_bytes(b'y')
obs = r['training_observations'][0]
manifest = {
 'format':'bodyrig-photoreal-teacher-manifest','version':1,
 'performer_id':r['performer_id'],'selected_epoch_id':r['selected_epoch_id'],
 'teacher_input_sha256':r['teacher_input_sha256'],'adapter':r['adapter'],
 'adapter_revision':r['adapter_revision'],'upstream_repository':r['upstream_repository'],
 'upstream_commit':r['upstream_commit'],'training_complete':True,
 'consumed_training_source_keys':[r['training_sources'][0]['source_key']],
 'consumed_training_observations':[{'source_key':obs['source_key'],'frame_sha256':obs['frame_sha256'],'timestamp_seconds':obs['timestamp_seconds'],'eye':obs['eye']}],
 'artifacts':[{'kind':'checkpoint','relative_path':'teacher.bin','size_bytes':1,'sha256':hashlib.sha256(b'x').hexdigest()}],
 'photoreal_acceptance_authority':False,'human_visual_acceptance_required':True,'production_activation':False}
(out / 'teacher-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PhotorealTeacherRunnerError, match="artifact universe mismatch"):
        run_external_teacher(
            _config([sys.executable, str(adapter)]),
            _teacher_input(),
            workspace=tmp_path / "workspace",
        )


def test_teacher_runner_rejects_claimed_consumption_outside_authorized_train_universe(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter-bogus-source.py"
    adapter.write_text(
        """
import argparse
import hashlib
import json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
p.add_argument('--bodyrig-upstream-commit', required=True)
a = p.parse_args()
r = json.loads(Path(a.bodyrig_request).read_text(encoding='utf-8'))
out = Path(a.bodyrig_output)
artifact = out / 'teacher.bin'
artifact.write_bytes(b'x')
obs = r['training_observations'][0]
manifest = {
 'format':'bodyrig-photoreal-teacher-manifest','version':1,
 'performer_id':r['performer_id'],'selected_epoch_id':r['selected_epoch_id'],
 'teacher_input_sha256':r['teacher_input_sha256'],'adapter':r['adapter'],
 'adapter_revision':r['adapter_revision'],'upstream_repository':r['upstream_repository'],
 'upstream_commit':r['upstream_commit'],'training_complete':True,
 'consumed_training_source_keys':['scene:not-authorized:E:/other.mp4'],
 'consumed_training_observations':[{'source_key':obs['source_key'],'frame_sha256':obs['frame_sha256'],'timestamp_seconds':obs['timestamp_seconds'],'eye':obs['eye']}],
 'artifacts':[{'kind':'checkpoint','relative_path':'teacher.bin','size_bytes':1,'sha256':hashlib.sha256(b'x').hexdigest()}],
 'photoreal_acceptance_authority':False,'human_visual_acceptance_required':True,'production_activation':False}
(out / 'teacher-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PhotorealTeacherRunnerError, match="outside authorized training universe"):
        run_external_teacher(
            _config([sys.executable, str(adapter)]),
            _teacher_input(),
            workspace=tmp_path / "workspace",
        )


def test_teacher_config_requires_exact_upstream_commit() -> None:
    config = _config([sys.executable, "adapter.py"])
    config["upstream_commit"] = "main"
    with pytest.raises(PhotorealTeacherRunnerError, match="exact 40-hex commit"):
        build_teacher_request(config, _teacher_input())
