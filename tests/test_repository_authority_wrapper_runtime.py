"""Run verify-repository-authority.ps1 for real.

``test_repository_authority_wrapper_contract.py`` reads the wrapper's source.
This runs it, in PowerShell, against a fake ``gh`` in a throw-away checkout on
``main``. The wrapper used to fail on the configuration BodyRig actually has
(classic branch protection, no rulesets), while the evaluator passed on the
same data.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from bodyrig import repository_authority as authority

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is unavailable")

# A fake GitHub CLI. It answers from JSON files in FAKE_GH_DIR and fails, as
# the real one does, for an endpoint that has no file.
FAKE_GH = r'''
import os, sys
from pathlib import Path

root = Path(os.environ["FAKE_GH_DIR"])
args = sys.argv[1:]
if args[:1] == ["auth"]:
    sys.exit(0)
if args[:1] != ["api"] or len(args) < 2:
    sys.exit(1)
path = args[1]
if path.endswith("/branches/main/protection"):
    name = "protection.json"
elif path.endswith("/branches/main"):
    name = "branch.json"
elif path.endswith("/rulesets?includes_parents=true"):
    name = "rulesets.json"
elif "/rulesets/" in path:
    name = "ruleset-" + path.rsplit("/", 1)[1] + ".json"
else:
    print("unexpected endpoint " + path, file=sys.stderr)
    sys.exit(1)
target = root / name
if not target.is_file():
    print('{"message":"Not Found"}', file=sys.stderr)
    sys.exit(1)
sys.stdout.write(target.read_text(encoding="utf-8"))
'''


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c", "user.name=contract",
            "-c", "user.email=contract@example.invalid",
            "-c", "commit.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _classic_protection() -> dict:
    """Classic branch protection that satisfies the evaluator."""
    return {
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "required_status_checks": {
            "strict": True,
            "checks": [
                {"context": name, "app_id": authority._expected_check_app_id(name)}
                for name in authority.REQUIRED_STATUS_CHECKS
            ],
        },
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_conversation_resolution": {"enabled": True},
    }


def _ruleset(number: int, *, active: bool) -> dict:
    """A ruleset on main. An active one satisfies the evaluator on its own."""
    return {
        "id": number,
        "name": f"main-authority-{number}",
        "target": "branch",
        "enforcement": "active" if active else "disabled",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {"required_review_thread_resolution": True}},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": name, "integration_id": authority._expected_check_app_id(name)}
                        for name in authority.REQUIRED_STATUS_CHECKS
                    ],
                },
            },
        ],
    }


class Checkout:
    """A clean checkout on ``main`` holding the wrapper and its evaluator."""

    def __init__(self, base: Path) -> None:
        self.root = base / "checkout"
        (self.root / "bodyrig").mkdir(parents=True)
        shutil.copy(ROOT / "verify-repository-authority.ps1", self.root)
        for name in ("__init__.py", "repository_authority.py"):
            shutil.copy(ROOT / "bodyrig" / name, self.root / "bodyrig" / name)
        _git(self.root, "init", "--quiet", "--initial-branch=main")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "--quiet", "-m", "wrapper contract fixture")
        self.head = _git(self.root, "rev-parse", "HEAD")
        self.tools = base / "tools"
        self.tools.mkdir()
        script = self.tools / "fake_gh.py"
        script.write_text(FAKE_GH, encoding="utf-8")
        if os.name == "nt":
            (self.tools / "gh.cmd").write_text(
                f'@"{sys.executable}" "{script}" %*\r\n', encoding="ascii"
            )
        else:
            launcher = self.tools / "gh"
            launcher.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="ascii"
            )
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
        self.github = base / "github"
        self.github.mkdir()

    def github_state(
        self,
        *,
        head: str | None = None,
        protection: dict | None,
        rulesets: list[dict] | None,
    ) -> None:
        for stale in self.github.iterdir():
            stale.unlink()
        branch = {"name": "main", "protected": True, "commit": {"sha": head or self.head}}
        (self.github / "branch.json").write_text(json.dumps(branch), encoding="utf-8")
        if protection is not None:
            (self.github / "protection.json").write_text(json.dumps(protection), encoding="utf-8")
        if rulesets is not None:
            summaries = [{"id": item["id"], "name": item["name"]} for item in rulesets]
            (self.github / "rulesets.json").write_text(json.dumps(summaries), encoding="utf-8")
            for item in rulesets:
                (self.github / f"ruleset-{item['id']}.json").write_text(
                    json.dumps(item), encoding="utf-8"
                )

    def run(self, *extra: str) -> subprocess.CompletedProcess:
        environment = dict(os.environ)
        environment["PATH"] = str(self.tools) + os.pathsep + environment.get("PATH", "")
        environment["FAKE_GH_DIR"] = str(self.github)
        # The wrapper must find the evaluator in ITS checkout, not in this one.
        environment.pop("PYTHONPATH", None)
        return subprocess.run(
            [
                PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                str(self.root / "verify-repository-authority.ps1"),
                "-BodyRigPython", sys.executable,
                *extra,
            ],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            env=environment,
            timeout=300,
            check=False,
        )

    def verdict(self) -> tuple[int, dict]:
        completed = self.run("-Json")
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, (
            f"-Json must print exactly one line; rc={completed.returncode}\n"
            f"stdout={completed.stdout[-600:]}\nstderr={completed.stderr[-600:]}"
        )
        return completed.returncode, json.loads(lines[0])


@pytest.fixture()
def checkout(tmp_path: Path) -> Checkout:
    return Checkout(tmp_path)


def test_classic_protection_without_rulesets_passes(checkout: Checkout) -> None:
    # What BodyRig has today. An empty ruleset list used to write no file.
    checkout.github_state(protection=_classic_protection(), rulesets=[])
    code, verdict = checkout.verdict()
    assert code == 0, verdict
    assert verdict["passed"] is True
    assert verdict["authority_mode"] == "classic"
    assert verdict["head_revision"] == checkout.head
    assert verdict["format"] == authority.FORMAT
    assert verdict["production_activation"] is False


def test_a_single_ruleset_reaches_the_evaluator_as_a_list(checkout: Checkout) -> None:
    # A pipeline unrolls a one-element array into a bare object, and the
    # evaluator then sees no ruleset at all.
    checkout.github_state(protection=None, rulesets=[_ruleset(100, active=True)])
    code, verdict = checkout.verdict()
    assert code == 0, verdict
    assert verdict["authority_mode"] == "ruleset"
    assert verdict["rulesets"]["applicable_ruleset_ids"] == [100]


def test_two_rulesets_reach_the_evaluator_as_two(checkout: Checkout) -> None:
    checkout.github_state(
        protection=None,
        rulesets=[_ruleset(100, active=False), _ruleset(101, active=True)],
    )
    code, verdict = checkout.verdict()
    assert code == 0, verdict
    assert verdict["rulesets"]["applicable_ruleset_ids"] == [101]


def test_an_unreadable_rulesets_endpoint_is_not_a_crash(checkout: Checkout) -> None:
    checkout.github_state(protection=_classic_protection(), rulesets=None)
    code, verdict = checkout.verdict()
    assert code == 0, verdict
    assert verdict["authority_mode"] == "classic"


def test_a_deficit_is_a_verdict_with_exit_2(checkout: Checkout) -> None:
    weak = _classic_protection()
    weak["enforce_admins"] = {"enabled": False}
    checkout.github_state(protection=weak, rulesets=[])
    code, verdict = checkout.verdict()
    assert code == 2
    assert verdict["passed"] is False
    assert verdict["authority_mode"] is None
    assert any("administrators can bypass" in error for error in verdict["classic"]["errors"])

    checkout.github_state(protection=None, rulesets=[])
    code, verdict = checkout.verdict()
    assert code == 2
    assert verdict["passed"] is False


def test_main_elsewhere_than_the_checkout_fails(checkout: Checkout) -> None:
    checkout.github_state(head="f" * 40, protection=_classic_protection(), rulesets=[])
    code, verdict = checkout.verdict()
    assert code == 2
    assert any("does not match" in error for error in verdict["errors"])


def test_human_readable_output(checkout: Checkout) -> None:
    checkout.github_state(protection=_classic_protection(), rulesets=[])
    completed = checkout.run()
    assert completed.returncode == 0, completed.stderr[-400:]
    assert "BodyRig repository authority: PASS" in completed.stdout
    assert checkout.head in completed.stdout


def test_only_an_exact_clean_main_checkout_is_verified(checkout: Checkout) -> None:
    checkout.github_state(protection=_classic_protection(), rulesets=[])
    (checkout.root / "stray.txt").write_text("x\n", encoding="utf-8")
    completed = checkout.run("-Json")
    assert completed.returncode != 0
    assert "exact clean main checkout" in completed.stderr + completed.stdout
    (checkout.root / "stray.txt").unlink()

    _git(checkout.root, "checkout", "--quiet", "-b", "feature")
    completed = checkout.run("-Json")
    assert completed.returncode != 0
    assert "must run from branch main" in completed.stderr + completed.stdout
