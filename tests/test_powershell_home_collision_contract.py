from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AFFECTED_OPERATORS = (
    "refit-subject-anatomy.ps1",
    "audit-retained-anatomy.ps1",
    "audit-anatomy-candidate.ps1",
    "extract-retained-hair.ps1",
    "extract-eye-components.ps1",
    "extract-eye-appearance.ps1",
    "build-source-hair-review-runtime.ps1",
    "build-source-hair-eye-review-runtime.ps1",
    "build-source-eye-only-review-runtime.ps1",
)
HOME_ASSIGNMENT = re.compile(r"(?im)^\s*\$home\s*=")


def test_high_fidelity_wsl_operators_do_not_assign_automatic_home() -> None:
    for relative in AFFECTED_OPERATORS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert HOME_ASSIGNMENT.search(source) is None, relative
        assert "$wslHomeProbe" in source, relative


def test_high_fidelity_wsl_default_sith_root_is_preserved() -> None:
    for relative in AFFECTED_OPERATORS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        lowered = source.lower()
        assert "pathlib.path.home().as_posix()" in lowered, relative
        assert "/.local/share/bodyrig/sith" in lowered, relative
