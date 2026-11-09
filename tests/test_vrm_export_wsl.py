"""The two WSL launchers for the VRM export, run with pwsh against a fake ``wsl.exe``.

The fake records its argv, so the exact command that reaches WSL is checked:
bubblewrap is always requested, no shell runs the CLI, and paths are translated.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN_PS1 = ROOT / "run-vrm-export-wsl.ps1"
SETUP_PS1 = ROOT / "setup-vrm-export-wsl.ps1"
PWSH = shutil.which("pwsh")

FAKE_WSL = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_WSL_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["-d", "Ubuntu-22.04"]:
    args = args[2:]
if "wslpath" in args:
    print("/wsl" + args[-1])
    sys.exit(0)
if args[:3] == ["--exec", "printenv", "HOME"]:
    print("/home/a")
    sys.exit(0)
if args[:3] == ["--exec", "sh", "-c"]:
    state = os.environ.get("FAKE_WSL_STATE")
    if not state:
        sys.exit(1)
    print(state)
    sys.exit(0)
sys.exit(int(os.environ.get("FAKE_WSL_EXIT", "0")))
'''

STATE = {"host_python": "/usr/bin/python3.11", "bpy_python": "/home/a/.local/share/bodyrig/bpy-venv/bin/python",
         "cache": "/home/a/.cache/bodyrig/scene-cache", "work_root": "/home/a/.cache/bodyrig/scene-work"}

needs_pwsh = pytest.mark.skipif(PWSH is None or os.name == "nt", reason="needs pwsh and a POSIX fake wsl")


def _pwsh(tmp_path: Path, script: Path, args: list[str], *, state: dict | None = STATE, exit_code: int = 0):
    fake = tmp_path / "fake-wsl"
    fake.write_text(FAKE_WSL.replace("/usr/bin/env python3", sys.executable, 1), encoding="utf-8")
    fake.chmod(0o755)
    log = tmp_path / "wsl-log.jsonl"
    env = {**os.environ, "FAKE_WSL_LOG": str(log), "FAKE_WSL_EXIT": str(exit_code),
           "FAKE_WSL_STATE": json.dumps(state) if state else ""}
    result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(script), *args, "-WslExe", str(fake)],
                            capture_output=True, text=True, env=env, timeout=120)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return result, calls


def _cli_call(calls: list[list[str]]) -> list[str]:
    return next(call for call in calls if "bodyrig.vrm_export_cli" in call)


@needs_pwsh
def test_export_uses_bubblewrap_cache_and_no_shell(tmp_path: Path) -> None:
    pack = tmp_path / "Pack One.zip"
    pack.write_bytes(b"zip")
    out = tmp_path / "vrm out"
    result, calls = _pwsh(tmp_path, RUN_PS1, ["-Asset", str(pack), "-Out", str(out), "-Distro", "Ubuntu-22.04"],
                          exit_code=1)
    assert result.returncode == 1, result.stderr
    final = _cli_call(calls)
    assert final[:2] == ["-d", "Ubuntu-22.04"]
    assert final[final.index("--cd") + 1] == "/wsl" + str(ROOT)
    assert final[final.index("--exec") + 1] == "env"
    assert "sh" not in final[final.index("--exec"):]
    command = final.index("export")
    assert final[command + 1] == "/wsl" + str(pack) and final[command + 2] == "--out"
    assert final[final.index("--isolation") + 1] == "bwrap" and "none" not in final
    assert final[final.index("--out") + 1] == "/wsl" + str(out)
    assert final[final.index("--addons") + 1] == "/home/a/.local/share/bodyrig/vrm-addons"
    assert final[final.index("--cache") + 1] == "/home/a/.cache/bodyrig/vrm-cache"
    assert final[final.index("--bpy-python") + 1] == STATE["bpy_python"]
    assert final[final.index("--work-root") + 1] == STATE["work_root"]
    assert out.is_dir()


@needs_pwsh
def test_inbox_runs_watch(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    result, calls = _pwsh(tmp_path, RUN_PS1, ["-Inbox", str(inbox), "-Out", str(tmp_path / "out"), "-MaxTexture", "1024"])
    assert result.returncode == 0, result.stderr
    final = _cli_call(calls)
    assert final[final.index("watch") + 1:final.index("watch") + 3] == ["--inbox", "/wsl" + str(inbox)]
    assert final[final.index("--max-texture") + 1] == "1024"
    assert inbox.is_dir()


@needs_pwsh
@pytest.mark.parametrize("args", [[], ["-Asset", "x.zip", "-Inbox", "in"]])
def test_needs_exactly_one_of_asset_or_inbox(tmp_path: Path, args: list[str]) -> None:
    result, calls = _pwsh(tmp_path, RUN_PS1, [*args, "-Out", str(tmp_path / "out")])
    assert result.returncode != 0
    assert not any("bodyrig.vrm_export_cli" in call for call in calls)


@needs_pwsh
def test_stops_when_wsl_is_not_set_up(tmp_path: Path) -> None:
    (tmp_path / "a.zip").write_bytes(b"z")
    result, calls = _pwsh(tmp_path, RUN_PS1, ["-Asset", str(tmp_path / "a.zip"), "-Out", str(tmp_path / "o")],
                          state=None)
    assert result.returncode != 0
    assert "setup-scene-inspector-wsl.ps1" in result.stdout + result.stderr
    assert not any("bodyrig.vrm_export_cli" in call for call in calls)


@needs_pwsh
def test_setup_runs_the_pinned_installer_without_a_shell(tmp_path: Path) -> None:
    result, calls = _pwsh(tmp_path, SETUP_PS1, [])
    assert result.returncode == 0, result.stderr
    assert "VRM-EXPORT-WSL: PASS" in result.stdout
    final = next(call for call in calls if "scripts/vrm_export_setup.py" in call)
    assert final[final.index("--exec") + 1] == "env" and "sh" not in final[final.index("--exec"):]
    assert final[final.index("--addons") + 1] == "/home/a/.local/share/bodyrig/vrm-addons"
    assert STATE["host_python"] in final


@needs_pwsh
def test_setup_fails_loudly(tmp_path: Path) -> None:
    result, _ = _pwsh(tmp_path, SETUP_PS1, [], exit_code=3)
    assert result.returncode != 0
    assert "PASS" not in result.stdout


@needs_pwsh
def test_weight_reference_is_translated_and_passed(tmp_path: Path) -> None:
    pack = tmp_path / "a.zip"
    pack.write_bytes(b"z")
    twin = tmp_path / "twin.blend"
    twin.write_bytes(b"b")
    result, calls = _pwsh(tmp_path, RUN_PS1, ["-Asset", str(pack), "-Out", str(tmp_path / "o"),
                                              "-WeightReference", str(twin)])
    assert result.returncode == 0, result.stderr
    final = _cli_call(calls)
    assert final[final.index("--weight-reference") + 1] == "/wsl" + str(twin)
    plain, calls2 = _pwsh(tmp_path, RUN_PS1, ["-Asset", str(pack), "-Out", str(tmp_path / "o")])
    assert "--weight-reference" not in _cli_call(calls2[len(calls):] or calls2)
