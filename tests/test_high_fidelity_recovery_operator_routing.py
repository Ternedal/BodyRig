from __future__ import annotations

from pathlib import Path

import bodyrig.high_fidelity_release_readiness_cli as cli


REVISION = "f" * 40
JOB_ID = "hfpreview-" + "e" * 32


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    for relative in cli.CANONICAL_OPERATOR_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if path.suffix == ".json" else "exit 0\n", encoding="utf-8")
    (root / "archive-invalid-high-fidelity-human-review.ps1").write_text("exit 0\n", encoding="utf-8")
    return root


def test_recovery_command_is_checkout_bound_and_absolutized_before_gate_a(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"package")
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))
    monkeypatch.setattr(cli, "_has_minimum_handoff_revision", lambda _root, _revision: True)
    result = {
        "state": "human-review-recovery-required",
        "gates": [],
        "next_gate": {
            "gate": "high_fidelity_human_review_recovery",
            "command": (
                ".\\archive-invalid-high-fidelity-human-review.ps1 "
                f"-PreviewJobId '{JOB_ID}' -PackagePath '{package.resolve()}'"
            ),
            "operator_input_required": True,
            "reason": "preserve invalid review",
        },
        "production_ready": False,
        "production_activation": False,
    }

    bound = cli.bind_operator_checkout(result, root)

    assert bound["state"] == "human-review-recovery-required"
    assert bound["operator_checkout"]["authorized"] is True
    assert bound["operator_checkout"]["accepted_revision"] is None
    command = bound["next_gate"]["command"]
    assert command.startswith('& "')
    assert str((root / "archive-invalid-high-fidelity-human-review.ps1").resolve()) in command
    assert f"-PreviewJobId '{JOB_ID}'" in command
    assert f"-PackagePath '{package.resolve()}'" in command


def test_recovery_command_is_blocked_on_stale_pre_gate_a_checkout(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))
    monkeypatch.setattr(cli, "_has_minimum_handoff_revision", lambda _root, _revision: False)
    result = {
        "state": "human-review-recovery-required",
        "gates": [],
        "next_gate": {
            "gate": "high_fidelity_human_review_recovery",
            "command": (
                ".\\archive-invalid-high-fidelity-human-review.ps1 "
                f"-PreviewJobId '{JOB_ID}' -PackagePath 'C:\\hf\\promoted.mrbody'"
            ),
            "operator_input_required": True,
            "reason": "preserve invalid review",
        },
        "production_ready": False,
        "production_activation": False,
    }

    bound = cli.bind_operator_checkout(result, root)

    assert bound["state"] == "blocked"
    assert bound["next_gate"] is None
    assert bound["operator_checkout"]["authorized"] is False
    assert cli.MINIMUM_PHYSICAL_HANDOFF_REVISION in bound["operator_checkout"]["reason"]
