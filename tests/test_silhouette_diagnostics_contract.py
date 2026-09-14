from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.silhouette_diagnostics_cli import (
    SEMANTICS,
    SilhouetteDiagnosticRunnerError,
    _read_result,
)


ROOT = Path(__file__).resolve().parents[1]


def _side() -> dict[str, object]:
    return {
        "mask_file": "candidate-mask.png",
        "profile_overlay_file": "candidate-profile-overlay.png",
        "mask": {
            "bbox_x": 10,
            "bbox_y": 20,
            "bbox_width": 300,
            "bbox_height": 800,
            "bbox_aspect_width_over_height": 0.375,
            "foreground_fraction": 0.22,
            "bbox_fill_fraction": 0.74,
        },
        "width_profile": [0.1, 0.12, 0.3, 0.31, 0.28, 0.29, 0.25, 0.18, 0.12],
        "head_shoulder_ratio": 0.36,
        "head_shoulder_score": 1.0,
    }


def _result() -> dict[str, object]:
    candidate = _side()
    reference = _side()
    reference["mask_file"] = "reference-mask.png"
    reference["profile_overlay_file"] = "reference-profile-overlay.png"
    return {
        "format": "bodyrig-silhouette-diagnostic",
        "version": 1,
        "evaluator_revision": "5",
        "candidate_sha256": "1" * 64,
        "body_reference_sha256": "2" * 64,
        "profile_similarity": 0.91,
        "candidate": candidate,
        "reference": reference,
        "semantics": SEMANTICS,
    }


def test_diagnostic_result_contract_is_strict_and_revision_bound(tmp_path: Path) -> None:
    path = tmp_path / "silhouette-diagnostic.json"
    path.write_text(json.dumps(_result()), encoding="utf-8")

    result = _read_result(path)

    assert result["evaluator_revision"] == "5"
    assert result["candidate"]["head_shoulder_ratio"] == pytest.approx(0.36)
    assert len(result["candidate"]["width_profile"]) == 9


def test_diagnostic_result_rejects_unexpected_fields(tmp_path: Path) -> None:
    value = _result()
    value["unexpected"] = True
    path = tmp_path / "silhouette-diagnostic.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(SilhouetteDiagnosticRunnerError, match="fields must match v1"):
        _read_result(path)


def test_diagnostic_result_rejects_nonfinite_profile_samples(tmp_path: Path) -> None:
    value = _result()
    value["candidate"]["width_profile"][3] = float("nan")
    path = tmp_path / "silhouette-diagnostic.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(SilhouetteDiagnosticRunnerError, match="must be finite"):
        _read_result(path)


def test_bridge_reuses_revision5_profile_and_writes_visual_mask_artifacts() -> None:
    source = (ROOT / "bodyrig" / "bridges" / "opencv_silhouette_diagnostics.py").read_text(encoding="utf-8")

    assert "opencv_fidelity_evaluator_v5" in source
    assert "evaluator_v5.width_profile" in source
    assert '"candidate-mask.png"' in source
    assert '"reference-mask.png"' in source
    assert '"candidate-profile-overlay.png"' in source
    assert '"reference-profile-overlay.png"' in source
    assert "private-diagnostic-only-not-fidelity-acceptance" in source


def test_operator_wrapper_uses_parser_safe_rows_collection() -> None:
    source = (ROOT / "run-fidelity-silhouette-diagnostics.ps1").read_text(encoding="utf-8")

    assert "$rows = @()" in source
    assert "$rows += [pscustomobject]@{" in source
    assert "$rows | Format-Table -AutoSize" in source
    assert "} | Format-Table" not in source
