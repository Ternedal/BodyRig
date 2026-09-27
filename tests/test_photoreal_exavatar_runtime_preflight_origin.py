from __future__ import annotations

from types import SimpleNamespace

from bodyrig import photoreal_exavatar_runtime_preflight as runtime


def test_workspace_origin_accepts_regular_package_under_pinned_repo(tmp_path) -> None:
    repo = tmp_path / "repo"
    package = repo / "package"
    package.mkdir(parents=True)
    module = SimpleNamespace(
        __file__=str(package / "__init__.py"),
        __path__=[str(package)],
    )

    assert runtime._module_resolves_from_repo(module, repo) is True
    assert runtime._module_origin(module) == str((package / "__init__.py").resolve())


def test_workspace_origin_accepts_namespace_package_under_pinned_repo(tmp_path) -> None:
    repo = tmp_path / "Depth-Anything-V2"
    package = repo / "depth_anything_v2"
    package.mkdir(parents=True)
    module = SimpleNamespace(__file__=None, __path__=[str(package)])

    assert runtime._module_resolves_from_repo(module, repo) is True
    assert runtime._module_origin(module) == str(package.resolve())


def test_workspace_origin_rejects_namespace_package_with_external_portion(tmp_path) -> None:
    repo = tmp_path / "Depth-Anything-V2"
    package = repo / "depth_anything_v2"
    external = tmp_path / "site-packages" / "depth_anything_v2"
    package.mkdir(parents=True)
    external.mkdir(parents=True)
    module = SimpleNamespace(
        __file__=None,
        __path__=[str(package), str(external)],
    )

    assert runtime._module_resolves_from_repo(module, repo) is False


def test_workspace_origin_rejects_module_without_location(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    module = SimpleNamespace(__file__=None, __path__=[])

    assert runtime._module_resolves_from_repo(module, repo) is False
