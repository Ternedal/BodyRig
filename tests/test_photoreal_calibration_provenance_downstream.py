from __future__ import annotations

import ast
from pathlib import Path


def _source(name: str) -> str:
    return (Path(__file__).parents[1] / "bodyrig" / name).read_text(encoding="utf-8")


def test_frame_identity_authority_requires_calibration_provenance() -> None:
    source = _source("photoreal_frame_identity_authority.py")
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "CALIBRATION_PROVENANCE_FORMAT" in names or "identity_calibration_provenance_sha256" in source
    assert "negative_inventory_sha256" in source
    assert "identity_calibration_provenance_sha256" in source


def test_frame_index_carries_calibration_provenance() -> None:
    source = _source("photoreal_frame_index.py")
    assert "negative_inventory_sha256" in source
    assert "identity_calibration_provenance_sha256" in source


def test_teacher_input_carries_calibration_provenance() -> None:
    source = _source("photoreal_teacher_input.py")
    assert "negative_inventory_sha256" in source
    assert "identity_calibration_provenance_sha256" in source
