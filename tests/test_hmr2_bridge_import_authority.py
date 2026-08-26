import importlib.util
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
