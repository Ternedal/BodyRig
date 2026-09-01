from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "contracts" / "bodyrig-rig-acceptance-v1.schema.json"


def _policy() -> tuple[dict, dict]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "BodyRig Target Rig Acceptance v1"
    assert len(schema.get("allOf", [])) == 1
    conditional = schema["allOf"][0]
    return conditional["if"], conditional["then"]


def test_non_placeholder_gate_a_requires_physical_lineage_skin_and_topology_qa() -> None:
    condition, consequence = _policy()

    package = condition["properties"]["package"]
    assert condition["required"] == ["package"]
    assert package["required"] == ["placeholder_avatar"]
    assert package["properties"]["placeholder_avatar"] == {"const": False}
    assert set(consequence["required"]) == {
        "physical_clone",
        "skin_qa",
        "mesh_topology_qa",
    }


def test_placeholder_diagnostic_gate_a_does_not_globally_require_physical_lineage() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    required = set(schema["required"])

    assert "physical_clone" not in required
    assert "skin_qa" not in required
    assert "mesh_topology_qa" not in required
    assert schema["properties"]["physical_clone"]["properties"]["mode"] == {
        "const": "stash-sith-high-fidelity"
    }
    assert schema["properties"]["skin_qa"]["properties"]["manual_review_required"] == {
        "const": True
    }
    assert schema["properties"]["mesh_topology_qa"]["properties"]["structural_pass"] == {
        "const": True
    }
