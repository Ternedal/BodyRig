from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

import bodyrig.hands_feet_nails_release_authority as release
from bodyrig.hands_feet_nails_authority import CHECKLIST_FIELDS
from bodyrig.hands_feet_nails_source_capture import REQUIRED_REGIONS


PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"
BODYRIG_REVISION = "1" * 40
PACKAGE_SHA = "2" * 64
ASSEMBLY_SHA = "3" * 64
REVIEW_ID = "hfnreview-0123456789abcdef0123456789abcdef"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png(extra: bytes = b"") -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1024, 1024) + extra


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


def _review(render_manifest_sha: str, region_hashes: dict[str, str]) -> dict:
    return {
        "review_id": REVIEW_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": BODYRIG_REVISION,
        "source_capture_id": "hfncap-0123456789abcdef0123456789abcdef",
        "source_capture_sha256": "9" * 64,
        "source_manifest_sha256": "a" * 64,
        "source_region_sha256": {
            "left_hand": "b" * 64,
            "right_hand": "c" * 64,
            "left_foot": "d" * 64,
            "right_foot": "e" * 64,
        },
        "render_manifest_sha256": render_manifest_sha,
        "render_region_sha256": dict(region_hashes),
        **{field: True for field in CHECKLIST_FIELDS},
    }


def _render_bundle(tmp_path: Path, *, bodyrig_revision: str = BODYRIG_REVISION, package_sha: str = PACKAGE_SHA) -> tuple[Path, dict]:
    root = tmp_path / "render-bundle"
    snapshots_root = root / "snapshots"
    snapshots_root.mkdir(parents=True)
    snapshots = []
    region_hashes: dict[str, str] = {}
    for region in REQUIRED_REGIONS:
        image = snapshots_root / f"{region}.png"
        image.write_bytes(_png(region.encode()))
        image_sha = _sha(image)
        region_hashes[region] = image_sha
        snapshots.append(
            {
                "view": region,
                "file": image.name,
                "sha256": image_sha,
                "width": 1024,
                "height": 1024,
            }
        )
    manifest = {
        "format": "bodyrig-hands-feet-nails-render-set",
        "version": 1,
        "body_id": BODY_ID,
        "package_sha256": package_sha,
        "semantics": "human-review-diagnostic-not-physical-pass",
        "snapshots": snapshots,
    }
    manifest_path = snapshots_root / "hands-feet-nails-render-set.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    comparison = {
        "format": "bodyrig-fidelity-comparison-authority",
        "version": 1,
        "authority": "validated-package-comparison-only",
        "bodyrig_revision": bodyrig_revision,
        "runtime_manifest_sha256": "f" * 64,
        "package_sha256": package_sha,
        "physical_acceptance_authority": False,
        "comparison_only": True,
        "production_activation": False,
    }
    comparison_path = root / "comparison-authority.json"
    comparison_path.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")

    render_authority = {
        "format": "bodyrig-hands-feet-nails-render-authority",
        "version": 1,
        "bodyrig_revision": bodyrig_revision,
        "body_id": BODY_ID,
        "package_sha256": package_sha,
        "runtime_manifest_sha256": "f" * 64,
        "comparison_authority_sha256": _sha(comparison_path),
        "render_manifest_sha256": _sha(manifest_path),
        "render_region_sha256": region_hashes,
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    }
    render_authority_path = root / "hands-feet-nails-render-authority.json"
    render_authority_path.write_text(json.dumps(render_authority, indent=2) + "\n", encoding="utf-8")
    return render_authority_path, _review(_sha(manifest_path), region_hashes)


def _install_review_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, review: dict) -> Path:
    review_root = tmp_path / "raw-review"
    review_root.mkdir()
    review_path = review_root / "authority.json"
    review_path.write_text(json.dumps(review, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(release, "read_authority", lambda *args, **kwargs: dict(review))
    monkeypatch.setattr(release, "review_authority_dir", lambda *args, **kwargs: review_root)
    return review_path


def test_finalize_and_readback_bind_review_render_and_comparison(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    render_authority_path, review = _render_bundle(tmp_path)
    _install_review_fixture(tmp_path, monkeypatch, review)

    receipt = release.write_release_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        review_id=REVIEW_ID,
        render_authority_path=render_authority_path,
    )

    assert receipt["state"] == "complete"
    assert receipt["source_grounded"] is True
    assert receipt["operator_supplied"] is True
    assert receipt["production_activation"] is False
    assert receipt["body_package_sha256"] == PACKAGE_SHA
    reread = release.read_release_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        release_id=receipt["release_id"],
    )
    assert reread == receipt


def test_finalize_rejects_renderer_from_different_bodyrig_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    render_authority_path, review = _render_bundle(tmp_path, bodyrig_revision="0" * 40)
    review["bodyrig_revision"] = BODYRIG_REVISION
    _install_review_fixture(tmp_path, monkeypatch, review)

    with pytest.raises(release.HandsFeetNailsReleaseAuthorityError, match="different BodyRig revision"):
        release.write_release_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            review_id=REVIEW_ID,
            render_authority_path=render_authority_path,
        )


def test_finalize_rejects_renderer_from_different_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    render_authority_path, review = _render_bundle(tmp_path, package_sha="0" * 64)
    review["body_package_sha256"] = PACKAGE_SHA
    _install_review_fixture(tmp_path, monkeypatch, review)

    with pytest.raises(release.HandsFeetNailsReleaseAuthorityError, match="different body package"):
        release.write_release_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            review_id=REVIEW_ID,
            render_authority_path=render_authority_path,
        )


def test_frozen_comparison_tamper_revokes_finalized_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    render_authority_path, review = _render_bundle(tmp_path)
    _install_review_fixture(tmp_path, monkeypatch, review)
    receipt = release.write_release_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        review_id=REVIEW_ID,
        render_authority_path=render_authority_path,
    )
    target = release.release_authority_dir(tmp_path, PERSON_ID, PERSON_REVISION, receipt["release_id"])
    (target / "comparison-authority.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(release.HandsFeetNailsReleaseAuthorityError, match="comparison-authority bytes changed"):
        release.read_release_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            release_id=receipt["release_id"],
        )


def test_frozen_render_authority_tamper_revokes_finalized_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    render_authority_path, review = _render_bundle(tmp_path)
    _install_review_fixture(tmp_path, monkeypatch, review)
    receipt = release.write_release_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        review_id=REVIEW_ID,
        render_authority_path=render_authority_path,
    )
    target = release.release_authority_dir(tmp_path, PERSON_ID, PERSON_REVISION, receipt["release_id"])
    (target / "render-authority.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(release.HandsFeetNailsReleaseAuthorityError, match="render-authority bytes changed"):
        release.read_release_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            release_id=receipt["release_id"],
        )
