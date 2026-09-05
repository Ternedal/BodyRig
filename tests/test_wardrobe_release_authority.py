from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.wardrobe_release_authority as release
from bodyrig.wardrobe_authority import CHECKLIST_FIELDS
from bodyrig.wardrobe_source_capture import REQUIRED_VIEWS


PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"
BODYRIG_REVISION = "1" * 40
PACKAGE_SHA = "2" * 64
ASSEMBLY_SHA = "3" * 64
REVIEW_ID = "wardreview-0123456789abcdef0123456789abcdef"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assembly() -> dict:
    return {
        "format": "bodyrig-person-assembly-receipt",
        "version": 2,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body": {"revision_id": BODY_REVISION, "body_id": BODY_ID, "package_sha256": "4" * 64},
        "voice": {
            "revision_id": "voice-r0001",
            "voice_id": "voice-0123456789abcdef0123456789abcdef",
            "voice_package": "voice-a.voice",
            "package_sha256": "5" * 64,
        },
        "personality": {
            "revision_id": "personality-r0001",
            "default_language": "da-DK",
            "instructions_sha256": "6" * 64,
            "style_notes_sha256": "7" * 64,
        },
        "audition": {
            "audition_id": "audition-0123456789abcdef0123456789abcdef",
            "receipt_sha256": "8" * 64,
        },
    }


def _body_release() -> dict:
    return {
        "format": "bodyrig-person-release-status",
        "version": 1,
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "production_ready": True,
        "production_activation": True,
    }


def _review() -> dict:
    return {
        "review_id": REVIEW_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": BODYRIG_REVISION,
        "source_capture_id": "wardcap-0123456789abcdef0123456789abcdef",
        "source_capture_sha256": "9" * 64,
        "source_manifest_sha256": "a" * 64,
        "source_view_sha256": {
            "front": "b" * 64,
            "left_side": "c" * 64,
            "right_side": "d" * 64,
            "back": "e" * 64,
        },
        "garment_inventory_sha256": "f" * 64,
        "garment_count": 3,
        "footwear_present": True,
        "footwear_review_required": True,
        "footwear_review_passed": True,
        **{field: True for field in CHECKLIST_FIELDS},
    }


def _install_review_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    review = _review()
    review_root = tmp_path / "raw-review"
    review_root.mkdir()
    review_path = review_root / "authority.json"
    review_path.write_text(json.dumps(review, sort_keys=True) + "\n", encoding="utf-8")
    render_root = review_root / "render"
    snapshots = render_root / "snapshots"
    snapshots.mkdir(parents=True)
    files = {
        "wardrobe-render-authority.json": {"kind": "render-authority"},
        "wardrobe-package-lineage.json": {"kind": "package-lineage"},
        "comparison-authority.json": {"kind": "comparison"},
        "machine-probe.json": {"kind": "machine"},
        "deformation-probe.json": {"kind": "deformation"},
    }
    for name, value in files.items():
        (render_root / name).write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    (snapshots / "wardrobe-render-set.json").write_text('{"kind":"manifest"}\n', encoding="utf-8")
    for view in REQUIRED_VIEWS:
        (snapshots / f"{view}.png").write_bytes(view.encode("utf-8"))

    monkeypatch.setattr(release, "read_authority", lambda *args, **kwargs: dict(review))
    monkeypatch.setattr(release, "review_authority_dir", lambda *args, **kwargs: review_root)

    def fake_validate(path, *, body_id, package_sha256, bodyrig_revision):
        root = Path(path).resolve().parent
        manifest = root / "snapshots" / "wardrobe-render-set.json"
        return {
            "path": Path(path).resolve(),
            "sha256": _sha(Path(path).resolve()),
            "lineage_sha256": _sha(root / "wardrobe-package-lineage.json"),
            "comparison_sha256": _sha(root / "comparison-authority.json"),
            "runtime_manifest_sha256": "0" * 64,
            "machine_sha256": _sha(root / "machine-probe.json"),
            "deformation_sha256": _sha(root / "deformation-probe.json"),
            "rendered": {
                "manifest_sha256": _sha(manifest),
                "view_sha256": {view: _sha(root / "snapshots" / f"{view}.png") for view in REQUIRED_VIEWS},
            },
        }

    monkeypatch.setattr(release, "validate_render_authority_bundle", fake_validate)
    return review_root, review


def test_finalize_and_readback_bind_review_and_frozen_render_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_review_fixture(tmp_path, monkeypatch)

    receipt = release.write_release_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        review_id=REVIEW_ID,
        bodyrig_revision=BODYRIG_REVISION,
    )

    assert receipt["state"] == "complete"
    assert receipt["source_grounded"] is True
    assert receipt["operator_supplied"] is True
    assert receipt["footwear_present"] is True
    assert receipt["footwear_review_passed"] is True
    assert receipt["production_activation"] is False
    reread = release.read_release_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        release_id=receipt["release_id"],
    )
    assert reread == receipt


def test_finalize_rejects_different_checkout_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_review_fixture(tmp_path, monkeypatch)

    with pytest.raises(release.WardrobeReleaseAuthorityError, match="exact BodyRig revision"):
        release.write_release_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            review_id=REVIEW_ID,
            bodyrig_revision="0" * 40,
        )


def test_frozen_raw_review_tamper_revokes_finalized_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_review_fixture(tmp_path, monkeypatch)
    receipt = release.write_release_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        review_id=REVIEW_ID,
        bodyrig_revision=BODYRIG_REVISION,
    )
    target = release.release_authority_dir(tmp_path, PERSON_ID, PERSON_REVISION, receipt["release_id"])
    (target / "review-authority.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(release.WardrobeReleaseAuthorityError, match="human-review authority bytes changed"):
        release.read_release_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            release_id=receipt["release_id"],
        )


def test_frozen_render_authority_tamper_revokes_finalized_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_review_fixture(tmp_path, monkeypatch)
    receipt = release.write_release_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        review_id=REVIEW_ID,
        bodyrig_revision=BODYRIG_REVISION,
    )
    target = release.release_authority_dir(tmp_path, PERSON_ID, PERSON_REVISION, receipt["release_id"])
    (target / "render" / "wardrobe-render-authority.json").write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(release.WardrobeReleaseAuthorityError, match="render_authority_sha256"):
        release.read_release_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            release_id=receipt["release_id"],
        )
