from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_preflight as base
from bodyrig import photoreal_exavatar_preflight_strict as strict


def _prepare_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    deps = tmp_path / "deps"
    assets = tmp_path / "assets"
    reference = tmp_path / "reference"
    deps.mkdir()
    assets.mkdir()
    reference.mkdir()
    for _name, relative in base.PUBLIC_TOOL_LAYOUT.items():
        (deps / relative).mkdir(parents=True)
    for _name, relative, _restricted in base.ASSET_LAYOUT:
        path = assets / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode("utf-8"))
    for _name, relative in strict.STRICT_EXTRA_ASSETS:
        path = assets / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode("utf-8"))
    for _name, relative in base.REFERENCE_ASSETS:
        path = reference / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode("utf-8"))
    return deps, assets, reference


def _patch_git_and_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    commits = {base.PUBLIC_TOOL_LAYOUT[name]: commit for name, _url, commit in base.REPOSITORIES}

    def fake_git(path: Path, *args: str):
        if args == ("rev-parse", "HEAD"):
            return commits[path.name]
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(base, "_git", fake_git)
    monkeypatch.setattr(base.shutil, "which", lambda name: f"/usr/bin/{name}")


def test_strict_preflight_requires_complete_upstream_runtime_assets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deps, assets, reference = _prepare_roots(tmp_path)
    _patch_git_and_tools(monkeypatch)

    result = strict.build_exavatar_preflight_strict(
        dependency_root=deps,
        asset_root=assets,
        reference_model_root=reference,
        smplx_gender="female",
    )

    assert result["benchmark_environment_ready"] is True
    assert result["strict_upstream_asset_inventory"] is True
    assert result["strict_flame_asset_count"] == len(strict.STRICT_FLAME_ASSETS) == 3
    assert result["strict_hand4whole_asset_count"] == len(strict.STRICT_HAND4WHOLE_ASSETS) == 4
    assert result["strict_extra_asset_count"] == len(strict.STRICT_EXTRA_ASSETS) == 7
    names = {item["name"] for item in result["assets"]}
    assert {name for name, _relative in strict.STRICT_EXTRA_ASSETS}.issubset(names)
    assert result["smplx_gender"] == "female"
    assert result["upstream_default_gender_accepted"] is False


def test_strict_preflight_blocks_missing_flame_texture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deps, assets, reference = _prepare_roots(tmp_path)
    _patch_git_and_tools(monkeypatch)
    missing = assets / "human_model_files" / "flame" / "FLAME_texture.npz"
    missing.unlink()

    result = strict.build_exavatar_preflight_strict(
        dependency_root=deps,
        asset_root=assets,
        reference_model_root=reference,
        smplx_gender="female",
    )

    assert result["benchmark_environment_ready"] is False
    assert "missing asset: human_model_files/flame/FLAME_texture.npz" in result["blockers"]
    record = next(item for item in result["assets"] if item["name"] == "flame_texture")
    assert record["present"] is False
    assert record["sha256"] is None


def test_strict_preflight_blocks_missing_hand4whole_j14_regressor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deps, assets, reference = _prepare_roots(tmp_path)
    _patch_git_and_tools(monkeypatch)
    missing = assets / "human_model_files" / "smplx" / "SMPLX_to_J14.pkl"
    missing.unlink()

    result = strict.build_exavatar_preflight_strict(
        dependency_root=deps,
        asset_root=assets,
        reference_model_root=reference,
        smplx_gender="female",
    )

    assert result["benchmark_environment_ready"] is False
    assert "missing asset: human_model_files/smplx/SMPLX_to_J14.pkl" in result["blockers"]
    record = next(item for item in result["assets"] if item["name"] == "hand4whole_smplx_to_j14")
    assert record["present"] is False
    assert record["sha256"] is None


def test_strict_preflight_digest_changes_with_supplemental_assets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deps, assets, reference = _prepare_roots(tmp_path)
    _patch_git_and_tools(monkeypatch)

    first = strict.build_exavatar_preflight_strict(
        dependency_root=deps,
        asset_root=assets,
        reference_model_root=reference,
        smplx_gender="female",
    )
    texture = assets / "human_model_files" / "flame" / "FLAME_texture.npz"
    texture.write_bytes(b"changed-texture")
    second = strict.build_exavatar_preflight_strict(
        dependency_root=deps,
        asset_root=assets,
        reference_model_root=reference,
        smplx_gender="female",
    )

    assert first["preflight_sha256"] != second["preflight_sha256"]
