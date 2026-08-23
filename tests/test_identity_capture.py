from __future__ import annotations

import json
import sys
from pathlib import Path

from bodyrig.identity_capture_cli import main as capture_main


BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "shape": {
        "shoulder_to_height": 0.24,
        "hip_to_height": 0.19,
        "arm_to_height": 0.44,
        "leg_to_height": 0.53,
    },
    "motion": {"energy": 0.42, "head_motion": 0.21},
}


def _proof() -> dict:
    return {
        "format": "bodyrig-recovery-proof",
        "version": 1,
        "source_count": 2,
        "adapter": "fixture-recovery",
        "revision": "recovery-v1",
        "track_id": "7",
        "observed_frames": 120,
        "bodyprint": BODYPRINT,
    }


def _adapter(path: Path, *, wrong_track: bool = False, extra_result: bool = False) -> None:
    track_expression = "'8'" if wrong_track else "request['subject_track_id']"
    extra = "out.joinpath('debug.pkl').write_bytes(b'nope')" if extra_result else ""
    path.write_text(
        f"""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-workspace', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
p.add_argument('--bodyrig-source', action='append', required=True)
a = p.parse_args()
request_text = Path(a.bodyrig_request).read_text(encoding='utf-8')
request = json.loads(request_text)
if len(a.bodyrig_source) != request['source_count']:
    raise SystemExit(10)
for source in a.bodyrig_source:
    if source in request_text:
        raise SystemExit(11)
    if not Path(source).is_file():
        raise SystemExit(12)
workspace = Path(a.bodyrig_workspace)
workspace.joinpath('face-crop.private').write_bytes(b'derived private fixture')
out = Path(a.bodyrig_output)
identity = {{
    'format': 'bodyrig-visual-identity',
    'version': 1,
    'adapter': a.bodyrig_adapter,
    'revision': a.bodyrig_revision,
    'source_count': request['source_count'],
    'subject_track_id': {track_expression},
    'capture': {{
        'observed_frames': request['observed_frames'],
        'face_frames': 80,
        'full_body_frames': 100,
        'side_body_frames': 25,
        'rear_body_frames': 20,
    }},
    'coverage': {{
        'face': 0.9,
        'hair_or_scalp': 0.8,
        'skin': 0.75,
        'clothing': 0.85,
        'full_body': 0.95,
        'back': 0.6,
    }},
    'quality': {{'sharpness': 0.8, 'lighting': 0.7, 'visibility': 0.9}},
    'privacy': {{'contains_source_media': False, 'contains_biometric_template': False}},
}}
out.joinpath('identity.json').write_text(json.dumps(identity), encoding='utf-8')
{extra}
""",
        encoding="utf-8",
    )


def _fixture(tmp_path: Path, *, wrong_track: bool = False, extra_result: bool = False):
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(_proof()), encoding="utf-8")
    source1 = tmp_path / "source-one.mp4"
    source2 = tmp_path / "source-two.mp4"
    source1.write_bytes(b"video fixture one")
    source2.write_bytes(b"video fixture two")
    adapter = tmp_path / "capture_adapter.py"
    _adapter(adapter, wrong_track=wrong_track, extra_result=extra_result)
    config = {
        "format": "bodyrig-identity-capture-config",
        "version": 1,
        "adapter": "fixture-identity-capture",
        "revision": "capture-rev-1",
        "command": [sys.executable, str(adapter)],
        "timeout_seconds": 30,
    }
    config_path = tmp_path / "capture-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return proof_path, source1, source2, config_path


def test_capture_cli_creates_profile_and_private_workspace_without_source_paths(tmp_path: Path):
    proof_path, source1, source2, config_path = _fixture(tmp_path)
    workspace = tmp_path / "identity-workspace"
    output = tmp_path / "identity.json"

    result = capture_main(
        [
            str(proof_path),
            str(source1),
            str(source2),
            "--config",
            str(config_path),
            "--workspace",
            str(workspace),
            "--out",
            str(output),
        ]
    )
    assert result == 0
    identity = json.loads(output.read_text(encoding="utf-8"))
    assert identity["subject_track_id"] == "7"
    assert identity["source_count"] == 2
    assert workspace.joinpath("face-crop.private").is_file()
    serialized = output.read_text(encoding="utf-8")
    assert str(source1) not in serialized
    assert str(source2) not in serialized
    assert str(workspace) not in serialized
    assert str(config_path) not in serialized


def test_capture_cli_rejects_wrong_subject_and_removes_private_workspace(tmp_path: Path):
    proof_path, source1, source2, config_path = _fixture(tmp_path, wrong_track=True)
    workspace = tmp_path / "identity-workspace"
    output = tmp_path / "identity.json"

    result = capture_main(
        [
            str(proof_path), str(source1), str(source2),
            "--config", str(config_path),
            "--workspace", str(workspace),
            "--out", str(output),
        ]
    )
    assert result == 1
    assert not output.exists()
    assert not workspace.exists()


def test_capture_cli_rejects_extra_result_artifacts_and_removes_workspace(tmp_path: Path):
    proof_path, source1, source2, config_path = _fixture(tmp_path, extra_result=True)
    workspace = tmp_path / "identity-workspace"
    output = tmp_path / "identity.json"

    result = capture_main(
        [
            str(proof_path), str(source1), str(source2),
            "--config", str(config_path),
            "--workspace", str(workspace),
            "--out", str(output),
        ]
    )
    assert result == 1
    assert not output.exists()
    assert not workspace.exists()


def test_capture_cli_rejects_source_count_mismatch_before_workspace_creation(tmp_path: Path):
    proof_path, source1, _, config_path = _fixture(tmp_path)
    workspace = tmp_path / "identity-workspace"
    output = tmp_path / "identity.json"

    result = capture_main(
        [
            str(proof_path), str(source1),
            "--config", str(config_path),
            "--workspace", str(workspace),
            "--out", str(output),
        ]
    )
    assert result == 1
    assert not output.exists()
    assert not workspace.exists()
