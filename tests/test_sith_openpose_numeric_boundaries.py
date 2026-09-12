from __future__ import annotations

import pytest

from bodyrig.sith_prepare import SithPrepareError, _triples


def test_sith_openpose_triples_reject_boolean_component() -> None:
    with pytest.raises(SithPrepareError, match="non-numeric"):
        _triples([0.0, 0.0, True], label="probe", expected_points=1)


def test_sith_openpose_triples_huge_integer_fails_with_domain_error() -> None:
    with pytest.raises(SithPrepareError, match="non-finite"):
        _triples([10**400, 0.0, 0.9], label="probe", expected_points=1)


def test_sith_openpose_triples_preserve_ordinary_numeric_values() -> None:
    assert _triples([10, 20.5, 1], label="probe", expected_points=1) == [(10.0, 20.5, 1.0)]
