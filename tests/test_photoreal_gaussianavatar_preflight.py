from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig import photoreal_gaussianavatar_preflight as preflight


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    ga = tmp_path / "GaussianAvatar"
    ia = tmp_path / "InstantAvatar"
    assets = tmp_path / "assets"
    ga.mkdir()
    ia.mkdir()
    for relative in preflight.REQUIRED_FEMALE_SMPL_ASSETS:
        path = assets / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode("utf-8"))
    return ga, ia, assets


def _pin_git(monkeypatch: pytest.MonkeyPatch, ga: Path, ia: Path) -> None:
    commits = {
        ga.resolve(): preflight.GAUSSIANAVATAR_COMMIT,
        ia.resolve(): preflight.INSTANTAVATAR_COMMIT,
    }

    def fake_git(path: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return commits[path.resolve()]
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_git", fake_git)
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)


def test_gaussianavatar_preflight_is_explicit_female_smpl_not_fake_smplx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ga, ia, assets = _roots(tmp_path)
    _pin_git(monkeypatch, ga, ia)
    result = preflight.build_gaussianavatar_preflight(
        gaussianavatar_root=ga,
        instantavatar_root=ia,
        asset_root=assets,
        smpl_gender="female",
    )
    assert result["source_asset_preflight_ready"] is True
    assert result["smpl_gender"] == "female"
    assert result["smpl_gender_explicit"] is True
    assert result["smpl_type"] == "smpl"
    assert result["smplx_training_path_claimed"] is False
    assert result["execution_runtime_ready"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_dependency_authorized"] is False
    assert result["production_activation"] is False


def test_gaussianavatar_preflight_rejects_nonfemale_prior_for_performer_42(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ga, ia, assets = _roots(tmp_path)
    _pin_git(monkeypatch, ga, ia)
    with pytest.raises(preflight.PhotorealGaussianAvatarPreflightError, match="smpl_gender=female"):
        preflight.build_gaussianavatar_preflight(
            gaussianavatar_root=ga,
            instantavatar_root=ia,
            asset_root=assets,
            smpl_gender="neutral",
        )


def test_gaussianavatar_preflight_blocks_missing_canonical_asset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ga, ia, assets = _roots(tmp_path)
    _pin_git(monkeypatch, ga, ia)
    missing = assets / "lbs_map_smpl_512.npy"
    missing.unlink()
    result = preflight.build_gaussianavatar_preflight(
        gaussianavatar_root=ga,
        instantavatar_root=ia,
        asset_root=assets,
        smpl_gender="female",
    )
    assert result["source_asset_preflight_ready"] is False
    assert "missing GaussianAvatar benchmark asset: lbs_map_smpl_512.npy" in result["blockers"]


def test_gaussianavatar_preflight_blocks_commit_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ga, ia, assets = _roots(tmp_path)

    def fake_git(path: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return "f" * 40 if path.resolve() == ga.resolve() else preflight.INSTANTAVATAR_COMMIT
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_git", fake_git)
    monkeypatch.setattr(preflight.shutil, "which", lambda _name: "/usr/bin/git")
    result = preflight.build_gaussianavatar_preflight(
        gaussianavatar_root=ga,
        instantavatar_root=ia,
        asset_root=assets,
        smpl_gender="female",
    )
    assert result["source_asset_preflight_ready"] is False
    assert any("repository commit mismatch: GaussianAvatar" in blocker for blocker in result["blockers"])
