from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import bodyrig.bridges.hmr2_4dhumans_bridge as bridge


def test_hmr2_bridge_seeds_phalp_smpl_cache_from_local_authority(monkeypatch, tmp_path):
    repo = tmp_path / "4D-Humans"
    source = repo / "data" / bridge.SMPL_FILENAME
    source.parent.mkdir(parents=True)
    source.write_bytes(b"licensed-smpl-authority")

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    calls = []

    def fake_run(command, *, cwd=None, **kwargs):
        calls.append((command, Path(cwd)))
        converted = Path(cwd) / f"{Path(bridge.SMPL_FILENAME).stem}_p3.pkl"
        converted.write_bytes(b"converted-smpl")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    cache = bridge._ensure_phalp_smpl_cache(repo)
    expected_dir = home / ".cache" / "phalp" / "3D" / "models" / "smpl"
    assert cache == expected_dir / bridge.PHALP_SMPL_FILENAME
    assert cache.read_bytes() == b"converted-smpl"
    assert (expected_dir / bridge.PHALP_SMPL_SOURCE_HASH_FILENAME).read_text(encoding="ascii").strip() == hashlib.sha256(source.read_bytes()).hexdigest()
    assert len(calls) == 1
    assert "from phalp.utils.utils import convert_pkl" in calls[0][0][2]

    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cache should be reused")),
    )
    assert bridge._ensure_phalp_smpl_cache(repo) == cache
