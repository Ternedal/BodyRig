from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname


DIST_NAME = "bodyrig"
EXPECTED_ENTRY_POINT = "bodyrig.guided_app:run"


class InstallAuthorityError(RuntimeError):
    pass


def _same_path(left: Path, right: Path) -> bool:
    try:
        left_text = os.path.normcase(str(left.expanduser().resolve()))
        right_text = os.path.normcase(str(right.expanduser().resolve()))
    except (OSError, RuntimeError, ValueError) as exc:
        raise InstallAuthorityError(f"could not resolve install authority path: {exc}") from exc
    return left_text == right_text


def _file_url_path(value: str) -> Path:
    parsed = urlparse(value)
    if parsed.scheme.lower() != "file":
        raise InstallAuthorityError("BodyRig editable distribution direct_url is not a local file URL")
    path_text = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        path_text = f"//{parsed.netloc}{path_text}"
    return Path(path_text).expanduser().resolve()


def _project_metadata(root: Path) -> tuple[str, dict[str, str]]:
    path = root / "pyproject.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise InstallAuthorityError(f"BodyRig pyproject metadata is unreadable: {path}") from exc
    project = raw.get("project")
    if not isinstance(project, dict) or str(project.get("name") or "").strip().lower() != DIST_NAME:
        raise InstallAuthorityError("pyproject.toml does not declare the BodyRig distribution")
    version = str(project.get("version") or "").strip()
    if not version:
        raise InstallAuthorityError("pyproject.toml has no static BodyRig version")
    scripts_raw = project.get("scripts")
    if not isinstance(scripts_raw, dict) or not scripts_raw:
        raise InstallAuthorityError("pyproject.toml has no BodyRig project scripts")
    scripts: dict[str, str] = {}
    for name, value in scripts_raw.items():
        clean_name = str(name or "").strip()
        clean_value = str(value or "").strip()
        if not clean_name or not clean_value:
            raise InstallAuthorityError("pyproject.toml contains an invalid BodyRig project script")
        scripts[clean_name] = clean_value
    if scripts.get("bodyrig") != EXPECTED_ENTRY_POINT:
        raise InstallAuthorityError(
            f"pyproject.toml bodyrig entry point changed unexpectedly: {scripts.get('bodyrig') or 'missing'}"
        )
    return version, scripts


def _installed_scripts(distribution: Any) -> dict[str, str]:
    scripts: dict[str, str] = {}
    for entry in distribution.entry_points:
        if getattr(entry, "group", None) != "console_scripts":
            continue
        name = str(getattr(entry, "name", "") or "").strip()
        value = str(getattr(entry, "value", "") or "").strip()
        if not name or not value:
            raise InstallAuthorityError("installed BodyRig distribution contains an invalid console-script entry point")
        if name in scripts:
            raise InstallAuthorityError(f"installed BodyRig distribution contains duplicate console script: {name}")
        scripts[name] = value
    return scripts


def validate_editable_install(
    repo_root: str | Path,
    *,
    distribution_reader: Callable[[str], Any] = importlib.metadata.distribution,
    python_executable: str | Path | None = None,
    launcher_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    if not (root / "pyproject.toml").is_file() or not (root / "bodyrig" / "__init__.py").is_file():
        raise InstallAuthorityError(f"repo root is not a BodyRig checkout: {root}")
    project_version, project_scripts = _project_metadata(root)

    executable = Path(python_executable or sys.executable).expanduser().resolve()
    expected_python = (root / ".venv" / "Scripts" / "python.exe").resolve()
    if not _same_path(executable, expected_python):
        raise InstallAuthorityError(
            f"BodyRig install authority requires repo-local Windows Python: expected={expected_python}, actual={executable}"
        )

    launcher = Path(launcher_path or (root / ".venv" / "Scripts" / "bodyrig.exe")).expanduser().resolve()
    if not launcher.is_file():
        raise InstallAuthorityError(f"BodyRig console launcher is missing: {launcher}")

    try:
        distribution = distribution_reader(DIST_NAME)
    except importlib.metadata.PackageNotFoundError as exc:
        raise InstallAuthorityError("BodyRig distribution is not installed in the repo virtualenv") from exc

    installed_version = str(getattr(distribution, "version", "") or "").strip()
    if installed_version != project_version:
        raise InstallAuthorityError(
            f"installed BodyRig distribution metadata is stale: expected version={project_version}, actual={installed_version or 'missing'}"
        )

    direct_text = distribution.read_text("direct_url.json")
    if not direct_text:
        raise InstallAuthorityError("installed BodyRig distribution has no PEP 610 direct_url.json")
    try:
        direct = json.loads(direct_text)
    except json.JSONDecodeError as exc:
        raise InstallAuthorityError("installed BodyRig direct_url.json is invalid JSON") from exc
    if not isinstance(direct, dict):
        raise InstallAuthorityError("installed BodyRig direct_url.json must be an object")
    dir_info = direct.get("dir_info")
    if not isinstance(dir_info, dict) or dir_info.get("editable") is not True:
        raise InstallAuthorityError("installed BodyRig distribution is not an editable install")
    source = _file_url_path(str(direct.get("url") or ""))
    if not _same_path(source, root):
        raise InstallAuthorityError(
            f"installed BodyRig editable source is bound to a different checkout: expected={root}, actual={source}"
        )

    installed_scripts = _installed_scripts(distribution)
    if installed_scripts != project_scripts:
        missing = sorted(set(project_scripts) - set(installed_scripts))
        extra = sorted(set(installed_scripts) - set(project_scripts))
        changed = sorted(
            name
            for name in set(project_scripts) & set(installed_scripts)
            if project_scripts[name] != installed_scripts[name]
        )
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        if changed:
            details.append("changed=" + ",".join(changed))
        raise InstallAuthorityError(
            "installed BodyRig console-script metadata differs from active pyproject.toml"
            + (": " + "; ".join(details) if details else "")
        )

    return {
        "format": "bodyrig-editable-install-authority",
        "version": 2,
        "ok": True,
        "distribution": {
            "name": DIST_NAME,
            "version": installed_version,
            "editable": True,
            "source": str(source),
        },
        "python_executable": str(executable),
        "launcher": str(launcher),
        "project_scripts": installed_scripts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that BodyRig is editable-installed from this exact checkout in the repo-local Windows virtualenv."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = validate_editable_install(args.repo_root)
    except InstallAuthorityError as exc:
        print(f"BodyRig editable install authority: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
