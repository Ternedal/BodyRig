from __future__ import annotations

import re
from pathlib import Path


RENDERER_ACCEPTANCE_CALL = re.compile(
    r"(?ms)^\.\\record-renderer-acceptance\.ps1 `\n"
    r"(?P<args>(?:  -[^\n]+\n?)+)"
)


def _renderer_acceptance_calls(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [match.group("args") for match in RENDERER_ACCEPTANCE_CALL.finditer(text)]


def test_operator_docs_bind_every_renderer_attestation_to_machine_probe() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    expected_calls = {
        repo_root / "README.md": 2,
        repo_root / "docs" / "RIG_ACCEPTANCE.md": 2,
    }

    for path, expected_count in expected_calls.items():
        calls = _renderer_acceptance_calls(path)
        assert len(calls) == expected_count, (
            f"{path.relative_to(repo_root)} must document exactly {expected_count} "
            "record-renderer-acceptance.ps1 invocations"
        )
        for args in calls:
            assert "-ProbeReport " in args, (
                f"{path.relative_to(repo_root)} documents a renderer attestation "
                "without the mandatory -ProbeReport machine evidence"
            )
