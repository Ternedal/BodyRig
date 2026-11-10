"""Install the two Blender add-ons ``bodyrig.vrm_export`` needs, at pinned commits.

    python scripts/vrm_export_setup.py --addons C:\\BodyRig\\vrm-addons

- VRM Add-on for Blender (saturday06), ``src/io_scene_vrm``;
- XNALara-io-Tools (Valerie-Bosco, the maintained XPS Tools fork), with its
  pinned submodules, plus one local patch (below).

Writes ``bodyrig-addons.json`` (pins + patch hash) into the add-on folder; that
stamp is part of every VRM cache key, so changing a pin invalidates old results.

The patch: the fork parents every bone to ``edit_bones[parentId]``. XPS marks
the root with parent ``-1``, which Python reads as the LAST bone, so every real
XPS skeleton comes in with its root hanging off a leaf. Upstream report pending.
Needs ``git`` on PATH and network access once.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bodyrig import hashing  # noqa: E402
from bodyrig.vrm_export import ADDON_PINS, ADDON_STAMP  # noqa: E402

XPS_PATCH_FILE = "import_xnalara_model.py"
XPS_PATCH_OLD = "            editBone.parent = armature.edit_bones[xps_bone.parentId]"
XPS_PATCH_NEW = ("            if xps_bone.parentId is not None and xps_bone.parentId >= 0:  # bodyrig: -1 is the root\n"
                 "                editBone.parent = armature.edit_bones[xps_bone.parentId]")


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)


def fetch(pin: dict, into: Path) -> None:
    into.mkdir(parents=True)
    _git("init", "-q", cwd=into)
    _git("remote", "add", "origin", pin["repo"], cwd=into)
    _git("fetch", "-q", "--depth", "1", "origin", pin["commit"], cwd=into)
    _git("checkout", "-q", "FETCH_HEAD", cwd=into)
    if pin.get("submodules"):
        _git("submodule", "update", "-q", "--init", "--recursive", "--depth", "1", cwd=into)


def patch_xps(addon: Path) -> str:
    target = addon / XPS_PATCH_FILE
    text = target.read_text(encoding="utf-8")
    if XPS_PATCH_NEW not in text:
        if text.count(XPS_PATCH_OLD) != 1:
            raise SystemExit(f"XPS patch does not apply cleanly to {target}; the pinned commit changed?")
        target.write_text(text.replace(XPS_PATCH_OLD, XPS_PATCH_NEW), encoding="utf-8")
    return hashing.sha256_bytes(XPS_PATCH_NEW.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--addons", type=Path, required=True, help="target folder (replaced add-on by add-on)")
    args = parser.parse_args(argv)
    args.addons.mkdir(parents=True, exist_ok=True)
    stamp: dict = {"pins": {}, "patches": {}}
    with tempfile.TemporaryDirectory(prefix="bodyrig-addons-") as tmp:
        for module, pin in ADDON_PINS.items():
            checkout = Path(tmp) / module
            print(f"fetching {module} @ {pin['commit'][:12]}", flush=True)
            fetch(pin, checkout)
            source = checkout / pin["subdir"]
            target = args.addons / module
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            stamp["pins"][module] = {"repo": pin["repo"], "commit": pin["commit"]}
            if module == "XNALara-io-Tools":
                stamp["patches"][module] = patch_xps(target)
    (args.addons / ADDON_STAMP).write_text(json.dumps(stamp, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"add-ons ready in {args.addons}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
