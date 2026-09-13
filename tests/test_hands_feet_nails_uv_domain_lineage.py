from __future__ import annotations

import struct

import bodyrig.hands_feet_nails_uv_domain_evidence as subject


def _add_accessor(document: dict[str, object], binary: bytearray, raw: bytes, component: int, kind: str, count: int) -> int:
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


def test_canonical_mesh_accepts_post_donor_topology_name() -> None:
    names: list[str] = []
    for region_names in subject.REGION_JOINT_NAMES.values():
        for name in region_names:
            if name not in names:
                names.append(name)
    nodes = [{"name": name} for name in names]
    nodes.append({"name": "Body", "mesh": 0, "skin": 0})
    document: dict[str, object] = {
        "nodes": nodes,
        "skins": [{"name": subject.SKIN_NAME, "joints": list(range(len(names)))}],
        "meshes": [],
    }
    binary = bytearray()
    count = 3
    uv = _add_accessor(document, binary, b"".join(struct.pack("<2f", 0.1 + i * 0.1, 0.2 + i * 0.1) for i in range(count)), 5126, "VEC2", count)
    joints = _add_accessor(document, binary, b"".join(struct.pack("<4H", 0, 0, 0, 0) for _ in range(count)), 5123, "VEC4", count)
    weights = _add_accessor(document, binary, b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in range(count)), 5126, "VEC4", count)
    document["meshes"] = [{
        "name": subject.DONOR_MESH_NAME,
        "primitives": [{"attributes": {"TEXCOORD_0": uv, "JOINTS_0": joints, "WEIGHTS_0": weights}}],
    }]

    mesh_index, skin_index, primitive_index, primitive, _joint_nodes, joint_names = subject._canonical_mesh(document)

    assert mesh_index == 0
    assert skin_index == 0
    assert primitive_index == 0
    assert primitive["attributes"]["TEXCOORD_0"] == uv
    assert joint_names == names


def test_validator_accepts_documented_mesh_lineage_names() -> None:
    base = {
        "format": subject.FORMAT,
        "version": subject.VERSION,
        "policy_revision": subject.POLICY_REVISION,
        "person_id": "person-" + "1" * 32,
        "body_revision": "body-r0001",
        "capture_id": "hfncap-" + "2" * 32,
        "landmark_evidence_bodyrig_revision": "a" * 40,
        "uv_evidence_bodyrig_revision": "b" * 40,
        "body_id": "body-example",
        "package_sha256": "c" * 64,
        "landmark_evidence_sha256": "d" * 64,
        "skin_name": subject.SKIN_NAME,
        "mesh_index": 0,
        "skin_index": 0,
        "primitive_index": 0,
        "weight_threshold": subject.WEIGHT_THRESHOLD,
        "regions": {},
        "exact_source_package_bound": True,
        "geometry_modified": False,
        "texture_modified": False,
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }
    offset = 0
    for region, names in subject.REGION_JOINT_NAMES.items():
        base["regions"][region] = {
            "capture_region": region,
            "semantic_region": subject.SEMANTIC_REGIONS[region],
            "target_joint_names": list(names),
            "target_joint_indices": list(range(offset, offset + len(names))),
            "vertex_count": 3,
            "uv_count": 3,
            "uv_bounds": {"u_min": 0.1, "v_min": 0.1, "u_max": 0.2, "v_max": 0.2},
            "uv_set_sha256": "e" * 64,
        }
        offset += len(names)

    for mesh_name in subject.MESH_NAMES:
        evidence = dict(base)
        evidence["regions"] = dict(base["regions"])
        evidence["mesh_name"] = mesh_name
        assert subject.validate_uv_domain_evidence(evidence)["mesh_name"] == mesh_name
