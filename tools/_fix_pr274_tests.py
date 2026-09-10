from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "tests/test_pbr_ab_body_job_source.py",
    "def test_valid_succeeded_revision_bound_body_job_is_safe_retained_source(tmp_path: Path, monkeypatch) -> None:\n"
    "    repo, _job_root, job = _setup(tmp_path, monkeypatch)\n",
    "def test_valid_succeeded_revision_bound_body_job_is_safe_retained_source(tmp_path: Path, monkeypatch) -> None:\n"
    "    repo, job_root, job = _setup(tmp_path, monkeypatch)\n",
)

replace_exact(
    "tests/test_throughput_candidate_from_ab_plan_contract.py",
    "    assert '$raw.Count -ne 1' not in WRAPPER\n",
    "    assert 'if ($raw.Count -ne 1) { throw \"Internal throughput candidate launcher did not return exactly one machine-readable result.\" }' not in WRAPPER\n",
)

for relative in (
    "tools/_fix_pr274_tests.py",
    ".github/workflows/_fix_pr274_tests.yml",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()

print("PR #274 test corrections applied")
