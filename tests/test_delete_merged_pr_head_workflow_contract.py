from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_delete_merged_pr_head_workflow_is_same_repo_and_merged_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "delete-merged-pr-head.yml").read_text(encoding="utf-8")
    assert "github.event.pull_request.merged == true" in workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow
    assert "BODYRIG_HEAD_BRANCH: ${{ github.event.pull_request.head.ref }}" in workflow
    assert '"${{ github.event.pull_request.head.ref }}"' not in workflow


def test_delete_merged_pr_head_preserves_evidence_lineage() -> None:
    workflow = (ROOT / ".github" / "workflows" / "delete-merged-pr-head.yml").read_text(encoding="utf-8")
    assert '"architecture/"' in workflow
    assert '"candidate/"' in workflow
    assert '"diagnostic/"' in workflow
    assert '"feat/delete-unused-personality-revisions-20260919"' in workflow


def test_delete_merged_pr_head_verifies_remote_before_deletion() -> None:
    workflow = (ROOT / ".github" / "workflows" / "delete-merged-pr-head.yml").read_text(encoding="utf-8")
    assert "git ls-remote --exit-code --heads origin $branch" in workflow
    assert "git push origin --delete $branch" in workflow
