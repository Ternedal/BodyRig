from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from bodyrig.fidelity_evaluator_cli import FidelityEvaluatorRunnerError, _read_result


MEASUREMENT = {
    "format": "bodyrig-fidelity-measurement",
    "version": 1,
    "iteration": 1,
    "candidate_sha256": "1" * 64,
    "reference_set_sha256": "2" * 64,
    "evaluator": {"name": "fixture", "revision": "fixture-v1"},
    "scores": {
        "face_appearance": 0.5,
        "body_silhouette": 0.5,
        "hair_appearance": 0.5,
        "skin_material": 0.5,
        "photorealism": 0.5,
        "human_plausibility": 0.5,
        "overall": 0.5,
    },
    "semantics": "visual-fidelity-not-identity-verification",
}


def _result(version: object = 1) -> dict:
    return {
        "format": "bodyrig-fidelity-evaluation",
        "version": version,
        "measurement": copy.deepcopy(MEASUREMENT),
        "body_reference": None,
        "shape_hint": {},
        "diagnostics": {},
        "human_visual_authority_required": True,
        "semantics": "visual-fidelity-not-identity-verification",
    }


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_boolean_result_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    _write(path, _result(True))

    with pytest.raises(FidelityEvaluatorRunnerError, match="format/version mismatch"):
        _read_result(path)


def test_numeric_float_result_version_remains_v1_compatible(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    _write(path, _result(1.0))

    result = _read_result(path)

    assert result["version"] == 1.0
    assert result["human_visual_authority_required"] is True
    assert result["semantics"] == "visual-fidelity-not-identity-verification"
    assert result["measurement"]["version"] == 1
