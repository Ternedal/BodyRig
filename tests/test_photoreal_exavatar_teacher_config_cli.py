from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_teacher_config_cli as cli


def _stale_config() -> dict[str, object]:
    return {
        "format": cli.FORMAT,
        "version": cli.VERSION,
        "adapter": cli.ADAPTER,
        "revision": "sha256:" + ("1" * 64),
        "upstream_repository": cli.UPSTREAM_REPOSITORY,
        "upstream_commit": cli.UPSTREAM_COMMIT,
        "command": [
            "C:/Python/python.exe",
            "C:/BodyRig/bodyrig/photoreal_exavatar_teacher_wsl_bridge.py",
            "--distribution",
            "Ubuntu-22.04",
            "--wsl-exe",
            "wsl.exe",
            "--linux-python",
            "/opt/bodyrig-exavatar/bin/python",
            "--workspace-root",
            "/opt/bodyrig-exavatar/workspaces/bodyrig-42",
            "--runtime-preflight",
            "/opt/bodyrig-exavatar/workspaces/bodyrig-42/runtime-preflight.json",
            "--adapter-script",
            "C:/BodyRig/tools/photoreal_exavatar_teacher_adapter.py",
        ],
        "timeout_seconds": cli.MAX_TIMEOUT_SECONDS,
    }


def _argv(output: Path) -> list[str]:
    return [
        "--windows-python",
        "C:/Python/python.exe",
        "--bridge",
        "C:/BodyRig/bodyrig/photoreal_exavatar_teacher_wsl_bridge.py",
        "--adapter",
        "C:/BodyRig/tools/photoreal_exavatar_teacher_adapter.py",
        "--linux-workspace-root",
        "/opt/bodyrig-exavatar/workspaces/bodyrig-42",
        "--linux-runtime-preflight",
        "/opt/bodyrig-exavatar/workspaces/bodyrig-42/runtime-preflight.json",
        "--out",
        str(output),
        "--reuse-existing",
    ]


def test_only_canonical_pinned_teacher_config_is_replaceable(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_stale_config()), encoding="utf-8")

    assert cli._is_replaceable_stale_config(path) is True

    corrupted = _stale_config()
    corrupted["upstream_commit"] = "f" * 40
    path.write_text(json.dumps(corrupted), encoding="utf-8")
    assert cli._is_replaceable_stale_config(path) is False


def test_reuse_existing_atomically_rebuilds_stale_teacher_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "exavatar-teacher-config.json"
    output.write_text(json.dumps(_stale_config()), encoding="utf-8")
    built_paths: list[Path] = []

    def stale_validate(**_kwargs):
        raise cli.PhotorealExAvatarTeacherConfigError("stale config")

    def fake_build(*, output_path, **_kwargs):
        path = Path(output_path)
        built_paths.append(path)
        value = _stale_config()
        value["revision"] = "sha256:" + ("2" * 64)
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")
        return value

    monkeypatch.setattr(cli, "validate_exavatar_teacher_config_file", stale_validate)
    monkeypatch.setattr(cli, "build_exavatar_teacher_config_file", fake_build)

    code = cli.main(_argv(output))

    assert code == 0
    assert len(built_paths) == 1
    assert built_paths[0].parent == output.parent
    assert built_paths[0].name.startswith(f".{output.name}.rebuild-")
    rebuilt = json.loads(output.read_text(encoding="utf-8"))
    assert rebuilt["revision"] == "sha256:" + ("2" * 64)
    assert list(tmp_path.glob(f".{output.name}.rebuild-*")) == []


def test_failed_teacher_config_rebuild_preserves_existing_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "exavatar-teacher-config.json"
    original = json.dumps(_stale_config(), sort_keys=True)
    output.write_text(original, encoding="utf-8")

    def stale_validate(**_kwargs):
        raise cli.PhotorealExAvatarTeacherConfigError("stale config")

    def fail_build(*, output_path, **_kwargs):
        Path(output_path).write_text("partial\n", encoding="utf-8")
        raise cli.PhotorealExAvatarTeacherConfigError("synthetic rebuild failure")

    monkeypatch.setattr(cli, "validate_exavatar_teacher_config_file", stale_validate)
    monkeypatch.setattr(cli, "build_exavatar_teacher_config_file", fail_build)

    code = cli.main(_argv(output))

    assert code == 1
    assert output.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(f".{output.name}.rebuild-*")) == []
