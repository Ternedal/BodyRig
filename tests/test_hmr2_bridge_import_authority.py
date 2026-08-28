import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import bodyrig.bridges.hmr2_4dhumans_bridge as bridge


def test_hmr2_bridge_phalp_lookup_ignores_bodyrig_local_helper(monkeypatch, tmp_path):
    bridge_dir = Path(bridge.__file__).resolve().parent
    package_parent = Path(bridge.__file__).resolve().parents[2]
    fake_site = tmp_path / "site-packages"
    fake_package = fake_site / "phalp"
    fake_package.mkdir(parents=True)
    (fake_package / "__init__.py").write_text("# fake external PHALP\n", encoding="utf-8")

    monkeypatch.delitem(bridge.sys.modules, "phalp", raising=False)
    monkeypatch.setattr(
        bridge.sys,
        "path",
        [str(package_parent), str(bridge_dir), str(fake_site)],
    )

    shadowed = importlib.util.find_spec("phalp")
    assert shadowed is not None
    assert shadowed.submodule_search_locations is None
    assert Path(shadowed.origin).resolve() == (bridge_dir / "phalp.py").resolve()

    external = bridge._find_external_phalp_spec()
    assert external is not None
    assert external.submodule_search_locations
    assert Path(next(iter(external.submodule_search_locations))).resolve() == fake_package.resolve()


def test_mp4_track_command_uses_low_vram_launcher(tmp_path):
    repo = tmp_path / "4D-Humans"
    source = tmp_path / "segment-01.mp4"
    output = tmp_path / "output"

    command = bridge._track_command(repo, source, output)

    assert command[:3] == [
        sys.executable,
        "-c",
        bridge._PHALP_MP4_LOW_VRAM_LAUNCHER,
    ]
    assert command[3] == str(repo / "track.py")
    assert "setup_detectron2_with_RPN" in command[2]
    assert "phalp.detector=" not in " ".join(command)
    assert "render.enable=false" in command
    assert "overwrite=true" in command


def test_low_vram_launcher_really_skips_ground_truth_detector(tmp_path):
    fake_site = tmp_path / "site-packages"
    tracker_package = fake_site / "phalp" / "trackers"
    tracker_package.mkdir(parents=True)
    (fake_site / "phalp" / "__init__.py").write_text("", encoding="utf-8")
    (tracker_package / "__init__.py").write_text("", encoding="utf-8")
    (tracker_package / "PHALP.py").write_text(
        "class PHALP:\n"
        "    def setup_detectron2_with_RPN(self):\n"
        "        self.detector_x = 'loaded'\n",
        encoding="utf-8",
    )

    fake_track = tmp_path / "track.py"
    fake_track.write_text(
        "from phalp.trackers.PHALP import PHALP\n"
        "tracker = PHALP()\n"
        "tracker.setup_detectron2_with_RPN()\n"
        "print(repr(tracker.detector_x))\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(fake_site)
    completed = subprocess.run(
        [sys.executable, "-c", bridge._PHALP_MP4_LOW_VRAM_LAUNCHER, str(fake_track)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "None"
