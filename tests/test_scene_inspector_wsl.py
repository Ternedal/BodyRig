"""WSL2 path for the scene inspector: setup decisions and the two Windows launchers.

The launchers are executed with pwsh against a fake ``wsl.exe`` that records its
argv, so the exact command that reaches WSL is checked, not just the script text.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "wsl_scene_inspector_setup.py"
RUN_PS1 = ROOT / "run-scene-inspector-wsl.ps1"
SETUP_PS1 = ROOT / "setup-scene-inspector-wsl.ps1"
PWSH = shutil.which("pwsh")


def _setup_module():
    spec = importlib.util.spec_from_file_location("wsl_scene_inspector_setup", SETUP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("policy, expected", [
    ("python3.11:\n  Installed: (none)\n  Candidate: (none)\n", True),
    ("python3.11:\n  Installed: (none)\n  Candidate: 3.11.0~rc1-1~22.04\n", True),
    ("python3.11:\n  Installed: (none)\n  Candidate: 3.11.14-1+jammy1\n", False),
    ("", True),
])
def test_deadsnakes_only_when_no_final_311(policy: str, expected: bool) -> None:
    assert _setup_module().needs_deadsnakes(policy) is expected


def test_setup_refuses_a_folder_that_is_not_the_checkout(tmp_path: Path, capsys) -> None:
    assert _setup_module().main(["--repo", str(tmp_path)]) == 1
    assert "SCENE-INSPECTOR-WSL: FAIL (not a BodyRig checkout" in capsys.readouterr().out


def test_setup_does_not_relax_userns_without_the_flag(monkeypatch, tmp_path: Path) -> None:
    module = _setup_module()
    sysctl = tmp_path / "userns"
    sysctl.write_text("1\n")
    monkeypatch.setattr(module, "USERNS_SYSCTL", str(sysctl))
    monkeypatch.setattr(module, "bwrap_works", lambda: False)
    calls = []
    monkeypatch.setattr(module, "run", lambda argv, **kw: calls.append(argv))
    with pytest.raises(module.SetupFailed, match="AllowUsernsSysctl"):
        module.ensure_bwrap(False)
    assert calls == []


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


@needs_pwsh
def test_run_launcher_always_uses_bubblewrap_and_no_shell(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    out = tmp_path / "scene out"
    result, calls = _pwsh(tmp_path, RUN_PS1, ["-Root", str(root), "-Out", str(out), "-Asset", "props\\chair.fbx",
                                             "-Distro", "Ubuntu-22.04"], exit_code=1)
    assert result.returncode == 1, result.stderr
    final = calls[-1]
    assert final[:2] == ["-d", "Ubuntu-22.04"]
    assert final[final.index("--cd") + 1] == "/wsl" + str(ROOT)
    assert final[final.index("--exec") + 1] == "env"
    assert final[final.index("--isolation") + 1] == "bwrap"
    assert final[final.index("--root") + 1] == "/wsl" + str(root)
    assert final[final.index("--out") + 1] == "/wsl" + str(out)
    assert final[final.index("--asset") + 1] == "props/chair.fbx"
    assert final[final.index("--bpy-python") + 1] == STATE["bpy_python"]
    assert final[final.index("--cache") + 1] == STATE["cache"]
    assert "none" not in final and "sh" not in final[final.index("--exec"):]
    assert final[final.index("--budget") + 1] == "60m"  # a run is always time-bounded


@needs_pwsh
def test_run_launcher_passes_the_budget_and_its_exit_code(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    result, calls = _pwsh(tmp_path, RUN_PS1, ["-Root", str(root), "-Out", str(tmp_path / "o"), "-All",
                                             "-Budget", "15m"], exit_code=3)
    assert result.returncode == 3, result.stderr
    assert calls[-1][calls[-1].index("--budget") + 1] == "15m"


@needs_pwsh
def test_run_launcher_stops_when_wsl_is_not_set_up(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    result, calls = _pwsh(tmp_path, RUN_PS1, ["-Root", str(root), "-Out", str(tmp_path / "o"), "-All"], state=None)
    assert result.returncode != 0
    assert "setup-scene-inspector-wsl.ps1" in result.stdout + result.stderr
    assert not any("bodyrig.scene_inspector_cli" in call for call in calls)


@needs_pwsh
def test_setup_launcher_passes_the_userns_flag_only_when_asked(tmp_path: Path) -> None:
    _, calls = _pwsh(tmp_path, SETUP_PS1, [])
    assert calls[-1][calls[-1].index("--exec") + 1:][:2] == ["python3", "scripts/wsl_scene_inspector_setup.py"]
    assert "--allow-userns-sysctl" not in calls[-1]
    _, calls = _pwsh(tmp_path, SETUP_PS1, ["-AllowUsernsSysctl"])
    assert "--allow-userns-sysctl" in calls[-1]


def test_isolation_probe_fails_the_setup_on_any_leak(monkeypatch, tmp_path: Path) -> None:
    module = _setup_module()
    monkeypatch.setattr(module, "HOME", tmp_path)

    class Done:
        stdout = json.dumps({"windows_drives_hidden": True, "wsl_home_hidden": True, "interop_hidden": True,
                             "gpu_device_hidden": True, "network_blocked": False})

    monkeypatch.setattr(module, "run", lambda argv, **kw: Done())
    with pytest.raises(module.SetupFailed, match="network_blocked"):
        module.isolation_probe(ROOT, Path("/venv/bin/python"))
    assert not (tmp_path / ".bodyrig-isolation-probe").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux") or shutil.which("bwrap") is None
                    or not os.environ.get("BODYRIG_BPY_PYTHON"), reason="needs bubblewrap and the bpy runtime")
def test_isolation_probe_passes_with_the_real_sandbox(tmp_path: Path, monkeypatch) -> None:
    module = _setup_module()
    monkeypatch.setattr(module, "HOME", tmp_path)
    monkeypatch.setattr(module, "HOST_PYTHON", sys.executable)
    checks = module.isolation_probe(ROOT, Path(os.environ["BODYRIG_BPY_PYTHON"]))
    assert all(checks.values()) and set(checks) >= {"wsl_home_hidden", "network_blocked"}


def test_speed_line_takes_the_worst_verdict_per_target() -> None:
    module = _setup_module()
    cold = {"metadata": {"verdict": "PASS"}, "analysis": {"verdict": "PASS"}, "first_usable": {"verdict": "PASS"},
            "cached": {"verdict": "NOT_MEASURED"}}
    warm = {"metadata": {"verdict": "NOT_MEASURED"}, "analysis": {"verdict": "NOT_MEASURED"},
            "first_usable": {"verdict": "PASS"}, "cached": {"verdict": "PASS"}}
    assert module.speed_line([cold, warm]).startswith("SCENE-INSPECTOR-WSL SPEED: PASS (metadata PASS, analysis PASS")
    assert "SPEED: PARTIAL" in module.speed_line([cold]) and "cached NOT MEASURED" in module.speed_line([cold])
    slow = dict(cold, analysis={"verdict": "FAIL"})
    assert "SPEED: FAIL" in module.speed_line([slow, warm]) and "analysis FAIL" in module.speed_line([slow, warm])
    assert "SPEED: PARTIAL" in module.speed_line([None])


@pytest.mark.skipif(not sys.platform.startswith("linux") or shutil.which("bwrap") is None
                    or not os.environ.get("BODYRIG_BPY_PYTHON"), reason="needs bubblewrap and the bpy runtime")
def test_smoke_runs_cold_then_cached_and_reports_speed(tmp_path: Path, monkeypatch) -> None:
    module = _setup_module()
    monkeypatch.setattr(module, "STATE", tmp_path / "state")
    monkeypatch.setattr(module, "HOST_PYTHON", sys.executable)
    summary = module.smoke(ROOT, Path(os.environ["BODYRIG_BPY_PYTHON"]))
    slo = summary["smoke_slo"]
    assert slo["cold"]["analysis"]["verdict"] in ("PASS", "FAIL") and slo["cached"]["cached"]["n"] >= 5
    assert module.speed_line([slo["cold"], slo["cached"]]).startswith("SCENE-INSPECTOR-WSL SPEED: ")
