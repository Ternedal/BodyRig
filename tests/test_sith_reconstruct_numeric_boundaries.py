from __future__ import annotations

import json

import pytest

from bodyrig.sith_reconstruct import FIT_PARAM_LENGTHS, SithReconstructError, _finite_vector, validate_fit_params


def _fit_params() -> dict[str, list[float | int]]:
    params: dict[str, list[float | int]] = {
        field: [0.0] * length for field, length in FIT_PARAM_LENGTHS.items()
    }
    params["scale"] = [1.0]
    return params


def test_sith_fit_vector_rejects_boolean_component() -> None:
    with pytest.raises(SithReconstructError, match="non-finite number"):
        _finite_vector([True], field="scale", length=1)


def test_sith_fit_vector_huge_integer_fails_with_domain_error() -> None:
    with pytest.raises(SithReconstructError, match="non-finite number"):
        _finite_vector([10**400], field="scale", length=1)


def test_sith_fit_vector_preserves_ordinary_numeric_values() -> None:
    assert _finite_vector([1, -2.5, 0], field="probe", length=3) == [1.0, -2.5, 0.0]


def test_persisted_fit_json_huge_integer_fails_with_domain_error(tmp_path) -> None:
    params = _fit_params()
    params["betas"][0] = 10**400
    path = tmp_path / "fit.json"
    path.write_text(json.dumps(params), encoding="utf-8")

    with pytest.raises(SithReconstructError, match="betas contains a non-finite number"):
        validate_fit_params(path)
