from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.fidelity_evaluator_cli import (
    FidelityEvaluatorRunnerError,
    REQUIRED_VISIBLE_COMPONENTS,
    _validate_component_visibility,
)


PACKAGE_SHA = "a" * 64
AVATAR_SHA = "b" * 64
REVISION = "c" * 40
BODY_ID = "bodyid-test"


def _write_render(tmp_path: Path, *, mutate=None) -> Path:
    root = tmp_path / "comparison-render"
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True)
    render = snapshots / "fidelity-render-set.json"
    render.write_text(
        json.dumps(
            {
                "format": "bodyrig-fidelity-render-set",
                "version": 1,
                "body_id": BODY_ID,
                "package_sha256": PACKAGE_SHA,
                "semantics": "visual-fidelity-not-identity-verification",
                "snapshots": [],
            }
        ),
        encoding="utf-8",
    )
    components = [
        {
            "label": label,
            "node_name": node,
            "present_in_avatar_bytes": True,
            "instantiated": True,
            "active_in_hierarchy": True,
            "visible_skinned_renderer": True,
            "visible_renderer_count": 1,
        }
        for label, node in REQUIRED_VISIBLE_COMPONENTS.items()
    ]
    report = {
        "format": "bodyrig-component-visibility-probe",
        "version": 1,
        "observed_at": "2026-09-14T07:00:00.0000000Z",
        "bodyrig_revision": REVISION,
        "platform": "windows-unity-univrm",
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "avatar_sha256": AVATAR_SHA,
        "required_component_count": 5,
        "present_component_count": 5,
        "visible_component_count": 5,
        "all_required_present_and_visible": True,
        "components": components,
        "human_visual_authority_required": True,
        "production_activation": False,
        "semantics": "component-presence-and-runtime-visibility-not-visual-quality-acceptance",
    }
    if mutate is not None:
        mutate(report)
    (root / "component-visibility-probe.json").write_text(json.dumps(report), encoding="utf-8")
    return render


def test_complete_physical_component_visibility_is_accepted(tmp_path: Path) -> None:
    render = _write_render(tmp_path)
    report = _validate_component_visibility(render)
    assert report["all_required_present_and_visible"] is True
    assert report["visible_component_count"] == 5


def test_missing_physical_visibility_report_fails_closed(tmp_path: Path) -> None:
    render = _write_render(tmp_path)
    (render.parent.parent / "component-visibility-probe.json").unlink()
    with pytest.raises(FidelityEvaluatorRunnerError, match="component-visibility-probe.json"):
        _validate_component_visibility(render)


def test_missing_hair_fails_even_if_aggregate_flag_claims_complete(tmp_path: Path) -> None:
    def mutate(report: dict) -> None:
        hair = next(item for item in report["components"] if item["label"] == "hair")
        hair["present_in_avatar_bytes"] = False
        hair["instantiated"] = False
        hair["active_in_hierarchy"] = False
        hair["visible_skinned_renderer"] = False
        hair["visible_renderer_count"] = 0
        # Deliberately leave all aggregate counts/flag at the forged PASS values.

    render = _write_render(tmp_path, mutate=mutate)
    with pytest.raises(FidelityEvaluatorRunnerError, match="required component hair"):
        _validate_component_visibility(render)


def test_package_identity_must_match_render_manifest(tmp_path: Path) -> None:
    render = _write_render(tmp_path, mutate=lambda report: report.__setitem__("package_sha256", "d" * 64))
    with pytest.raises(FidelityEvaluatorRunnerError, match="package differs"):
        _validate_component_visibility(render)


def test_duplicate_component_label_fails_closed(tmp_path: Path) -> None:
    def mutate(report: dict) -> None:
        report["components"][1]["label"] = "hair"
        report["components"][1]["node_name"] = REQUIRED_VISIBLE_COMPONENTS["hair"]

    render = _write_render(tmp_path, mutate=mutate)
    with pytest.raises(FidelityEvaluatorRunnerError, match="invalid or duplicated"):
        _validate_component_visibility(render)
