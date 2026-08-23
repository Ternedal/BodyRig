from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

from bodyrig.external_fitter_cli import main as fit_main
from bodyrig.identity_capture_cli import main as capture_main
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


def test_source_to_identity_to_external_fit_to_mrbody(tmp_path: Path):
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
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    source1 = tmp_path / "person-1.mp4"
    source2 = tmp_path / "person-2.mp4"
    source1.write_bytes(b"private video one")
    source2.write_bytes(b"private video two")

    capture_adapter = tmp_path / "capture_adapter.py"
    capture_adapter.write_text(
        """
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
for source in a.bodyrig_source:
    if source in request_text:
        raise SystemExit(20)
workspace = Path(a.bodyrig_workspace)
workspace.joinpath('face-crop.private').write_bytes(b'private derived identity material')
workspace.joinpath('clothing.private').write_bytes(b'private derived clothing material')
identity = {
    'format': 'bodyrig-visual-identity',
    'version': 1,
    'adapter': a.bodyrig_adapter,
    'revision': a.bodyrig_revision,
    'source_count': request['source_count'],
    'subject_track_id': request['subject_track_id'],
    'capture': {
        'observed_frames': request['observed_frames'],
        'face_frames': 80,
        'full_body_frames': 100,
        'side_body_frames': 25,
        'rear_body_frames': 20,
    },
    'coverage': {
        'face': 0.9, 'hair_or_scalp': 0.8, 'skin': 0.75,
        'clothing': 0.85, 'full_body': 0.95, 'back': 0.6,
    },
    'quality': {'sharpness': 0.8, 'lighting': 0.7, 'visibility': 0.9},
    'privacy': {'contains_source_media': False, 'contains_biometric_template': False},
}
Path(a.bodyrig_output, 'identity.json').write_text(json.dumps(identity), encoding='utf-8')
""",
        encoding="utf-8",
    )
    capture_config = {
        "format": "bodyrig-identity-capture-config",
        "version": 1,
        "adapter": "fixture-capture",
        "revision": "capture-v1",
        "command": [sys.executable, str(capture_adapter)],
        "timeout_seconds": 30,
    }
    capture_config_path = tmp_path / "capture-config.json"
    capture_config_path.write_text(json.dumps(capture_config), encoding="utf-8")
    identity_path = tmp_path / "identity.json"
    workspace = tmp_path / "identity-workspace"

    capture_exit = capture_main(
        [
            str(proof_path), str(source1), str(source2),
            "--config", str(capture_config_path),
            "--workspace", str(workspace),
            "--out", str(identity_path),
        ]
    )
    assert capture_exit == 0
    assert workspace.joinpath("face-crop.private").is_file()

    fitter_adapter = tmp_path / "fitter_adapter.py"
    fitter_adapter.write_text(
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
request_text = Path(a.bodyrig_request).read_text(encoding='utf-8')
if a.bodyrig_workspace in request_text:
    raise SystemExit(30)
request = json.loads(request_text)
workspace = Path(a.bodyrig_workspace)
if not workspace.joinpath('face-crop.private').is_file():
    raise SystemExit(31)
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
    fitter_config = {
        "format": "bodyrig-external-fitter-config",
        "version": 1,
        "adapter": "fixture-high-fidelity",
        "revision": "fit-v1",
        "command": [sys.executable, str(fitter_adapter)],
        "capabilities": {
            "visual_identity": True,
            "textures": True,
            "hair": True,
            "clothing": True,
        },
        "timeout_seconds": 30,
    }
    fitter_config_path = tmp_path / "fitter-config.json"
    fitter_config_path.write_text(json.dumps(fitter_config), encoding="utf-8")
    package_path = tmp_path / "person-a.mrbody"

    fit_exit = fit_main(
        [
            str(proof_path),
            "--identity-profile", str(identity_path),
            "--identity-workspace", str(workspace),
            "--config", str(fitter_config_path),
            "--body-id", "person-a",
            "--name", "Person A",
            "--out", str(package_path),
        ]
    )
    assert fit_exit == 0

    validated = validate_package(package_path)
    assert validated.manifest["id"] == "person-a"
    assert [stage["stage"] for stage in validated.provenance["pipeline"]] == [
        "body-recovery", "visual-identity-capture", "avatar-fitting"
    ]
    assert validated.provenance["pipeline"][1]["adapter"] == "fixture-capture"
    assert validated.provenance["pipeline"][2]["adapter"] == "fixture-high-fidelity"

    private_strings = [
        str(source1), str(source2), str(workspace), str(capture_adapter), str(fitter_adapter),
        str(capture_config_path), str(fitter_config_path),
    ]
    with zipfile.ZipFile(package_path, "r") as archive:
        portable_text = b"\n".join(
            archive.read(name)
            for name in ("manifest.json", "provenance.json", "bodyprint.json", "checksums.json")
        ).decode("utf-8")
    for private in private_strings:
        assert private not in portable_text
