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
    "evaluator": {"name": "bodyrig-opencv-visual-fidelity", "revision": "4"},
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


def _revision4_result() -> dict:
    return {
        "format": "bodyrig-fidelity-evaluation",
        "version": 1,
        "measurement": copy.deepcopy(MEASUREMENT),
        "body_reference": {"kind": "private-rgba-capture", "sha256": "3" * 64},
        "shape_hint": None,
        "plausibility": {
            "face_detectability": 1.0,
            "bilateral_balance": 0.8,
            "head_shoulder_proportion": 0.75,
            "head_shoulder_ratio": 0.21,
            "skin_liveliness": 0.7,
            "facial_definition": 0.65,
            "score": 0.73,
            "semantics": "broad-render-plausibility-and-definition-not-age-or-identity-classification",
        },
        "facial_definition": {
            "score": 0.65,
            "candidate": {
                "detail": 4.2,
                "local_contrast": 0.8,
                "eye_edge_density": 0.15,
                "midface_edge_density": 0.18,
            },
            "reference_face_count": 1,
            "photorealism_raw": 0.72,
            "photorealism_definition_cap": 0.81,
            "semantics": "reference-relative-local-feature-definition-not-biometric-identification",
        },
        "diagnostics": {},
        "human_visual_authority_required": True,
        "semantics": "visual-fidelity-not-identity-verification",
    }


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_revision4_bridge_result_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    _write(path, _revision4_result())
    result = _read_result(path)
    assert result["measurement"]["evaluator"]["revision"] == "4"
    assert result["plausibility"]["score"] == pytest.approx(0.73)
    assert result["facial_definition"]["reference_face_count"] == 1


def test_revision4_plausibility_shape_is_fail_closed(tmp_path: Path) -> None:
    value = _revision4_result()
    value["plausibility"]["unexpected"] = 1
    path = tmp_path / "result.json"
    _write(path, value)
    with pytest.raises(FidelityEvaluatorRunnerError, match="plausibility fields"):
        _read_result(path)


def test_revision4_facial_definition_rejects_boolean_reference_count(tmp_path: Path) -> None:
    value = _revision4_result()
    value["facial_definition"]["reference_face_count"] = True
    path = tmp_path / "result.json"
    _write(path, value)
    with pytest.raises(FidelityEvaluatorRunnerError, match="reference_face_count"):
        _read_result(path)
