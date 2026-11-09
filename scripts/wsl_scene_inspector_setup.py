"""Set up and self-test the Blender scene inspector inside WSL2 (Ubuntu).

Run by setup-scene-inspector-wsl.ps1 from Windows, or directly inside WSL:

    python3 scripts/wsl_scene_inspector_setup.py --repo /mnt/c/path/to/BodyRig

Standalone and stdlib-only on purpose: it runs on the distro's own python3
(3.10 on Ubuntu 22.04), before Python 3.11 exists. Idempotent: what is already
in place is checked, not reinstalled. Steps:

1. WSL2 + Ubuntu check.
2. apt: bubblewrap, python3.11, python3.11-venv. Uses the deadsnakes PPA only
   when the distro has no final 3.11 (22.04 ships a release candidate, 24.04
   none). Asks for the sudo password once.
3. bubblewrap probe (user namespaces). If Ubuntu's AppArmor restriction blocks
   it, the fix is printed; it is applied only with --allow-userns-sysctl,
   because it relaxes a kernel hardening setting in this distro.
4. A Python 3.11 venv with the hash-locked bpy runtime (--require-hashes --no-deps).
5. Smoke test: a Blender-generated corpus inspected with --isolation bwrap;
   every asset must reach FULLY_ANALYZED under bubblewrap, and the .blend with
   embedded scripts must not run them.

Ends with one line: ``SCENE-INSPECTOR-WSL: PASS`` or ``SCENE-INSPECTOR-WSL: FAIL (<reason>)``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
VENV = HOME / ".local" / "share" / "bodyrig" / "bpy-venv"
STATE = HOME / ".cache" / "bodyrig"
HOST_PYTHON = "python3.11"
USERNS_SYSCTL = "/proc/sys/kernel/apparmor_restrict_unprivileged_userns"
USERNS_CONF = "/etc/sysctl.d/60-bodyrig-bwrap.conf"
BPY_PROBE = (
    "import bpy, os, sys; sys.stdout.write(bpy.app.version_string); sys.stdout.flush(); os._exit(0)"
)


# Runs on the host python with BodyRig importable: builds the same bubblewrap prefix the
# inspector uses and checks, from inside it, that the Windows drives, the WSL home, WSL
# interop, the GPU device and the network are all out of reach.
ISOLATION_PROBE = r"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
from bodyrig import scene_inspector as si
bpy_python, marker = Path(sys.argv[1]), Path(sys.argv[2])
inner = (
    "import json, os, socket\n"
    "checks = {'windows_drives_hidden': not os.path.exists('/mnt/c'),\n"
    "          'wsl_home_hidden': not os.path.exists(%r),\n"
    "          'interop_hidden': not os.path.exists('/init') and not os.environ.get('WSL_INTEROP'),\n"
    "          'gpu_device_hidden': not os.path.exists('/dev/dxg')}\n"
    "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=3); checks['network_blocked'] = False\n"
    "except OSError:\n    checks['network_blocked'] = True\n"
    "print(json.dumps(checks))\n"
) % str(marker)
with tempfile.TemporaryDirectory(prefix="bodyrig-isolation-probe-") as tmp:
    job = Path(tmp)
    read_only = si.BlenderRuntime("module", bpy_python, "probe").read_only_paths()
    argv = si.bwrap_prefix(job, read_only, si.child_env(job)) + [str(bpy_python), "-I", "-c", inner]
    print(subprocess.run(argv, check=True, capture_output=True, text=True, timeout=120).stdout.strip())
"""


class SetupFailed(Exception):
    pass


def say(status: str, message: str) -> None:
    print(f"[{status:<7}] {message}", flush=True)


def run(argv: list, *, check: bool = True, capture: bool = False, env: dict = None, timeout: float = 1800):
    result = subprocess.run(argv, check=False, timeout=timeout, env=env,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None, text=True)
    if check and result.returncode != 0:
        tail = (result.stdout or "")[-1500:] if capture else ""
        raise SetupFailed(f"{' '.join(str(a) for a in argv[:4])} ... exited {result.returncode} {tail}".strip())
    return result


def sudo(argv: list) -> list:
    return argv if os.geteuid() == 0 else ["sudo", *argv]


def needs_deadsnakes(policy_text: str) -> bool:
    """True when apt has no final 3.11.x candidate (none, or 22.04's 3.11.0~rc)."""
    for line in policy_text.splitlines():
        line = line.strip()
        if line.startswith("Candidate:"):
            candidate = line.split(":", 1)[1].strip()
            return candidate in ("", "(none)") or not candidate.startswith("3.11.") or "~rc" in candidate
    return True


def is_final_311(python: str) -> bool:
    if shutil.which(python) is None:
        return False
    probe = run([python, "-c", "import sys, venv, ensurepip; "
                 "assert sys.version_info[:2] == (3, 11) and sys.version_info.releaselevel == 'final'"],
                check=False, capture=True)
    return probe.returncode == 0


def check_platform() -> dict:
    version = Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
    if "microsoft" not in version:
        raise SetupFailed("not running inside WSL")
    if "wsl2" not in version and not Path("/run/WSL").exists():
        raise SetupFailed("WSL1 detected; the inspector needs WSL2 (wsl --set-version <distro> 2)")
    release = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip().strip('"')
    if release.get("ID") != "ubuntu":
        raise SetupFailed(f"Ubuntu required, found {release.get('ID')}; install Ubuntu-22.04 or Ubuntu-24.04 in WSL")
    say("OK", f"WSL2, {release.get('PRETTY_NAME')}, distro {os.environ.get('WSL_DISTRO_NAME', '?')}")
    return release


def ensure_packages() -> None:
    missing = []
    if shutil.which("bwrap") is None:
        missing.append("bubblewrap")
    if not is_final_311(HOST_PYTHON):
        missing += ["python3.11", "python3.11-venv"]
    if not missing:
        say("OK", "bubblewrap and Python 3.11 present")
        return
    say("INSTALL", f"apt packages: {' '.join(missing)} (sudo may ask for your WSL password)")
    if "python3.11" in missing:
        policy = run(["apt-cache", "policy", "python3.11"], check=False, capture=True).stdout or ""
        if needs_deadsnakes(policy):
            if shutil.which("add-apt-repository") is None:
                run(sudo(["apt-get", "update", "-q"]))
                run(sudo(["apt-get", "install", "-y", "-q", "software-properties-common"]))
            say("INSTALL", "deadsnakes PPA for a final Python 3.11")
            run(sudo(["add-apt-repository", "-y", "ppa:deadsnakes/ppa"]))
    run(sudo(["apt-get", "update", "-q"]))
    run(sudo(["apt-get", "install", "-y", "-q", *missing]))
    if not is_final_311(HOST_PYTHON):
        raise SetupFailed("Python 3.11 still missing after apt install")
    say("OK", "packages installed")


def bwrap_works() -> bool:
    return run(["bwrap", "--ro-bind", "/", "/", "--unshare-all", "--die-with-parent", "true"],
               check=False, capture=True).returncode == 0


def ensure_bwrap(allow_sysctl: bool) -> None:
    if bwrap_works():
        say("OK", "bubblewrap can create user, mount, pid and network namespaces")
        return
    restricted = Path(USERNS_SYSCTL).exists() and Path(USERNS_SYSCTL).read_text().strip() == "1"
    if not restricted:
        raise SetupFailed("bubblewrap cannot create namespaces here (and it is not the AppArmor userns restriction)")
    if not allow_sysctl:
        raise SetupFailed(
            "Ubuntu's AppArmor blocks unprivileged user namespaces, which bubblewrap needs. "
            "Re-run with -AllowUsernsSysctl to set kernel.apparmor_restrict_unprivileged_userns=0 "
            f"persistently in {USERNS_CONF} (affects this WSL distro only)")
    say("CHANGE", f"kernel.apparmor_restrict_unprivileged_userns=0 via {USERNS_CONF}")
    run(["sh", "-c", f"echo 'kernel.apparmor_restrict_unprivileged_userns = 0' | "
                     f"{'' if os.geteuid() == 0 else 'sudo '}tee {USERNS_CONF} >/dev/null"])
    run(sudo(["sysctl", "-q", "-p", USERNS_CONF]))
    if not bwrap_works():
        raise SetupFailed("bubblewrap still cannot create namespaces after the sysctl change")
    say("OK", "bubblewrap works")


def ensure_venv(repo: Path) -> Path:
    python = VENV / "bin" / "python"
    if not python.exists():
        say("INSTALL", f"Python 3.11 venv at {VENV}")
        VENV.parent.mkdir(parents=True, exist_ok=True)
        run([HOST_PYTHON, "-m", "venv", str(VENV)])
    lock = repo / "requirements" / "blender-bpy.lock.txt"
    say("INSTALL", "hash-locked bpy runtime (first time downloads about 370 MB)")
    run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-q", "--require-hashes", "--no-deps",
         "-r", str(lock)])
    version = run([str(python), "-I", "-c", BPY_PROBE], capture=True).stdout.strip()
    say("OK", f"bpy {version}")
    return python


def isolation_probe(repo: Path, bpy_python: Path) -> dict:
    marker = HOME / ".bodyrig-isolation-probe"
    marker.write_text("visible outside the sandbox only\n", encoding="utf-8")
    try:
        env = {**os.environ, "PYTHONPATH": str(repo), "PYTHONDONTWRITEBYTECODE": "1"}
        out = run([HOST_PYTHON, "-c", ISOLATION_PROBE, str(bpy_python), str(marker)], capture=True, env=env).stdout
        checks = json.loads(out.strip().splitlines()[-1])
    finally:
        marker.unlink()
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise SetupFailed(f"bubblewrap sandbox leaks: {', '.join(failed)}")
    say("OK", "sandbox hides Windows drives, WSL home, interop, GPU device and network")
    return checks


def smoke(repo: Path, bpy_python: Path) -> dict:
    base = STATE / "setup-smoke"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    corpus = base / "corpus"
    run([str(bpy_python), "-I", str(repo / "tests" / "blender_fixtures" / "make_scene_corpus_bpy.py"), "--",
         str(corpus)], capture=True)
    env = {**os.environ, "PYTHONPATH": str(repo), "PYTHONDONTWRITEBYTECODE": "1"}
    out = base / "out"
    result = run([HOST_PYTHON, "-m", "bodyrig.scene_inspector_cli", "inspect", "--root", str(corpus), "--all",
                  "--out", str(out), "--cache", str(base / "cache"), "--work-root", str(base / "work"),
                  "--bpy-python", str(bpy_python), "--isolation", "bwrap", "--conditioning", "pose,depth,normal"],
                 check=False, capture=True, env=env)
    print(result.stdout, end="")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    states = summary.get("states", {})
    if result.returncode != 0 or set(states) != {"FULLY_ANALYZED"}:
        raise SetupFailed(f"smoke inspection did not fully analyze every asset: {states}")
    for asset in summary["assets"]:
        scene = json.loads((out / asset["out"] / "scene.json").read_text(encoding="utf-8"))
        if scene["isolation"]["mode"] != "bwrap":
            raise SetupFailed(f"{asset['path']} was not isolated with bubblewrap")
    if (corpus / "autorun-marker.txt").exists():
        raise SetupFailed("embedded script in autorun.blend ran")
    total = summary["timings"]["all"]["total"]
    say("OK", f"smoke: {len(summary['assets'])} assets FULLY_ANALYZED under bubblewrap, "
              f"p50 {total['p50']} ms, p95 {total['p95']} ms (this machine)")
    return summary


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, required=True, help="BodyRig checkout as a WSL path")
    parser.add_argument("--allow-userns-sysctl", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        if not (repo / "bodyrig" / "scene_inspector.py").is_file():
            raise SetupFailed(f"not a BodyRig checkout with the scene inspector: {repo}")
        release = check_platform()
        ensure_packages()
        ensure_bwrap(args.allow_userns_sysctl)
        bpy_python = ensure_venv(repo)
        checks = isolation_probe(repo, bpy_python)
        summary = None if args.skip_smoke else smoke(repo, bpy_python)
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "scene-inspector-wsl.json").write_text(json.dumps({
            "distro": os.environ.get("WSL_DISTRO_NAME"), "ubuntu": release.get("VERSION_ID"),
            "host_python": shutil.which(HOST_PYTHON), "bpy_python": str(bpy_python),
            "cache": str(STATE / "scene-cache"), "work_root": str(STATE / "scene-work"),
            "isolation_checks": checks,
            "smoke_timings": summary["timings"]["all"] if summary else None,
        }, indent=2) + "\n", encoding="utf-8")
    except (SetupFailed, OSError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
        print(f"SCENE-INSPECTOR-WSL: FAIL ({exc})", flush=True)
        return 1
    print("SCENE-INSPECTOR-WSL: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
