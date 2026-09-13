from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

import bodyrig.hands_feet_nails_uv_domain_evidence as subject


REVISION = "a" * 40
PERSON = "person-" + "1" * 32
BODY = "body-r0001"
CAPTURE = "hfncap-" + "2" * 32
PACKAGE_SHA = "3" * 64
LANDMARK_SHA = "4" * 64


def _region_payload(region: str, index: int) -> dict[str, object]:
    names = list(subject.REGION_JOINT_NAMES[region])
    return {
        "capture_region": region,
        "semantic_region": subject.SEMANTIC_REGIONS[region],
        "target_joint_names": names,
        "target_joint_indices": list(range(index, index + len(names))),
        "vertex_count": 3,
        "uv_count": 3,
        "uv_bounds": {"u_min": 0.1, "v_min": 0.2, "u_max": 0.4, "v_max": 0.6},
        "uv_set_sha256": hashlib.sha256(region.encode("utf-8")).hexdigest(),
    }


def _evidence() -> dict[str, object]:
    return {
        "format": subject.FORMAT,
        "version": subject.VERSION,
        "policy_revision": subject.POLICY_REVISION,
        "person_id": PERSON,
        "body_revision": BODY,
        "capture_id": CAPTURE,
        "landmark_evidence_bodyrig_revision": REVISION,
        "uv_evidence_bodyrig_revision": REVISION,
        "body_id": "body-example",
        "package_sha256": PACKAGE_SHA,
        "landmark_evidence_sha256": LANDMARK_SHA,
        "mesh_name": subject.MESH_NAME,
        "skin_name": subject.SKIN_NAME,
        "mesh_index": 0,
        "skin_index": 0,
        "primitive_index": 0,
        "weight_threshold": subject.WEIGHT_THRESHOLD,
        "regions": {
            region: _region_payload(region, offset)
            for offset, region in enumerate(subject.REGION_JOINT_NAMES)
        },
        "exact_source_package_bound": True,
        "geometry_modified": False,
        "texture_modified": False,
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }


def test_region_domain_uses_only_target_joint_weight_at_threshold() -> None:
    result = subject._region_domain(
        capture_region="left_foot",
        semantic_region="left_toenails",
        target_names=("target",),
        joint_names=["other", "target"],
        uvs=[(0.1, 0.2), (0.3, 0.4), (0.5, 0.6), (0.9, 0.9)],
        joints=[(1, 0, 0, 0)] * 4,
        weights=[
            (0.20, 0.80, 0.0, 0.0),
            (0.50, 0.50, 0.0, 0.0),
            (1.00, 0.00, 0.0, 0.0),
            (0.19, 0.81, 0.0, 0.0),
        ],
    )

    assert result["vertex_count"] == 3
    assert result["uv_count"] == 3
    assert result["uv_bounds"] == {"u_min": 0.1, "v_min": 0.2, "u_max": 0.5, "v_max": 0.6}
    expected = json.dumps([(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)], separators=(",", ":")).encode("utf-8")
    assert result["uv_set_sha256"] == hashlib.sha256(expected).hexdigest()


def test_region_domain_rejects_insufficient_target_vertices() -> None:
    with pytest.raises(subject.HandsFeetNailsUvDomainEvidenceError, match="too few skinned vertices"):
        subject._region_domain(
            capture_region="left_foot",
            semantic_region="left_toenails",
            target_names=("target",),
            joint_names=["other", "target"],
            uvs=[(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)],
            joints=[(1, 0, 0, 0)] * 3,
            weights=[(0.19, 0.81, 0.0, 0.0)] * 3,
        )


def test_validate_uv_domain_evidence_preserves_evidence_only_boundary() -> None:
    result = subject.validate_uv_domain_evidence(_evidence())
    assert result["exact_source_package_bound"] is True
    assert result["geometry_modified"] is False
    assert result["texture_modified"] is False
    assert result["package_application_authority"] is False
    assert result["human_review_required"] is True
    assert result["production_activation"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exact_source_package_bound", False),
        ("geometry_modified", True),
        ("texture_modified", True),
        ("package_application_authority", True),
        ("human_review_required", False),
        ("production_activation", True),
    ],
)
def test_validate_uv_domain_evidence_rejects_authority_boundary_drift(field: str, value: object) -> None:
    evidence = _evidence()
    evidence[field] = value
    with pytest.raises(subject.HandsFeetNailsUvDomainEvidenceError, match="evidence-only authority boundary"):
        subject.validate_uv_domain_evidence(evidence)


def test_derive_fails_closed_before_package_read_when_landmarks_are_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    landmark_path = tmp_path / "landmark.json"
    landmark_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        subject,
        "validate_landmark_evidence",
        lambda value: {
            "person_id": PERSON,
            "body_revision": BODY,
            "capture_id": CAPTURE,
            "evidence_bodyrig_revision": REVISION,
            "all_regions_application_ready": False,
        },
    )

    package_read = False

    def fail_if_called(path: Path) -> tuple[bytes, str, str]:
        nonlocal package_read
        package_read = True
        raise AssertionError("package must not be read")

    monkeypatch.setattr(subject, "_package_avatar", fail_if_called)
    with pytest.raises(subject.HandsFeetNailsUvDomainEvidenceError, match="fails closed"):
        subject.derive_uv_domain_evidence(
            tmp_path,
            PERSON,
            body_revision=BODY,
            capture_id=CAPTURE,
            landmark_evidence_path=landmark_path,
            package_path=tmp_path / "person.mrbody",
            uv_bodyrig_revision=REVISION,
        )
    assert package_read is False


def _add_accessor(
    document: dict[str, object],
    binary: bytearray,
    raw: bytes,
    component: int,
    kind: str,
    count: int,
) -> int:
    while len(binary) % 4:
        binary.append(0)
    offset = len(binary)
    binary.extend(raw)
    views = document.setdefault("bufferViews", [])
    accessors = document.setdefault("accessors", [])
    assert isinstance(views, list) and isinstance(accessors, list)
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
    accessors.append({"bufferView": len(views) - 1, "componentType": component, "count": count, "type": kind})
    return len(accessors) - 1


def test_derive_binds_exact_package_and_derives_all_four_uv_domains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    landmark_path = tmp_path / "landmark.json"
    landmark_path.write_text('{"marker":1}\n', encoding="utf-8")
    landmark_sha = hashlib.sha256(landmark_path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        subject,
        "validate_landmark_evidence",
        lambda value: {
            "person_id": PERSON,
            "body_revision": BODY,
            "capture_id": CAPTURE,
            "evidence_bodyrig_revision": REVISION,
            "all_regions_application_ready": True,
        },
    )

    all_names: list[str] = []
    for names in subject.REGION_JOINT_NAMES.values():
        for name in names:
            if name not in all_names:
                all_names.append(name)
    nodes = [{"name": name} for name in all_names]
    mesh_node = len(nodes)
    nodes.append({"name": "Body", "mesh": 0, "skin": 0})
    document: dict[str, object] = {
        "nodes": nodes,
        "skins": [{"name": subject.SKIN_NAME, "joints": list(range(len(all_names))) }],
        "meshes": [],
    }
    binary = bytearray()

    uv_values: list[tuple[float, float]] = []
    joint_values: list[tuple[int, int, int, int]] = []
    weight_values: list[tuple[float, float, float, float]] = []
    for region_index, names in enumerate(subject.REGION_JOINT_NAMES.values()):
        joint_index = all_names.index(names[0])
        base_u = 0.05 + 0.20 * region_index
        for offset in range(3):
            uv_values.append((base_u + 0.02 * offset, 0.10 + 0.05 * offset))
            joint_values.append((joint_index, 0, 0, 0))
            weight_values.append((1.0, 0.0, 0.0, 0.0))

    uv_raw = b"".join(struct.pack("<2f", *item) for item in uv_values)
    joint_raw = b"".join(struct.pack("<4H", *item) for item in joint_values)
    weight_raw = b"".join(struct.pack("<4f", *item) for item in weight_values)
    uv_accessor = _add_accessor(document, binary, uv_raw, 5126, "VEC2", len(uv_values))
    joint_accessor = _add_accessor(document, binary, joint_raw, 5123, "VEC4", len(joint_values))
    weight_accessor = _add_accessor(document, binary, weight_raw, 5126, "VEC4", len(weight_values))
    document["meshes"] = [{
        "name": subject.MESH_NAME,
        "primitives": [{
            "attributes": {
                "TEXCOORD_0": uv_accessor,
                "JOINTS_0": joint_accessor,
                "WEIGHTS_0": weight_accessor,
            }
        }],
    }]
    assert mesh_node == len(all_names)

    monkeypatch.setattr(subject, "_package_avatar", lambda path: (b"avatar", "body-example", PACKAGE_SHA))
    monkeypatch.setattr(subject, "_read_glb", lambda value: (document, bytes(binary)))

    result = subject.derive_uv_domain_evidence(
        tmp_path,
        PERSON,
        body_revision=BODY,
        capture_id=CAPTURE,
        landmark_evidence_path=landmark_path,
        package_path=tmp_path / "person.mrbody",
        uv_bodyrig_revision=REVISION,
    )

    assert result["package_sha256"] == PACKAGE_SHA
    assert result["landmark_evidence_sha256"] == landmark_sha
    assert result["mesh_name"] == subject.MESH_NAME
    assert result["skin_name"] == subject.SKIN_NAME
    assert set(result["regions"]) == set(subject.REGION_JOINT_NAMES)
    assert all(item["vertex_count"] == 3 for item in result["regions"].values())
    assert result["geometry_modified"] is False
    assert result["texture_modified"] is False
    assert result["production_activation"] is False
    assert Path(result["manifest"]).is_file()
