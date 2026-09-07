from __future__ import annotations

import tomllib
from pathlib import Path

from bodyrig.runtime_lock import load_lock


ROOT = Path(__file__).resolve().parents[1]


def test_build_backend_and_numeric_test_dependency_are_explicit() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    test_dependencies = project["project"]["optional-dependencies"]["test"]

    assert project["build-system"]["requires"] == ["hatchling==1.32.0"]
    assert "numpy>=1.26,<2; python_version < '3.13'" in test_dependencies
    assert "numpy>=2,<3; python_version >= '3.13'" in test_dependencies


def test_platform_locks_share_exact_common_dependency_authority() -> None:
    windows = load_lock(ROOT / "requirements" / "windows-python.lock.txt")
    linux = load_lock(ROOT / "requirements" / "linux-ci-python.lock.txt")

    assert windows["numpy"] == "1.26.4"
    assert linux["numpy"] == "1.26.4"
    assert windows["colorama"] == "0.4.6"
    assert "colorama" not in linux
    assert linux["uvloop"] == "0.22.1"
    assert "uvloop" not in windows

    windows_common = {key: value for key, value in windows.items() if key != "colorama"}
    linux_common = {key: value for key, value in linux.items() if key != "uvloop"}
    assert linux_common == windows_common


def test_ci_installs_and_verifies_platform_specific_exact_locks() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert '-c requirements/linux-ci-python.lock.txt -e ".[test]"' in workflow
    assert 'load_lock("requirements/linux-ci-python.lock.txt")' in workflow
    assert "Linux CI dependency lock mismatch" in workflow
    assert "python -m pip check" in workflow

    assert '-c requirements/windows-python.lock.txt -e ".[test]"' in workflow
    assert "python -m bodyrig.runtime_lock --lock requirements/windows-python.lock.txt" in workflow
