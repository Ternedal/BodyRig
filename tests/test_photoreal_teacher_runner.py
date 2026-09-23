from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.photoreal_teacher_runner as teacher_runner
from bodyrig.photoreal_teacher_runner import (
    PhotorealTeacherRunnerError,
    build_teacher_request,
    resume_external_teacher,
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


def _resign_teacher_input(value: dict[str, object]) -> dict[str, object]:
    value.pop("teacher_input_sha256", None)
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    value["teacher_input_sha256"] = hashlib.sha256(encoded).hexdigest()
    return value


def _teacher_input() -> dict[str, object]:
    result: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "selected_epoch_id": "epoch-a",
        "appearance_epoch_selection_sha256": "f" * 64,
        "identity_bank_sha256": "1" * 64,
        "identity_calibration_sha256": "2" * 64,
        "analyzer_model_set_sha256": "3" * 64,
        "training_sources": [
            {
                "source_key": "scene:t:E:/train.mp4",
                "group_id": "group-train",
                "kind": "video",
                "resolved_path": r"\\stash\VR_E\train.mp4",
                "size_bytes": 100,
                "sha256": "b" * 64,
                "information_score": 1.0,
                "width": 1920,
                "height": 1080,
                "projection": "flat",
                "stereo_layout": "mono",
            }
        ],
        "training_observations": [
            {
                "source_key": "scene:t:E:/train.mp4",
                "group_id": "group-train",
                "split": "train",
                "frame_sha256": "c" * 64,
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "view_bin": "face-front",
                "coverage": ["face-front"],
            }
        ],
        "held_out_evaluation_sources": [
            {
                "source_key": "scene:e:E:/secret-eval.mp4",
                "group_id": "group-eval",
                "kind": "video",
                "resolved_path": r"\\stash\VR_E\secret-eval.mp4",
                "size_bytes": 200,
                "sha256": "d" * 64,
                "information_score": 0.9,
                "width": 1920,
                "height": 1080,
                "projection": "flat",
                "stereo_layout": "mono",
            }
        ],
        "held_out_evaluation_observations": [
            {
                "source_key": "scene:e:E:/secret-eval.mp4",
                "group_id": "group-eval",
                "split": "evaluation",
                "frame_sha256": "e" * 64,
                "timestamp_seconds": 2.0,
                "eye": "mono",
                "view_bin": "face-profile",
                "coverage": ["face-profile"],
            }
        ],
        "held_out_view_coverage_required": ["face-profile"],
        "held_out_view_coverage_observed": ["face-profile"],
        "held_out_view_coverage_missing": [],
        "training_source_count": 1,
        "held_out_evaluation_source_count": 1,
        "training_observation_count": 1,
        "held_out_evaluation_observation_count": 1,
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    return _resign_teacher_input(result)


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


def test_teacher_request_rejects_resigned_unknown_training_source_field() -> None:
    teacher_input = _teacher_input()
    training_sources = teacher_input["training_sources"]
    assert isinstance(training_sources, list)
    assert isinstance(training_sources[0], dict)
    training_sources[0]["unexpected_authority"] = True
    _resign_teacher_input(teacher_input)

    with pytest.raises(PhotorealTeacherRunnerError, match="training source fields must match v1 exactly"):
        build_teacher_request(_config([sys.executable, "adapter.py"]), teacher_input)


def test_teacher_request_rejects_resigned_count_mismatch() -> None:
    teacher_input = _teacher_input()
    teacher_input["training_source_count"] = 2
    _resign_teacher_input(teacher_input)

    with pytest.raises(PhotorealTeacherRunnerError, match="training source count mismatch"):
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


def _prepare_incomplete_teacher_workspace(
    tmp_path: Path,
    *,
    config: dict[str, object],
    teacher_input: dict[str, object],
) -> tuple[Path, dict[str, object]]:
    workspace = tmp_path / "resume-workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    request = build_teacher_request(config, teacher_input)
    (workspace / "request.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return workspace, request


def test_teacher_runner_resumes_exact_incomplete_workspace(tmp_path: Path, monkeypatch) -> None:
    config = _config([sys.executable, "adapter.py"])
    teacher_input = _teacher_input()
    workspace, request = _prepare_incomplete_teacher_workspace(
        tmp_path,
        config=config,
        teacher_input=teacher_input,
    )
    captured: dict[str, object] = {}

    def fake_invoke(config_value, request_value, *, request_path, output_dir, log_path):
        captured["config"] = config_value
        captured["request"] = request_value
        captured["request_path"] = Path(request_path)
        captured["output_dir"] = Path(output_dir)
        captured["log_path"] = Path(log_path)
        return {"status": "resumed"}

    monkeypatch.setattr(teacher_runner, "_invoke_teacher_adapter", fake_invoke)

    result = resume_external_teacher(config, teacher_input, workspace=workspace)

    assert result == {"status": "resumed"}
    assert captured["request"] == request
    assert captured["request_path"] == workspace / "request.json"
    assert captured["output_dir"] == workspace / "output"
    assert captured["log_path"] == workspace / "adapter-resume-001.log"


def test_teacher_runner_resume_rejects_request_drift(tmp_path: Path, monkeypatch) -> None:
    config = _config([sys.executable, "adapter.py"])
    teacher_input = _teacher_input()
    workspace, _request = _prepare_incomplete_teacher_workspace(
        tmp_path,
        config=config,
        teacher_input=teacher_input,
    )
    existing = json.loads((workspace / "request.json").read_text(encoding="utf-8"))
    existing["selected_epoch_id"] = "different-epoch"
    (workspace / "request.json").write_text(
        json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    invoked = False

    def fake_invoke(*_args, **_kwargs):
        nonlocal invoked
        invoked = True
        return {}

    monkeypatch.setattr(teacher_runner, "_invoke_teacher_adapter", fake_invoke)

    with pytest.raises(PhotorealTeacherRunnerError, match="resume request differs"):
        resume_external_teacher(config, teacher_input, workspace=workspace)

    assert invoked is False


def test_teacher_runner_resume_rejects_nonempty_partial_output(tmp_path: Path, monkeypatch) -> None:
    config = _config([sys.executable, "adapter.py"])
    teacher_input = _teacher_input()
    workspace, _request = _prepare_incomplete_teacher_workspace(
        tmp_path,
        config=config,
        teacher_input=teacher_input,
    )
    (workspace / "output" / "partial.bin").write_bytes(b"partial")
    invoked = False

    def fake_invoke(*_args, **_kwargs):
        nonlocal invoked
        invoked = True
        return {}

    monkeypatch.setattr(teacher_runner, "_invoke_teacher_adapter", fake_invoke)

    with pytest.raises(PhotorealTeacherRunnerError, match="incomplete output directory is not empty"):
        resume_external_teacher(config, teacher_input, workspace=workspace)

    assert invoked is False


def test_teacher_runner_resume_rejects_completed_workspace(tmp_path: Path, monkeypatch) -> None:
    config = _config([sys.executable, "adapter.py"])
    teacher_input = _teacher_input()
    workspace, _request = _prepare_incomplete_teacher_workspace(
        tmp_path,
        config=config,
        teacher_input=teacher_input,
    )
    (workspace / "output" / "teacher-manifest.json").write_text("{}\n", encoding="utf-8")
    invoked = False

    def fake_invoke(*_args, **_kwargs):
        nonlocal invoked
        invoked = True
        return {}

    monkeypatch.setattr(teacher_runner, "_invoke_teacher_adapter", fake_invoke)

    with pytest.raises(PhotorealTeacherRunnerError, match="already complete"):
        resume_external_teacher(config, teacher_input, workspace=workspace)

    assert invoked is False


def test_teacher_runner_resume_uses_monotonic_resume_log_slots(tmp_path: Path, monkeypatch) -> None:
    config = _config([sys.executable, "adapter.py"])
    teacher_input = _teacher_input()
    workspace, _request = _prepare_incomplete_teacher_workspace(
        tmp_path,
        config=config,
        teacher_input=teacher_input,
    )
    (workspace / "adapter-resume-001.log").write_text("old attempt\n", encoding="utf-8")
    captured: dict[str, Path] = {}

    def fake_invoke(_config, _request, *, request_path, output_dir, log_path):
        captured["log_path"] = Path(log_path)
        return {"status": "resumed"}

    monkeypatch.setattr(teacher_runner, "_invoke_teacher_adapter", fake_invoke)

    resume_external_teacher(config, teacher_input, workspace=workspace)

    assert captured["log_path"] == workspace / "adapter-resume-002.log"



def test_teacher_runner_resume_accepts_missing_final_output_after_atomic_publish_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config([sys.executable, "adapter.py"])
    teacher_input = _teacher_input()
    workspace, _request = _prepare_incomplete_teacher_workspace(
        tmp_path,
        config=config,
        teacher_input=teacher_input,
    )
    (workspace / "output").rmdir()
    captured: dict[str, Path] = {}

    def fake_invoke(_config, _request, *, request_path, output_dir, log_path):
        captured["output_dir"] = Path(output_dir)
        return {"status": "resumed"}

    monkeypatch.setattr(teacher_runner, "_invoke_teacher_adapter", fake_invoke)

    result = resume_external_teacher(config, teacher_input, workspace=workspace)

    assert result == {"status": "resumed"}
    assert captured["output_dir"] == workspace / "output"


def test_teacher_adapter_partial_stage_never_poison_final_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}\n", encoding="utf-8")
    log_path = tmp_path / "adapter.log"
    config = {
        "command": ["adapter"],
        "adapter": "exavatar-benchmark",
        "revision": "bodyrig-v1",
        "upstream_commit": "1" * 40,
        "timeout_seconds": 30,
    }

    def failing_process(invoke, *, log_path, timeout_seconds):
        stage = Path(invoke[invoke.index("--bodyrig-output") + 1])
        (stage / "partial.bin").write_bytes(b"partial")
        return SimpleNamespace(returncode=9)

    monkeypatch.setattr(teacher_runner, "run_logged_process", failing_process)

    with pytest.raises(PhotorealTeacherRunnerError, match="failed with exit code 9"):
        teacher_runner._invoke_teacher_adapter(
            config,
            {},
            request_path=request_path,
            output_dir=output,
            log_path=log_path,
        )

    assert not output.exists()
    assert not (tmp_path / ".output.bodyrig-stage").exists()


def test_teacher_adapter_publishes_validated_stage_as_final_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}\n", encoding="utf-8")
    log_path = tmp_path / "adapter.log"
    config = {
        "command": ["adapter"],
        "adapter": "exavatar-benchmark",
        "revision": "bodyrig-v1",
        "upstream_commit": "1" * 40,
        "timeout_seconds": 30,
    }

    def successful_process(invoke, *, log_path, timeout_seconds):
        stage = Path(invoke[invoke.index("--bodyrig-output") + 1])
        (stage / "artifact.bin").write_bytes(b"ok")
        (stage / "teacher-manifest.json").write_text("{}\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(teacher_runner, "run_logged_process", successful_process)
    monkeypatch.setattr(
        teacher_runner,
        "validate_teacher_result",
        lambda manifest, *, request, output_dir: {"validated": True},
    )

    result = teacher_runner._invoke_teacher_adapter(
        config,
        {},
        request_path=request_path,
        output_dir=output,
        log_path=log_path,
    )

    assert result == {"validated": True}
    assert (output / "artifact.bin").read_bytes() == b"ok"
    assert (output / "teacher-manifest.json").is_file()
    assert not (tmp_path / ".output.bodyrig-stage").exists()
