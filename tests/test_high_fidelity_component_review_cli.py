from __future__ import annotations

from pathlib import Path

import bodyrig.high_fidelity_component_review_cli as cli
from bodyrig.high_fidelity_component_review import HighFidelityComponentReviewError

JOB_ID = "hfpreview-0123456789abcdef0123456789abcdef"
REVISION = "1" * 40


def _argv() -> list[str]:
    return [
        "--preview-job-id",
        JOB_ID,
        "--bodyrig-revision",
        REVISION,
        "--confirm-visual-checklist",
        "--quality-note",
        "Reviewed exact six-view evidence.",
    ]


def _receipt() -> dict:
    return {
        "preview_job_id": JOB_ID,
        "bodyrig_revision": REVISION,
        "candidate_package_sha256": "a" * 64,
        "review_vrm_sha256": "b" * 64,
        "promotion_eligibility": {"body_anatomy": True, "hair": False, "eyes": False},
        "review_outcome": {
            "body_anatomy": "pass",
            "hair": "visual-pass-deformation-review-required",
            "eyes": "visual-pass-iris-authority-required",
        },
    }


def test_cli_removes_only_new_receipt_when_post_write_verification_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.json"

    def fake_write(*args, **kwargs):
        path.write_text("new receipt", encoding="utf-8")
        return _receipt()

    monkeypatch.setattr(cli, "write_review", fake_write)
    monkeypatch.setattr(cli, "review_path", lambda *args, **kwargs: path)
    monkeypatch.setattr(
        cli,
        "read_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(HighFidelityComponentReviewError("verification failed")),
    )

    assert cli.main(_argv()) == 1
    assert not path.exists()


def test_cli_never_removes_preexisting_receipt_when_create_only_write_is_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.json"
    original = b"pre-existing authority"
    path.write_bytes(original)

    monkeypatch.setattr(
        cli,
        "write_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HighFidelityComponentReviewError("refusing to overwrite existing component review")
        ),
    )
    monkeypatch.setattr(cli, "review_path", lambda *args, **kwargs: path)

    assert cli.main(_argv()) == 1
    assert path.read_bytes() == original
