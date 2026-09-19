from __future__ import annotations

from bodyrig import photoreal_exavatar_workspace_wsl as workspace_wsl


def test_workspace_v1_accepts_numeric_one() -> None:
    assert workspace_wsl._is_v1(1)
    assert workspace_wsl._is_v1(1.0)


def test_workspace_v1_rejects_boolean_and_non_v1_values() -> None:
    assert not workspace_wsl._is_v1(True)
    assert not workspace_wsl._is_v1(False)
    assert not workspace_wsl._is_v1("1")
    assert not workspace_wsl._is_v1(0)
    assert not workspace_wsl._is_v1(2)


def test_workspace_frame_count_requires_exact_integer() -> None:
    assert workspace_wsl._is_exact_count(1, 1)
    assert not workspace_wsl._is_exact_count(True, 1)
    assert not workspace_wsl._is_exact_count(1.0, 1)
    assert not workspace_wsl._is_exact_count("1", 1)
