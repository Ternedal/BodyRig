from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "ci.yml",
    ROOT / ".github" / "workflows" / "codeql.yml",
    ROOT / ".github" / "workflows" / "loc-metrics.yml",
    ROOT / ".github" / "workflows" / "windows-log-handle-regression.yml",
)


def test_pr_workflow_concurrency_is_keyed_by_head_ref() -> None:
    expected = (
        'group: ${{ github.workflow }}-${{ '
        'github.event.pull_request.head.repo.full_name || github.repository }}-${{ '
        'github.event.pull_request.head.ref || github.ref }}'
    )
    for path in WORKFLOWS:
        source = path.read_text(encoding="utf-8")
        assert expected in source, path
        assert "github.event.pull_request.number || github.ref" not in source, path
        assert "github.event.pull_request.head.repo.full_name || github.repository" in source, path
        assert "cancel-in-progress: true" in source, path
