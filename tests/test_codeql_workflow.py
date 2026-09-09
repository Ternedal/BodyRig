from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "codeql.yml"
CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
CODEQL_SHA = "cdf488f595d80d6e07e03d4674febd5ab45fa938"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_codeql_workflow_exists_and_scans_python_only() -> None:
    text = _text()
    assert "name: codeql" in text
    assert "languages: python" in text
    assert "languages: powershell" not in text.lower()
    assert "languages: javascript" not in text.lower()
    assert "languages: go" not in text.lower()


def test_codeql_workflow_runs_on_main_pr_push_and_schedule() -> None:
    text = _text()
    assert "push:" in text
    assert "pull_request:" in text
    assert text.count("branches: [main]") == 2
    assert "schedule:" in text
    assert "cron:" in text


def test_codeql_workflow_permissions_are_minimal() -> None:
    text = _text()
    permissions = re.search(r"(?ms)^permissions:\n(?P<body>(?:  .+\n)+?)\n", text)
    assert permissions is not None
    lines = {line.strip() for line in permissions.group("body").splitlines() if line.strip()}
    assert lines == {"contents: read", "security-events: write"}
    assert "write-all" not in text


def test_codeql_actions_are_exact_sha_pinned() -> None:
    text = _text()
    assert f"uses: actions/checkout@{CHECKOUT_SHA}" in text
    assert f"uses: github/codeql-action/init@{CODEQL_SHA}" in text
    assert f"uses: github/codeql-action/analyze@{CODEQL_SHA}" in text

    for uses_target in re.findall(r"uses:\s*([^\s#]+)", text):
        assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", uses_target), uses_target


def test_codeql_check_name_is_stable_for_repository_authority() -> None:
    text = _text()
    assert "name: analyze (python)" in text
