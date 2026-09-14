from __future__ import annotations

import pytest

from bodyrig.fidelity_component_gap import (
    FidelityComponentGapError,
    REQUIRED_COMPONENTS,
    build_gap_plan,
    validate_visibility_report,
)
from bodyrig.high_fidelity_face_secondary_runtime import NODE_NAME as FACE_SECONDARY_RUNTIME_NODE


REVISION = "a" * 40
PACKAGE = "b" * 64
AVATAR = "c" * 64


def report(*missing: str) -> dict:
    missing_set = set(missing)
    components = []
    for label, node in REQUIRED_COMPONENTS:
        visible = label not in missing_set
        components.append(
            {
                "label": label,
                "node_name": node,
                "present_in_avatar_bytes": visible,
                "instantiated": visible,
                "active_in_hierarchy": visible,
                "visible_skinned_renderer": visible,
                "visible_renderer_count": 1 if visible else 0,
            }
        )
    present = sum(1 for item in components if item["present_in_avatar_bytes"])
    visible = sum(1 for item in components if item["visible_skinned_renderer"])
    return {
        "format": "bodyrig-component-visibility-probe",
        "version": 1,
        "observed_at": "2026-09-14T08:00:00Z",
        "bodyrig_revision": REVISION,
        "platform": "windows-unity-univrm",
        "body_id": "performer-42",
        "package_sha256": PACKAGE,
        "avatar_sha256": AVATAR,
        "required_component_count": 5,
        "present_component_count": present,
        "visible_component_count": visible,
        "all_required_present_and_visible": visible == 5,
        "components": components,
        "human_visual_authority_required": True,
        "production_activation": False,
        "semantics": "component-presence-and-runtime-visibility-not-visual-quality-acceptance",
    }


def render_set() -> dict:
    return {"body_id": "performer-42", "package_sha256": PACKAGE}


def test_complete_component_set_routes_to_human_visual_qa_without_release_authority() -> None:
    plan = build_gap_plan(report(), render_set=render_set())

    assert plan["state"] == "machine-component-complete-human-review-required"
    assert plan["missing_components"] == []
    assert plan["drawable_components"] == [label for label, _node in REQUIRED_COMPONENTS]
    assert plan["strict_machine_scoring_ready"] is True
    assert plan["next_actions"] == [
        {
            "id": "human-visual-qa",
            "components": [label for label, _node in REQUIRED_COMPONENTS],
            "operator_input_required": True,
            "implementation_required": False,
            "reason": "All machine-required components are physically drawable; visual quality still requires human review and does not imply release acceptance.",
        }
    ]
    assert plan["human_visual_authority_required"] is True
    assert plan["production_activation"] is False


def test_missing_hair_and_eyes_routes_to_existing_retained_composition() -> None:
    plan = build_gap_plan(report("hair", "eyes"), render_set=render_set())

    assert plan["state"] == "composition-required"
    assert plan["strict_machine_scoring_ready"] is False
    assert plan["missing_components"][:2] == ["hair", "eyes"]
    assert plan["next_actions"][0]["id"] == "retained-source-hair-eye-composition"
    assert plan["next_actions"][0]["components"] == ["hair", "eyes"]
    assert plan["next_actions"][0]["operator_input_required"] is False
    assert plan["next_actions"][0]["implementation_required"] is False


def test_missing_face_secondary_routes_to_existing_review_composer_without_fake_promotion() -> None:
    plan = build_gap_plan(report("face-secondary"), render_set=render_set())

    action = plan["next_actions"][0]
    assert action["id"] == "face-secondary-review-composition"
    assert action["components"] == ["face-secondary"]
    assert action["operator_input_required"] is False
    assert action["implementation_required"] is False
    assert "existing comparison-only face-secondary runtime composer" in action["reason"]
    assert "without promotion or release authority" in action["reason"]
    assert dict(REQUIRED_COMPONENTS)["face-secondary"] == FACE_SECONDARY_RUNTIME_NODE


def test_missing_nails_routes_to_source_bound_hfn_with_operator_evidence_boundary() -> None:
    plan = build_gap_plan(report("fingernails", "toenails"), render_set=render_set())

    action = plan["next_actions"][0]
    assert action["id"] == "source-bound-hfn-continuation"
    assert action["components"] == ["fingernails", "toenails"]
    assert action["operator_input_required"] is True
    assert action["implementation_required"] is False
    assert "capture/UV evidence may be required" in action["reason"]


def test_visibility_aggregate_must_match_component_entries() -> None:
    value = report("hair")
    value["visible_component_count"] = 5
    with pytest.raises(FidelityComponentGapError, match="aggregate counts"):
        validate_visibility_report(value)

    value = report("hair")
    value["all_required_present_and_visible"] = True
    with pytest.raises(FidelityComponentGapError, match="aggregate completeness"):
        validate_visibility_report(value)


def test_visibility_state_transitions_fail_closed() -> None:
    value = report("hair")
    hair = next(item for item in value["components"] if item["label"] == "hair")
    hair["present_in_avatar_bytes"] = False
    hair["instantiated"] = True
    with pytest.raises(FidelityComponentGapError, match="instantiated without source presence"):
        validate_visibility_report(value)

    value = report("eyes")
    eyes = next(item for item in value["components"] if item["label"] == "eyes")
    eyes["visible_skinned_renderer"] = True
    eyes["visible_renderer_count"] = 0
    with pytest.raises(FidelityComponentGapError, match="visible without an active hierarchy|renderer count"):
        validate_visibility_report(value)


def test_render_set_binding_rejects_stale_visibility_probe() -> None:
    stale = render_set()
    stale["package_sha256"] = "d" * 64
    with pytest.raises(FidelityComponentGapError, match="package differs"):
        build_gap_plan(report(), render_set=stale)
