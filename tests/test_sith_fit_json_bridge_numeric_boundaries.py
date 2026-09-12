from __future__ import annotations

import json

import pytest

from bodyrig.bridges import sith_canonical_smplx_obj as canonical
from bodyrig.bridges import sith_smplx_vrm_fitter as fitter


def _params(lengths: dict[str, int]) -> dict[str, list[float | int]]:
    value: dict[str, list[float | int]] = {
        field: [0.0] * length for field, length in lengths.items()
    }
    value["scale"] = [1.0]
    return value


@pytest.mark.parametrize(
    ("validator", "error_type"),
    [
        (canonical._finite_vector, canonical.CanonicalSmplxError),
        (fitter._finite_vector, fitter.FitterError),
    ],
)
def test_fit_vector_rejects_boolean_component(validator, error_type) -> None:
    with pytest.raises(error_type, match="non-finite value"):
        validator([True], field="scale", length=1)


@pytest.mark.parametrize(
    ("validator", "error_type"),
    [
        (canonical._finite_vector, canonical.CanonicalSmplxError),
        (fitter._finite_vector, fitter.FitterError),
    ],
)
def test_fit_vector_huge_integer_fails_with_domain_error(validator, error_type) -> None:
    with pytest.raises(error_type, match="non-finite value"):
        validator([10**400], field="scale", length=1)


@pytest.mark.parametrize("validator", [canonical._finite_vector, fitter._finite_vector])
def test_fit_vector_preserves_ordinary_numeric_values(validator) -> None:
    assert validator([1, -2.5, 0], field="probe", length=3) == [1.0, -2.5, 0.0]


def test_canonical_persisted_fit_json_huge_integer_fails_closed(tmp_path) -> None:
    params = _params(canonical.FIT_PARAM_LENGTHS)
    params["betas"][0] = 10**400
    path = tmp_path / "fit.json"
    path.write_text(json.dumps(params), encoding="utf-8")

    with pytest.raises(canonical.CanonicalSmplxError, match="betas contains a non-finite value"):
        canonical.load_fit_params(path)


def test_fitter_persisted_fit_json_huge_integer_fails_closed(tmp_path) -> None:
    params = _params(fitter.FIT_PARAM_LENGTHS)
    params["betas"][0] = 10**400
    path = tmp_path / "fit.json"
    path.write_text(json.dumps(params), encoding="utf-8")

    with pytest.raises(fitter.FitterError, match="betas contains a non-finite value"):
        fitter._fit_params(path)
