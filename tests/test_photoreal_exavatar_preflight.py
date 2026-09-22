from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_preflight as preflight


def _prepare_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    deps = tmp_path / "deps"
    assets = tmp_path / "assets"
    reference = tmp_path / "reference"
    deps.mkdir()
    assets.mkdir()
    reference.mkdir()
    for name, relative in preflight.PUBLIC_TOOL_LAYOUT.items():
        (deps / relative).mkdir(parents=True)
    for _name, relative, _restricted in preflight.ASSET_LAYOUT:
        path = assets / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode("utf-8") or b"x")
    for _name, relative in preflight.REFERENCE_ASSETS:
        path = reference / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode("utf-8") or b"x")
    return deps, assets, reference


def _patch_git_and_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    commits = {preflight.PUBLIC_TOOL_LAYOUT[name]: commit for name, _url, commit in preflight.REPOSITORIES}

    def fake_git(path: Path, *args: str):
        if args == ("rev-parse", "HEAD"):
            return commits[path.name]
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_git", fake_git)
    monkeypatch.setattr(preflight.shutil, "which", lambda name: f"/usr/bin/{name}")


def test_preflight_passes_only_with_exact_pinned_code_and_local_assets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deps, assets, reference = _prepare_roots(tmp_path)
    _patch_git_and_tools(monkeypatch)

    result = preflight.build_exavatar_preflight(
        dependency_root=deps,
        asset_root=assets,
        reference_model_root=reference,
        smplx_gender="female",
    )

    assert result["benchmark_environment_ready"] is True
    assert result["blockers"] == []
    assert result["smplx_gender"] == "female"
    assert result["smplx_gender_explicit"] is True
    assert result["upstream_default_gender_accepted"] is False
    assert result["automatic_restricted_asset_download"] is False
    assert all(item["sha256"] for item in result["assets"])
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_preflight_has_no_default_gender(tmp_path: Path) -> None:
    with pytest.raises(preflight.PhotorealExAvatarPreflightError, match="explicitly female, male or neutral"):
        preflight.build_exavatar_preflight(
            dependency_root=tmp_path,
            asset_root=tmp_path,
            reference_model_root=tmp_path,
            smplx_gender="",
        )


def test_preflight_blocks_wrong_dependency_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deps, assets, reference = _prepare_roots(tmp_path)
    _patch_git_and_tools(monkeypatch)
    original = preflight._git

    def wrong_git(path: Path, *args: str):
        if path.name == "ExAvatar_RELEASE" and args == ("rev-parse", "HEAD"):
            return "f" * 40
        return original(path, *args)

    monkeypatch.setattr(preflight, "_git", wrong_git)
    result = preflight.build_exavatar_preflight(
        dependency_root=deps,
        asset_root=assets,
        reference_model_root=reference,
        smplx_gender="female",
    )

    assert result["benchmark_environment_ready"] is False
    assert "dependency commit mismatch: exavatar" in result["blockers"]


def test_preflight_blocks_missing_restricted_asset_without_downloading(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deps, assets, reference = _prepare_roots(tmp_path)
    _patch_git_and_tools(monkeypatch)
    missing = assets / "human_model_files" / "smplx" / "SMPLX_FEMALE.npz"
    missing.unlink()

    result = preflight.build_exavatar_preflight(
        dependency_root=deps,
        asset_root=assets,
        reference_model_root=reference,
        smplx_gender="female",
    )

    assert result["benchmark_environment_ready"] is False
    assert "missing asset: human_model_files/smplx/SMPLX_FEMALE.npz" in result["blockers"]
    record = next(item for item in result["assets"] if item["name"] == "smplx_female")
    assert record["restricted_or_operator_supplied"] is True
    assert result["automatic_restricted_asset_download"] is False


def test_preflight_can_make_colmap_optional_but_never_nvcc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deps, assets, reference = _prepare_roots(tmp_path)
    _patch_git_and_tools(monkeypatch)
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None if name in {"nvcc", "colmap"} else f"/usr/bin/{name}")

    result = preflight.build_exavatar_preflight(
        dependency_root=deps,
        asset_root=assets,
        reference_model_root=reference,
        smplx_gender="neutral",
        require_colmap=False,
    )

    assert "required executable missing: colmap" not in result["blockers"]
    assert "required executable missing: nvcc" in result["blockers"]
    assert result["benchmark_environment_ready"] is False


def test_git_uses_command_local_safe_directory_for_root_owned_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "ExAvatar_RELEASE"
    checkout.mkdir()
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = "d45268730c779fae4118f1a361cf9ff639bc4d1e\n"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    observed = preflight._git(checkout, "rev-parse", "HEAD")

    resolved = checkout.resolve()
    assert observed == "d45268730c779fae4118f1a361cf9ff639bc4d1e"
    assert captured["command"] == [
        "git",
        "-c",
        f"safe.directory={resolved}",
        "-C",
        str(resolved),
        "rev-parse",
        "HEAD",
    ]
    assert captured["kwargs"]["shell"] is False
