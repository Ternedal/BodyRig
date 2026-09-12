from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.fidelity_adjustment import (
    FidelityAdjustmentError,
    SEMANTICS,
    build_fidelity_adjustment_plan,
    main,
)


def _evaluation(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-fidelity-evaluation",
        "version": version,
        "semantics": SEMANTICS,
        "measurement": {"scores": {"overall": 0.72}},
        "shape_hint": {
            "shoulder_direction": "wider",
            "hip_direction": "narrower",
            "shoulder_profile_delta": 0.02,
            "hip_profile_delta": -0.03,
        },
    }


def _canonical_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_adjustment_planner_rejects_boolean_evaluation_version() -> None:
    with pytest.raises(FidelityAdjustmentError, match="unsupported fidelity evaluation format/version"):
        build_fidelity_adjustment_plan(_evaluation(True))


def test_adjustment_cli_rejects_persisted_boolean_evaluation_version(tmp_path: Path) -> None:
    source = tmp_path / "evaluation.json"
    output = tmp_path / "adjustment-plan.json"
    source.write_text(json.dumps(_evaluation(True)), encoding="utf-8")

    assert main([str(source), "--out", str(output)]) == 1
    assert not output.exists()


def test_adjustment_planner_accepts_numeric_float_v1_and_preserves_bounded_authority() -> None:
    evaluation = _evaluation(1.0)

    plan = build_fidelity_adjustment_plan(evaluation)

    assert plan["format"] == "bodyrig-fidelity-adjustment-plan"
    assert plan["version"] == 1
    assert plan["semantics"] == SEMANTICS
    assert plan["evaluation_sha256"] == _canonical_sha256(evaluation)
    assert plan["applicable"] is True
    assert plan["feedback"] == "shoulders should be wider; hips should be narrower"

    request = plan["adjustment_request"]
    assert isinstance(request, dict)
    assert request["format"] == "bodyrig-bodyprint-adjustment"
    assert request["version"] == 1
    assert {item["field"] for item in request["changes"]} == {
        "shape.shoulder_to_height",
        "shape.hip_to_height",
    }
