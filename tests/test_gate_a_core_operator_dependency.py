from pathlib import Path

import pytest

from bodyrig.acceptance_status import AcceptanceStatusError
from bodyrig.acceptance_status_cli import CANONICAL_OPERATOR_FILES, _resolve_operator_root


def _operator_root(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    for name in CANONICAL_OPERATOR_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test operator dependency\n", encoding="utf-8")
    return tmp_path


def test_gate_a_transactional_core_is_a_canonical_operator_dependency(tmp_path: Path) -> None:
    assert "accept-physical-clone-core.ps1" in CANONICAL_OPERATOR_FILES

    root = _operator_root(tmp_path)
    (root / "accept-physical-clone-core.ps1").unlink()

    with pytest.raises(AcceptanceStatusError, match="missing canonical operator dependencies") as excinfo:
        _resolve_operator_root(root)

    assert "accept-physical-clone-core.ps1" in str(excinfo.value)
