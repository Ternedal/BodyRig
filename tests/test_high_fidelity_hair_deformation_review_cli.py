from __future__ import annotations

from pathlib import Path

import bodyrig.high_fidelity_hair_deformation_review_cli as cli
from bodyrig.high_fidelity_hair_deformation_review import HighFidelityHairDeformationReviewError

JOB_ID = "hfpreview-0123456789abcdef0123456789abcdef"
REVISION = "1" * 40


def _argv(*, confirm: bool = True) -> list[str]:
    args = [
        "--preview-job-id",
        JOB_ID,
        "--bodyrig-revision",
        REVISION,
    ]
    if confirm:
        args.append("--confirm-hair-deformation-checklist")
    args.extend(
        [
            "--quality-note",
            "Reviewed head-turn attachment, clipping, silhouette stability and restoration to neutral.",
        ]
    )
    return args


def _receipt() -> dict:
    return {
        "preview_job_id": JOB_ID,
        "bodyrig_revision": REVISION,
        "candidate_package_sha256": "a" * 64,
        "review_vrm_sha256": "b" * 64,
        "hair_deformation_probe_sha256": "c" * 64,
        "machine_metrics": {
            "observed_head_turn_degrees": 18.2,
            "vertex_motion_rms_m": 0.0005,
            "vertex_motion_max_m": 0.0015,
            "restoration_rms_m": 0.0001,
            "restoration_max_m": 0.0005,
        },
        "hair_promotion_eligible": True,
        "human_review_complete": True,
        "production_activation": False,
    }


def test_cli_requires_explicit_hair_deformation_confirmation(monkeypatch) -> None:
    called = False

    def fake_write(*args, **kwargs):
        nonlocal called
        called = True
        return _receipt()

    monkeypatch.setattr(cli, "write_review", fake_write)

    assert cli.main(_argv(confirm=False)) == 1
    assert called is False


def test_cli_removes_only_new_receipt_when_post_write_verification_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "hair-review.json"

    def fake_write(*args, **kwargs):
        path.write_text("new receipt", encoding="utf-8")
        return _receipt()

    monkeypatch.setattr(cli, "write_review", fake_write)
    monkeypatch.setattr(cli, "review_path", lambda *args, **kwargs: path)
    monkeypatch.setattr(
        cli,
        "read_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HighFidelityHairDeformationReviewError("verification failed")
        ),
    )

    assert cli.main(_argv()) == 1
    assert not path.exists()


def test_cli_never_removes_preexisting_receipt_when_create_only_write_is_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "hair-review.json"
    original = b"pre-existing authority"
    path.write_bytes(original)

    monkeypatch.setattr(
        cli,
        "write_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HighFidelityHairDeformationReviewError(
                "refusing to overwrite existing hair deformation review"
            )
        ),
    )
    monkeypatch.setattr(cli, "review_path", lambda *args, **kwargs: path)

    assert cli.main(_argv()) == 1
    assert path.read_bytes() == original
