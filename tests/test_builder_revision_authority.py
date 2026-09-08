from __future__ import annotations

import subprocess
from pathlib import Path

from bodyrig.external_fitter_cli import _clean_checkout_revision


ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_clean_checkout_revision_binds_exact_git_head_and_rejects_dirty_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "bodyrig-test@example.invalid")
    _git(repo, "config", "user.name", "BodyRig Test")
    tracked = repo / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "fixture")
    expected = _git(repo, "rev-parse", "HEAD").lower()

    assert len(expected) == 40
    assert _clean_checkout_revision(repo) == expected

    tracked.write_text("dirty\n", encoding="utf-8")
    assert _clean_checkout_revision(repo) is None


def test_clean_checkout_revision_rejects_untracked_files_and_non_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "bodyrig-test@example.invalid")
    _git(repo, "config", "user.name", "BodyRig Test")
    tracked = repo / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "fixture")

    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    assert _clean_checkout_revision(repo) is None
    assert _clean_checkout_revision(tmp_path / "not-a-repo") is None


def test_external_fitter_package_wiring_uses_clean_checkout_revision() -> None:
    source = (ROOT / "bodyrig" / "external_fitter_cli.py").read_text(encoding="utf-8")
    assert "builder_revision=_clean_checkout_revision()" in source
