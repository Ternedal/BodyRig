from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.bridges import sith_canonical_smplx_obj as canonical


def _params() -> dict[str, list[float]]:
    value = {field: [0.0] * length for field, length in canonical.FIT_PARAM_LENGTHS.items()}
    value["scale"] = [1.0]
    return value


def test_final_fit_parameter_contract_is_strict(tmp_path: Path):
    path = tmp_path / "000_fit.json"
    path.write_text(json.dumps(_params()), encoding="utf-8")
    assert canonical.load_fit_params(path)["scale"] == [1.0]

    invalid = _params()
    invalid["extra"] = [0.0]
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(canonical.CanonicalSmplxError, match="fields do not match"):
        canonical.load_fit_params(path)

    invalid = _params()
    invalid["scale"] = [0.0]
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(canonical.CanonicalSmplxError, match="scale is outside"):
        canonical.load_fit_params(path)


def test_obj_writer_overwrites_stale_fit_atomically_with_one_based_faces(tmp_path: Path):
    output = tmp_path / "000_smplx.obj"
    output.write_text("stale\n", encoding="utf-8")
    canonical.write_obj(
        output,
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [(0, 1, 2)],
    )
    assert output.read_text(encoding="utf-8") == (
        "v 0 0 0\n"
        "v 1 0 0\n"
        "v 0 1 0\n"
        "f 1 2 3\n"
    )
