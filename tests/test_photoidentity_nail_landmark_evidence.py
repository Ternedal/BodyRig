from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import bodyrig.photoidentity_nail_landmark_evidence as evidence
from bodyrig.photoidentity_nail_landmark_evidence import (
    PhotoIdentityNailLandmarkEvidenceError,
    build_landmark_evidence,
    validate_landmark_evidence,
)
from bodyrig.photoidentity_nail_landmarks import project_nail_landmarks


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _points(count: int, *, base_x: float, base_y: float, spacing: float, confidence: float) -> list[float]:
    values: list[float] = []
    for index in range(count):
        values.extend([base_x + (index % 5) * spacing, base_y + (index // 5) * spacing, confidence])
    return values


def _payload() -> dict:
    body = _points(25, base_x=300.0, base_y=400.0, spacing=55.0, confidence=0.0)
    for index in (19, 20, 21, 22, 23, 24):
        body[index * 3] = 450.0 + (index - 19) * 65.0
        body[index * 3 + 1] = 1450.0 + ((index - 19) % 3) * 45.0
        body[index * 3 + 2] = 0.95
    return {
        "people": [
            {
                "pose_keypoints_2d": body,
                "hand_left_keypoints_2d": _points(21, base_x=150.0, base_y=600.0, spacing=65.0, confidence=0.95),
                "hand_right_keypoints_2d": _points(21, base_x=1150.0, base_y=600.0, spacing=65.0, confidence=0.95),
            }
        ]
    }


def _projection(region: str = "left_fingernails") -> dict:
    return project_nail_landmarks(
        _payload(),
        region=region,
        frame_width=1920,
        frame_height=1920,
    )


def _canonical_evidence() -> dict:
    return {
        "format": evidence.FORMAT,
        "version": evidence.VERSION,
        "policy_revision": evidence.POLICY_REVISION,
        "performer_id": "42",
        "bodyrig_revision": "b" * 40,
        "input_discovery_sha256": "a" * 64,
        "private_source_manifest_set_sha256": "c" * 64,
        "openpose_adapter": evidence.OPENPOSE_ADAPTER,
        "openpose_revision": evidence.OPENPOSE_REVISION,
        "record_count": 1,
        "records": [
            {
                "candidate_id": "nailcand-" + "d" * 32,
                "region": "left_fingernails",
                "scene_id": "scene-a",
                "source_media_sha256": "e" * 64,
                "source_frame_sha256": "f" * 64,
                "closeup_image_sha256": "1" * 64,
                "projection": _projection(),
            }
        ],
        "source_paths_persisted": False,
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }


def test_validator_accepts_canonical_evidence_and_rejects_boolean_v1() -> None:
    value = _canonical_evidence()
    validated = validate_landmark_evidence(value)
    assert validated["record_count"] == 1
    assert validated["records"][0]["projection"]["application_ready"] is True

    bad = _canonical_evidence()
    bad["version"] = True
    with pytest.raises(PhotoIdentityNailLandmarkEvidenceError, match="format/version/revision mismatch"):
        validate_landmark_evidence(bad)


def test_validator_rejects_zero_records_authority_escalation_and_duplicates() -> None:
    empty = _canonical_evidence()
    empty["records"] = []
    empty["record_count"] = 0
    with pytest.raises(PhotoIdentityNailLandmarkEvidenceError, match="record count is invalid"):
        validate_landmark_evidence(empty)

    elevated = _canonical_evidence()
    elevated["package_application_authority"] = True
    with pytest.raises(PhotoIdentityNailLandmarkEvidenceError, match="evidence-only authority boundary"):
        validate_landmark_evidence(elevated)

    duplicate = _canonical_evidence()
    duplicate["records"].append(dict(duplicate["records"][0]))
    duplicate["record_count"] = 2
    with pytest.raises(PhotoIdentityNailLandmarkEvidenceError, match="duplicate nail landmark record"):
        validate_landmark_evidence(duplicate)


def test_validator_rejects_inconsistent_projection_readiness() -> None:
    value = _canonical_evidence()
    value["records"][0]["projection"] = dict(value["records"][0]["projection"])
    value["records"][0]["projection"]["application_ready"] = False
    with pytest.raises(PhotoIdentityNailLandmarkEvidenceError, match="application readiness is inconsistent"):
        validate_landmark_evidence(value)


def _build_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict, dict, dict, str]:
    public_path = tmp_path / "nail-source-candidates.json"
    public_path.write_text("{}\n", encoding="utf-8")
    private_root = tmp_path / "private-nail-source-candidates"
    candidate_root = private_root / "candidate-0001"
    candidate_root.mkdir(parents=True)
    frame = candidate_root / "source-frame.png"
    closeup = candidate_root / "left-fingernails.png"
    source = tmp_path / "private-source.mp4"
    source.write_bytes(b"exact-private-source-media")
    Image.new("RGB", (1920, 1920), (120, 110, 100)).save(frame)
    Image.new("RGB", (1024, 1024), (120, 110, 100)).save(closeup)

    candidate_id = "nailcand-" + "2" * 32
    public_candidate = {
        "candidate_id": candidate_id,
        "scene_id": "scene-a",
        "source_media_sha256": _sha(source),
        "source_frame_sha256": _sha(frame),
        "regions": {"left_fingernails": {"image_sha256": _sha(closeup)}},
    }
    private_candidate = {
        **public_candidate,
        "candidate_directory": str(candidate_root),
        "source_path": str(source),
        "region_images": {"left_fingernails": str(closeup)},
    }
    public = {
        "performer_id": "42",
        "bodyrig_revision": "4" * 40,
        "private_source_manifest_set_sha256": "5" * 64,
        "openpose_adapter": evidence.OPENPOSE_ADAPTER,
        "openpose_revision": evidence.OPENPOSE_REVISION,
    }
    return public_path, private_root, candidate_root, source, public_candidate, private_candidate, public, candidate_id


def test_build_binds_exact_candidate_bytes_without_persisting_private_paths(monkeypatch, tmp_path: Path) -> None:
    public_path, private_root, candidate_root, source, public_candidate, private_candidate, public, candidate_id = _build_fixture(tmp_path)
    private = {"unused": True}
    monkeypatch.setattr(
        evidence,
        "_load_discovery",
        lambda root: (public_path, public, private_root / "private-candidate-index.json", private),
    )
    monkeypatch.setattr(
        evidence,
        "_candidate_maps",
        lambda public_value, private_value: ({candidate_id: public_candidate}, {candidate_id: private_candidate}),
    )
    monkeypatch.setattr(evidence, "_run_openpose", lambda **kwargs: _payload())

    result = build_landmark_evidence(
        sweep_root=tmp_path,
        distribution="BodyRig",
        openpose="/opt/openpose",
    )

    output = tmp_path / "nail-landmark-projections.json"
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert result["manifest"] == str(output)
    assert persisted["input_discovery_sha256"] == _sha(public_path)
    assert persisted["record_count"] == 1
    assert persisted["records"][0]["source_media_sha256"] == _sha(source)
    assert persisted["records"][0]["source_frame_sha256"] == public_candidate["source_frame_sha256"]
    assert persisted["records"][0]["closeup_image_sha256"] == public_candidate["regions"]["left_fingernails"]["image_sha256"]
    assert persisted["records"][0]["projection"]["application_ready"] is True
    assert persisted["package_application_authority"] is False
    assert persisted["production_activation"] is False
    text = output.read_text(encoding="utf-8")
    assert "private-source.mp4" not in text
    assert str(candidate_root) not in text

    with pytest.raises(PhotoIdentityNailLandmarkEvidenceError, match="already exists"):
        build_landmark_evidence(
            sweep_root=tmp_path,
            distribution="BodyRig",
            openpose="/opt/openpose",
        )


def test_build_rejects_tampered_source_media_before_openpose(monkeypatch, tmp_path: Path) -> None:
    public_path, private_root, _candidate_root, source, public_candidate, private_candidate, public, candidate_id = _build_fixture(tmp_path)
    source.write_bytes(b"tampered-source-media")
    monkeypatch.setattr(evidence, "_load_discovery", lambda root: (public_path, public, private_root / "private.json", {}))
    monkeypatch.setattr(evidence, "_candidate_maps", lambda a, b: ({candidate_id: public_candidate}, {candidate_id: private_candidate}))
    called = False

    def fail_if_called(**kwargs):
        nonlocal called
        called = True
        return _payload()

    monkeypatch.setattr(evidence, "_run_openpose", fail_if_called)
    with pytest.raises(PhotoIdentityNailLandmarkEvidenceError, match="source media bytes changed"):
        build_landmark_evidence(sweep_root=tmp_path, distribution="BodyRig", openpose="/opt/openpose")
    assert called is False


def test_build_rejects_tampered_frame_before_openpose(monkeypatch, tmp_path: Path) -> None:
    public_path, private_root, candidate_root, _source, public_candidate, private_candidate, public, candidate_id = _build_fixture(tmp_path)
    frame = candidate_root / "source-frame.png"
    Image.new("RGB", (1920, 1920), (0, 0, 0)).save(frame)
    monkeypatch.setattr(evidence, "_load_discovery", lambda root: (public_path, public, private_root / "private.json", {}))
    monkeypatch.setattr(evidence, "_candidate_maps", lambda a, b: ({candidate_id: public_candidate}, {candidate_id: private_candidate}))
    called = False

    def fail_if_called(**kwargs):
        nonlocal called
        called = True
        return _payload()

    monkeypatch.setattr(evidence, "_run_openpose", fail_if_called)
    with pytest.raises(PhotoIdentityNailLandmarkEvidenceError, match="source-frame bytes changed"):
        build_landmark_evidence(sweep_root=tmp_path, distribution="BodyRig", openpose="/opt/openpose")
    assert called is False
