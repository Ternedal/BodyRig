from __future__ import annotations

import json
import sys
from pathlib import Path

from bodyrig.external_fitter_cli import main as external_main
from bodyrig.package import validate_package
from bodyrig.portable_identity import build_portable_identity


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


def test_external_fitter_uses_portable_identity_as_package_authority(tmp_path: Path):
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
    source_a = tmp_path / "a.mp4"
    source_b = tmp_path / "b.mp4"
    source_a.write_bytes(b"source-a")
    source_b.write_bytes(b"source-b")
    receipt = build_portable_identity(
        proof=proof,
        visual_identity=identity,
        source_files=[source_a, source_b],
        requested_alias="performer-123",
    )

    proof_path = tmp_path / "proof.json"
    identity_path = tmp_path / "identity.json"
    receipt_path = tmp_path / "portable-identity.json"
    workspace = tmp_path / "private-workspace"
    adapter = tmp_path / "adapter.py"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    workspace.mkdir()
    (workspace / "private.bin").write_bytes(b"private")

    adapter.write_text(
        """
import argparse
import hashlib
import json
from pathlib import Path
from bodyrig.avatar import ProceduralAvatarFitter
p=argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-workspace', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
a=p.parse_args()
request=json.loads(Path(a.bodyrig_request).read_text(encoding='utf-8'))
fitted=ProceduralAvatarFitter().fit(request['bodyprint'], name=request['name'])
out=Path(a.bodyrig_output)
out.joinpath('avatar.vrm').write_bytes(fitted.avatar_vrm)
out.joinpath('thumbnail.png').write_bytes(fitted.thumbnail_png)
out.joinpath('result.json').write_text(json.dumps({
  'format':'bodyrig-avatar-fit-result','version':1,
  'adapter':a.bodyrig_adapter,'revision':a.bodyrig_revision,
  'visual_identity':'source-derived',
  'avatar_sha256':hashlib.sha256(fitted.avatar_vrm).hexdigest(),
  'thumbnail_sha256':hashlib.sha256(fitted.thumbnail_png).hexdigest(),
}), encoding='utf-8')
""",
        encoding="utf-8",
    )
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
            "clothing": True,
        },
        "timeout_seconds": 30,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = tmp_path / "alias-filename.mrbody"

    assert external_main(
        [
            str(proof_path),
            "--identity-profile", str(identity_path),
            "--identity-workspace", str(workspace),
            "--config", str(config_path),
            "--body-id", "performer-123",
            "--portable-identity", str(receipt_path),
            "--name", "Fixture Person",
            "--out", str(output),
        ]
    ) == 0

    validated = validate_package(output)
    assert validated.manifest["id"] == receipt["body_id"]
    identity_stage = next(
        stage for stage in validated.provenance["pipeline"] if stage["stage"] == "identity_content"
    )
    assert identity_stage == {
        "stage": "identity_content",
        "adapter": "bodyrig.portable_identity",
        "revision": receipt["body_id"].removeprefix("bodyid-"),
    }


def test_external_fitter_rejects_portable_identity_alias_mismatch(tmp_path: Path):
    proof = {
        "format": "bodyrig-recovery-proof",
        "version": 1,
        "source_count": 1,
        "adapter": "fixture-recovery",
        "revision": "recovery-v1",
        "track_id": "7",
        "observed_frames": 20,
        "bodyprint": BODYPRINT,
    }
    identity = {
        "format": "bodyrig-visual-identity",
        "version": 1,
        "adapter": "fixture-capture",
        "revision": "capture-v1",
        "source_count": 1,
        "subject_track_id": "7",
        "capture": {"observed_frames":20,"face_frames":10,"full_body_frames":10,"side_body_frames":0,"rear_body_frames":0},
        "coverage": {"face":0.5,"hair_or_scalp":0.5,"skin":0.5,"clothing":0.5,"full_body":0.5,"back":0.0},
        "quality": {"sharpness":0.5,"lighting":0.5,"visibility":0.5},
        "privacy": {"contains_source_media":False,"contains_biometric_template":False},
    }
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    receipt = build_portable_identity(
        proof=proof,
        visual_identity=identity,
        source_files=[source],
        requested_alias="expected-alias",
    )
    proof_path = tmp_path / "proof.json"
    identity_path = tmp_path / "identity.json"
    receipt_path = tmp_path / "portable.json"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "format":"bodyrig-external-fitter-config","version":1,
        "adapter":"fixture-high-fidelity","revision":"1",
        "command":[sys.executable,"unused.py"],
        "capabilities":{"visual_identity":True,"textures":True,"hair":False,"clothing":True},
        "timeout_seconds":30,
    }), encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = tmp_path / "out.mrbody"
    assert external_main([
        str(proof_path), "--identity-profile", str(identity_path),
        "--identity-workspace", str(workspace), "--config", str(config_path),
        "--body-id", "wrong-alias", "--portable-identity", str(receipt_path),
        "--name", "Fixture", "--out", str(output),
    ]) == 1
    assert not output.exists()
