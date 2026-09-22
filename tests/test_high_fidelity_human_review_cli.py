from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig import high_fidelity_human_review_cli as cli
from bodyrig.high_fidelity_human_review import (
    CHECKLIST_FIELDS,
    PHOTOIDENTITY_CHECKLIST_FIELDS,
    HighFidelityHumanReviewError,
)


def _args(package: Path) -> list[str]:
    return [
        "--package",
        str(package),
        "--confirm-quality-checklist",
        "--quality-note",
        "physical high-fidelity review",
    ]


def test_cli_removes_only_new_receipt_when_post_write_verification_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    receipt_path = tmp_path / "candidate.review.json"
    receipt = {
        "body_id": "bodyid-test",
        "package_sha256": "1" * 64,
        "component_state_sha256": "2" * 64,
        "policy_revision": "bodyrig-high-fidelity-human-review-v1",
    }

    def write_review(*args, **kwargs):
        receipt_path.write_text("new receipt\n", encoding="utf-8")
        return receipt

    def fail_read(*args, **kwargs):
        raise HighFidelityHumanReviewError("post-write verification failed")

    monkeypatch.setattr(cli, "write_review", write_review)
    monkeypatch.setattr(cli, "review_path", lambda *args, **kwargs: receipt_path)
    monkeypatch.setattr(cli, "read_review", fail_read)

    assert cli.main(_args(package)) == 1
    assert not receipt_path.exists()
    assert "post-write verification failed" in capsys.readouterr().err


def test_cli_never_removes_preexisting_receipt_when_create_only_write_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    receipt_path = tmp_path / "candidate.review.json"
    receipt_path.write_text("authoritative existing receipt\n", encoding="utf-8")

    def reject_write(*args, **kwargs):
        raise HighFidelityHumanReviewError("refusing to overwrite existing high-fidelity human review")

    monkeypatch.setattr(cli, "write_review", reject_write)
    monkeypatch.setattr(cli, "review_path", lambda *args, **kwargs: receipt_path)

    assert cli.main(_args(package)) == 1
    assert receipt_path.read_text(encoding="utf-8") == "authoritative existing receipt\n"


def test_cli_routes_all_photoidentity_confirmations_into_exact_checklist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package = tmp_path / "photoidentical.mrbody"
    package.write_bytes(b"package")
    receipt_path = tmp_path / "photoidentical.review.json"
    captured: dict[str, object] = {}
    receipt = {
        "body_id": "bodyid-test",
        "package_sha256": "1" * 64,
        "component_state_sha256": "2" * 64,
        "policy_revision": "bodyrig-high-fidelity-human-review-v2-photoidentity",
    }

    def write_review(*args, **kwargs):
        captured["checklist"] = kwargs["checklist"]
        return receipt

    monkeypatch.setattr(cli, "write_review", write_review)
    monkeypatch.setattr(cli, "review_path", lambda *args, **kwargs: receipt_path)
    monkeypatch.setattr(cli, "read_review", lambda *args, **kwargs: receipt)

    args = _args(package) + [
        "--confirm-oral-teeth-photoidentity",
        "--confirm-chest-breast-shape-photoidentity",
        "--confirm-nipple-areola-photoidentity",
        "--confirm-intimate-anatomy-photoidentity",
        "--confirm-distinctive-markers-photoidentity",
    ]
    assert cli.main(args) == 0
    assert set(captured["checklist"]) == set(CHECKLIST_FIELDS) | set(PHOTOIDENTITY_CHECKLIST_FIELDS)
    assert all(captured["checklist"].values())
    assert '"policy_revision":"bodyrig-high-fidelity-human-review-v2-photoidentity"' in capsys.readouterr().out
