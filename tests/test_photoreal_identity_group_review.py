from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig.photoreal_identity_group_review import (
    ATTESTATION_FORMAT,
    PhotorealIdentityGroupReviewError,
    _candidate_id,
    _match_review_frame,
    record_attestation,
)


REVISION = "a" * 40
BANK_SHA = "b" * 64


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _review_root(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    root.mkdir()
    sheets = root / "private-review-sheets"
    sheets.mkdir()
    rows = []
    private_rows = []
    for index, group_id in enumerate(("scene:1", "scene:2"), start=1):
        sheet = sheets / f"group-{index}.png"
        sheet.write_bytes(f"sheet-{index}".encode("ascii"))
        rows.append(
            {
                "group_candidate_id": _candidate_id(BANK_SHA, group_id),
                "group_id": group_id,
                "reference_count": 1,
                "portrait_seed_centroid_cosine": 0.5 - index * 0.1,
                "review_sheet_sha256": _sha256(sheet),
                "samples": [],
            }
        )
        private_rows.append(
            {
                "group_candidate_id": _candidate_id(BANK_SHA, group_id),
                "group_id": group_id,
                "source_keys": [f"scene:{index}:E:/scene-{index}.mp4"],
                "review_sheet": str(sheet),
                "review_sheet_relative": f"private-review-sheets/{sheet.name}",
            }
        )
    public = {
        "format": "bodyrig-photoreal-identity-group-review-candidates",
        "version": 1,
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "identity_bank_sha256": BANK_SHA,
        "identity_bank_file_sha256": "c" * 64,
        "identity_request_sha256": "d" * 64,
        "portrait_seed_diagnostic_sha256": "e" * 64,
        "portrait_profile_sha256": "f" * 64,
        "group_count": 2,
        "groups": rows,
        "machine_portrait_cosine_authority": False,
        "human_identity_review_required": True,
        "identity_group_selection_authority": False,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    public_path = root / "identity-group-review-candidates.json"
    _write_json(public_path, public)
    private = {
        "format": "bodyrig-photoreal-private-identity-group-review-index",
        "version": 1,
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "public_manifest_sha256": _sha256(public_path),
        "portrait_profile_path": str(root / "profile.jpg"),
        "groups": private_rows,
        "source_paths_private": True,
        "production_activation": False,
    }
    _write_json(root / "private-review-index.json", private)
    return root


def test_candidate_id_is_bank_and_group_bound() -> None:
    first = _candidate_id(BANK_SHA, "scene:1")
    assert first.startswith("idgroup-")
    assert first == _candidate_id(BANK_SHA, "scene:1")
    assert first != _candidate_id(BANK_SHA, "scene:2")
    assert first != _candidate_id("c" * 64, "scene:1")


def test_review_frame_replays_supplied_stage7_sample_exactly() -> None:
    seen: dict[str, object] = {}
    image = object()
    sample = {"timestamp_seconds": 1.23456789, "eye": "mono"}

    class Base:
        @staticmethod
        def _read_sample(runtime, source, supplied):
            seen["sample"] = supplied
            return image, False

        @staticmethod
        def _frame_sha(value):
            assert value is image
            return "d" * 64

    adapter = SimpleNamespace(base=Base())
    result = _match_review_frame(
        adapter=adapter,
        runtime=object(),
        source={"projection": "flat"},
        sample=sample,
        reference={"frame_sha256": "d" * 64},
    )

    assert result is image
    assert seen["sample"] is sample


def test_human_attestation_requires_complete_partition_and_revalidates_sheets(
    tmp_path: Path,
) -> None:
    root = _review_root(tmp_path)

    result = record_attestation(
        review_root=root,
        attestation_revision=REVISION,
        accept_groups=["scene:1"],
        reject_groups=["scene:2"],
        quality_note="Reviewed both groups against the profile seed.",
        confirm_identity=True,
    )

    assert result["format"] == ATTESTATION_FORMAT
    assert result["accepted_group_ids"] == ["scene:1"]
    assert result["rejected_group_ids"] == ["scene:2"]
    assert result["human_identity_attested"] is True
    assert result["identity_group_selection_authority"] is True
    assert result["identity_matching_authorized"] is False
    assert result["teacher_training_authorized"] is False
    assert result["production_activation"] is False
    assert (root / "identity-group-attestation.json").is_file()


def test_human_attestation_fails_if_any_group_is_unclassified(tmp_path: Path) -> None:
    root = _review_root(tmp_path)

    with pytest.raises(
        PhotorealIdentityGroupReviewError,
        match="classify every group exactly once",
    ):
        record_attestation(
            review_root=root,
            attestation_revision=REVISION,
            accept_groups=["scene:1"],
            reject_groups=[],
            quality_note="Reviewed only one group, which is intentionally incomplete.",
            confirm_identity=True,
        )


def test_human_attestation_preserves_review_revision_from_older_checkout(
    tmp_path: Path,
) -> None:
    root = _review_root(tmp_path)
    attest_revision = "c" * 40

    result = record_attestation(
        review_root=root,
        attestation_revision=attest_revision,
        accept_groups=["scene:1", "scene:2"],
        reject_groups=[],
        quality_note="Reviewed both groups and confirmed both are the target performer.",
        confirm_identity=True,
    )

    assert result["review_bodyrig_revision"] == REVISION
    assert result["attestation_bodyrig_revision"] == attest_revision
    assert result["bodyrig_revision"] == attest_revision
    assert result["accepted_group_count"] == 2
    assert result["rejected_group_count"] == 0


def test_human_attestation_fails_if_review_sheet_bytes_change(tmp_path: Path) -> None:
    root = _review_root(tmp_path)
    private = json.loads((root / "private-review-index.json").read_text(encoding="utf-8"))
    sheet = Path(private["groups"][0]["review_sheet"])
    sheet.write_bytes(b"tampered")

    with pytest.raises(
        PhotorealIdentityGroupReviewError,
        match="review sheet bytes changed",
    ):
        record_attestation(
            review_root=root,
            attestation_revision=REVISION,
            accept_groups=["scene:1"],
            reject_groups=["scene:2"],
            quality_note="Reviewed both groups against the profile seed.",
            confirm_identity=True,
        )
