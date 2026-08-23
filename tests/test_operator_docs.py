from __future__ import annotations

import re
from pathlib import Path


RENDERER_ACCEPTANCE_CALL = re.compile(
    r"(?ms)^\.\\record-renderer-acceptance\.ps1 `\n"
    r"(?P<args>(?:  -[^\n]+\n?)+)"
)
RECOVERY_PREFLIGHT_CALL = re.compile(
    r"(?ms)^bodyrig-recovery-preflight `\n"
    r"(?P<args>(?:  --[^\n]+\n?)+)"
)
VALIDATE_RIG_CALL = re.compile(
    r"(?ms)^\.\\validate-rig\.ps1 `\n"
    r"(?P<args>(?:  -[^\n]+\n?)+)"
)


def _calls(path: Path, pattern: re.Pattern[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [match.group("args") for match in pattern.finditer(text)]


def test_operator_docs_bind_every_renderer_attestation_to_machine_probe() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    expected_calls = {
        repo_root / "README.md": 2,
        repo_root / "docs" / "RIG_ACCEPTANCE.md": 2,
    }

    for path, expected_count in expected_calls.items():
        calls = _calls(path, RENDERER_ACCEPTANCE_CALL)
        assert len(calls) == expected_count, (
            f"{path.relative_to(repo_root)} must document exactly {expected_count} "
            "record-renderer-acceptance.ps1 invocations"
        )
        for args in calls:
            assert "-ProbeReport " in args, (
                f"{path.relative_to(repo_root)} documents a renderer attestation "
                "without the mandatory -ProbeReport machine evidence"
            )


def test_recovery_preflight_docs_bind_to_pinned_phalp_checkout() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    paths = [repo_root / "README.md", repo_root / "docs" / "HMR2_BRIDGE.md"]
    for path in paths:
        calls = _calls(path, RECOVERY_PREFLIGHT_CALL)
        assert calls, f"{path.relative_to(repo_root)} must document bodyrig-recovery-preflight"
        for args in calls:
            assert "--phalp-repo " in args, (
                f"{path.relative_to(repo_root)} documents recovery preflight "
                "without the pinned --phalp-repo checkout"
            )


def test_low_level_validate_rig_docs_bind_to_pinned_phalp_checkout() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "docs" / "RIG_ACCEPTANCE.md"
    calls = _calls(path, VALIDATE_RIG_CALL)
    assert calls, "docs/RIG_ACCEPTANCE.md must document validate-rig.ps1"
    for args in calls:
        assert "-PhalpRepo " in args, (
            "docs/RIG_ACCEPTANCE.md documents validate-rig.ps1 without "
            "the mandatory -PhalpRepo checkout"
        )
