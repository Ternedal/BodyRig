from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig.install_authority import (
    EXPECTED_ENTRY_POINT,
    InstallAuthorityError,
    validate_editable_install,
)


PROJECT_SCRIPTS = {
    "bodyrig": EXPECTED_ENTRY_POINT,
    "bodyrig-recover": "bodyrig.recover_cli:main",
}


class FakeDistribution:
    def __init__(
        self,
        *,
        source: Path,
        editable: bool = True,
        version: str = "0.1.0",
        scripts: dict[str, str] | None = None,
    ):
        self.version = version
        self._direct = {
            "url": source.resolve().as_uri(),
            "dir_info": {"editable": editable},
        }
        selected = PROJECT_SCRIPTS if scripts is None else scripts
        self.entry_points = [
            SimpleNamespace(group="console_scripts", name=name, value=value)
            for name, value in selected.items()
        ]

    def read_text(self, name: str) -> str | None:
        if name != "direct_url.json":
            return None
        return json.dumps(self._direct)


def _checkout(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "BodyRig"
    (root / "bodyrig").mkdir(parents=True)
    (root / "bodyrig" / "__init__.py").write_text("\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "bodyrig"',
                'version = "0.1.0"',
                "",
                "[project.scripts]",
                f'bodyrig = "{EXPECTED_ENTRY_POINT}"',
                'bodyrig-recover = "bodyrig.recover_cli:main"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    scripts = root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    python = scripts / "python.exe"
    launcher = scripts / "bodyrig.exe"
    python.write_bytes(b"python")
    launcher.write_bytes(b"launcher")
    return root, python, launcher


def test_exact_editable_checkout_launcher_version_and_project_scripts_pass(tmp_path: Path) -> None:
    root, python, launcher = _checkout(tmp_path)
    dist = FakeDistribution(source=root)

    result = validate_editable_install(
        root,
        distribution_reader=lambda _name: dist,
        python_executable=python,
        launcher_path=launcher,
    )

    assert result["ok"] is True
    assert result["version"] == 2
    assert result["distribution"]["editable"] is True
    assert result["distribution"]["version"] == "0.1.0"
    assert Path(result["distribution"]["source"]) == root.resolve()
    assert result["project_scripts"] == PROJECT_SCRIPTS


def test_non_editable_distribution_is_rejected(tmp_path: Path) -> None:
    root, python, launcher = _checkout(tmp_path)
    dist = FakeDistribution(source=root, editable=False)

    with pytest.raises(InstallAuthorityError, match="not an editable install"):
        validate_editable_install(
            root,
            distribution_reader=lambda _name: dist,
            python_executable=python,
            launcher_path=launcher,
        )


def test_editable_distribution_from_other_checkout_is_rejected(tmp_path: Path) -> None:
    root, python, launcher = _checkout(tmp_path)
    other = tmp_path / "OtherBodyRig"
    other.mkdir()
    dist = FakeDistribution(source=other)

    with pytest.raises(InstallAuthorityError, match="different checkout"):
        validate_editable_install(
            root,
            distribution_reader=lambda _name: dist,
            python_executable=python,
            launcher_path=launcher,
        )


def test_stale_console_entry_point_is_rejected(tmp_path: Path) -> None:
    root, python, launcher = _checkout(tmp_path)
    stale = dict(PROJECT_SCRIPTS)
    stale["bodyrig"] = "bodyrig.old:main"
    dist = FakeDistribution(source=root, scripts=stale)

    with pytest.raises(InstallAuthorityError, match="console-script metadata differs"):
        validate_editable_install(
            root,
            distribution_reader=lambda _name: dist,
            python_executable=python,
            launcher_path=launcher,
        )


def test_missing_project_console_script_is_rejected(tmp_path: Path) -> None:
    root, python, launcher = _checkout(tmp_path)
    dist = FakeDistribution(source=root, scripts={"bodyrig": EXPECTED_ENTRY_POINT})

    with pytest.raises(InstallAuthorityError, match="missing=bodyrig-recover"):
        validate_editable_install(
            root,
            distribution_reader=lambda _name: dist,
            python_executable=python,
            launcher_path=launcher,
        )


def test_stale_distribution_version_is_rejected(tmp_path: Path) -> None:
    root, python, launcher = _checkout(tmp_path)
    dist = FakeDistribution(source=root, version="0.0.9")

    with pytest.raises(InstallAuthorityError, match="distribution metadata is stale"):
        validate_editable_install(
            root,
            distribution_reader=lambda _name: dist,
            python_executable=python,
            launcher_path=launcher,
        )


def test_missing_launcher_is_rejected(tmp_path: Path) -> None:
    root, python, launcher = _checkout(tmp_path)
    launcher.unlink()
    dist = FakeDistribution(source=root)

    with pytest.raises(InstallAuthorityError, match="console launcher is missing"):
        validate_editable_install(
            root,
            distribution_reader=lambda _name: dist,
            python_executable=python,
            launcher_path=launcher,
        )


def test_python_must_be_repo_local_windows_interpreter(tmp_path: Path) -> None:
    root, _python, launcher = _checkout(tmp_path)
    wrong_python = tmp_path / "python.exe"
    wrong_python.write_bytes(b"python")
    dist = FakeDistribution(source=root)

    with pytest.raises(InstallAuthorityError, match="repo-local Windows Python"):
        validate_editable_install(
            root,
            distribution_reader=lambda _name: dist,
            python_executable=wrong_python,
            launcher_path=launcher,
        )
