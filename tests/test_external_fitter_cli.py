from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

from bodyrig.external_fitter_cli import main as external_main
from bodyrig.package import validate_package


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


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    proof = {
        "format": "bodyrig-recovery-proof",
        "version": 1,
        "source_count": 2,
        "adapter": "fixture-recovery",
        "revision": "recovery-v1",
        "track_id": "7",
        "observed_frames": 120,
        "bodyprint": BODYPRINT,
    }
    identity = {
        "format": "bodyrig-visual-identity",
        "version": 1,
        "adapter": "fixture-capture",
        "revision": "capture-v1",
        "source_count": 2,
        "subject_track_id": "7",
        "capture": {
            "observed_frames": 120,
            "face_frames": 80,
            "full_body_frames": 100,
            "side_body_frames": 25,
            "rear_body_frames": 20,
        },
        "coverage": {
            "face": 0.9,
            "hair_or_scalp": 0.8,
            "skin": 0.75,
            "clothing": 0.85,
            "full_body": 0.95,
            "back": 0.6,
        },
        "quality": {"sharpness": 0.8, "lighting": 0.7, "visibility": 0.9},
        "privacy": {"contains_source_media": False, "contains_biometric_template": False},
    }
    proof_path = tmp_path / "proof.json"
    identity_path = tmp_path / "identity.json"
    workspace = tmp_path / "private-workspace"
    adapter = tmp_path / "adapter.py"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    workspace.mkdir()
    (workspace / "source-private.bin").write_bytes(b"private source fixture")
    adapter.write_text(
        """
import argparse
import hashlib
import json
from pathlib import Path
from bodyrig.avatar import ProceduralAvatarFitter

p = argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-workspace', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
a = p.parse_args()
request = json.loads(Path(a.bodyrig_request).read_text(encoding='utf-8'))
if not Path(a.bodyrig_workspace, 'source-private.bin').is_file():
    raise SystemExit(4)
fitted = ProceduralAvatarFitter().fit(request['bodyprint'], name=request['name'])
out = Path(a.bodyrig_output)
out.joinpath('avatar.vrm').write_bytes(fitted.avatar_vrm)
out.joinpath('thumbnail.png').write_bytes(fitted.thumbnail_png)
out.joinpath('result.json').write_text(json.dumps({
    'format': 'bodyrig-avatar-fit-result',
    'version': 1,
    'adapter': a.bodyrig_adapter,
    'revision': a.bodyrig_revision,
    'visual_identity': 'source-derived',
    'avatar_sha256': hashlib.sha256(fitted.avatar_vrm).hexdigest(),
    'thumbnail_sha256': hashlib.sha256(fitted.thumbnail_png).hexdigest(),
}), encoding='utf-8')
""",
        encoding="utf-8",
    )
    return proof_path, identity_path, workspace, adapter


def test_external_fitter_cli_builds_valid_portable_package(tmp_path: Path):
    proof_path, identity_path, workspace, adapter = _write_fixture(tmp_path)
    config = {
        "format": "bodyrig-external-fitter-config",
        "version": 1,
        "adapter": "fixture-high-fidelity",
        "revision": "fixture-rev-1",
        "command": [sys.executable, str(adapter)],
        "capabilities": {
            "visual_identity": True,
            "textures": True,
            "hair": True,
            "clothing": False,
        },
        "timeout_seconds": 30,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = tmp_path / "fixture.mrbody"

    exit_code = external_main(
        [
            str(proof_path),
            "--identity-profile",
            str(identity_path),
            "--identity-workspace",
            str(workspace),
            "--config",
            str(config_path),
            "--body-id",
            "fixture-person",
            "--name",
            "Fixture Person",
            "--out",
            str(output),
        ]
    )
    assert exit_code == 0
    validated = validate_package(output)
    assert [stage["stage"] for stage in validated.provenance["pipeline"]] == [
        "body-recovery",
        "visual-identity-capture",
        "appearance-boundary",
        "avatar-fitting",
    ]
    assert validated.provenance["pipeline"][2] == {
        "stage": "appearance-boundary",
        "adapter": "bodyrig.garment-policy",
        "revision": "external-outfit-v1",
    }
    assert validated.provenance["pipeline"][-1]["adapter"] == "fixture-high-fidelity"

    with zipfile.ZipFile(output, "r") as archive:
        all_text = b"".join(
            archive.read(name)
            for name in ("manifest.json", "provenance.json", "bodyprint.json")
        ).decode("utf-8")
    assert str(workspace) not in all_text
    assert str(adapter) not in all_text
    assert sys.executable not in all_text


def test_external_fitter_cli_rejects_config_without_identity_capability(tmp_path: Path):
    proof_path, identity_path, workspace, adapter = _write_fixture(tmp_path)
    config = {
        "format": "bodyrig-external-fitter-config",
        "version": 1,
        "adapter": "fixture-high-fidelity",
        "revision": "fixture-rev-1",
        "command": [sys.executable, str(adapter)],
        "capabilities": {
            "visual_identity": False,
            "textures": True,
            "hair": True,
            "clothing": False,
        },
        "timeout_seconds": 30,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = tmp_path / "fixture.mrbody"

    exit_code = external_main(
        [
            str(proof_path),
            "--identity-profile",
            str(identity_path),
            "--identity-workspace",
            str(workspace),
            "--config",
            str(config_path),
            "--body-id",
            "fixture-person",
            "--name",
            "Fixture Person",
            "--out",
            str(output),
        ]
    )
    assert exit_code == 1
    assert not output.exists()
