from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.person_body_review import (
    CANONICAL_VIEWS,
    PersonBodyReviewError,
    persist_review,
    read_review,
    validate_fidelity_output,
)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fidelity_output(tmp_path: Path, *, body_id: str, package_sha256: str) -> Path:
    root = tmp_path / "fidelity"
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True)

    entries = []
    for view in CANONICAL_VIEWS:
        payload = b"\x89PNG\r\n\x1a\nbodyrig-test-" + view.encode("ascii")
        path = snapshots / f"{view}.png"
        path.write_bytes(payload)
        entries.append(
            {
                "view": view,
                "file": f"{view}.png",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "width": 1024,
                "height": 1024,
            }
        )

    _write_json(
        snapshots / "fidelity-render-set.json",
        {
            "format": "bodyrig-fidelity-render-set",
            "version": 1,
            "body_id": body_id,
            "package_sha256": package_sha256,
            "semantics": "visual-fidelity-not-identity-verification",
            "snapshots": entries,
        },
    )
    _write_json(
        root / "comparison-authority.json",
        {
            "format": "bodyrig-fidelity-comparison-authority",
            "version": 1,
            "authority": "gate-a-pending-candidate",
            "bodyrig_revision": "a" * 40,
            "runtime_manifest_sha256": "b" * 64,
            "package_sha256": package_sha256,
            "physical_acceptance_authority": True,
            "comparison_only": True,
            "production_activation": False,
        },
    )
    return root


def test_persisted_body_review_is_bound_to_exact_package_and_four_views(tmp_path: Path) -> None:
    person_id = "person-" + "1" * 32
    body_id = "bodyid-" + "2" * 24
    package_sha = "3" * 64
    source = _fidelity_output(tmp_path, body_id=body_id, package_sha256=package_sha)
    library = tmp_path / "people"

    validated = validate_fidelity_output(source, body_id=body_id, package_sha256=package_sha)
    assert [item["view"] for item in validated["views"]] == list(CANONICAL_VIEWS)

    persisted = persist_review(
        library,
        person_id=person_id,
        fidelity_output_dir=source,
        body_id=body_id,
        package_sha256=package_sha,
    )
    assert persisted["package_sha256"] == package_sha
    assert persisted["body_id"] == body_id
    assert persisted["semantics"] == "visual-fidelity-not-identity-verification"
    assert [item["view"] for item in persisted["views"]] == list(CANONICAL_VIEWS)

    profile = {
        "person_id": person_id,
        "body_revisions": [
            {
                "revision_id": "body-r0001",
                "body_id": body_id,
                "package_sha256": package_sha,
            }
        ],
    }
    reread = read_review(library, profile, body_revision="body-r0001")
    assert reread["package_sha256"] == package_sha
    assert len(reread["views"]) == 4


def test_persisted_body_review_fails_closed_after_image_tampering(tmp_path: Path) -> None:
    person_id = "person-" + "4" * 32
    body_id = "bodyid-" + "5" * 24
    package_sha = "6" * 64
    source = _fidelity_output(tmp_path, body_id=body_id, package_sha256=package_sha)
    library = tmp_path / "people"
    persist_review(
        library,
        person_id=person_id,
        fidelity_output_dir=source,
        body_id=body_id,
        package_sha256=package_sha,
    )
    profile = {
        "person_id": person_id,
        "body_revisions": [
            {
                "revision_id": "body-r0001",
                "body_id": body_id,
                "package_sha256": package_sha,
            }
        ],
    }

    image = library / ".body-reviews" / person_id / package_sha / "front-full.png"
    image.write_bytes(image.read_bytes() + b"tamper")

    with pytest.raises(PersonBodyReviewError, match="persisted body review image has changed"):
        read_review(library, profile, body_revision="body-r0001")


def test_fidelity_output_rejects_wrong_candidate_package(tmp_path: Path) -> None:
    body_id = "bodyid-" + "7" * 24
    source = _fidelity_output(tmp_path, body_id=body_id, package_sha256="8" * 64)

    with pytest.raises(PersonBodyReviewError, match="package SHA does not match"):
        validate_fidelity_output(source, body_id=body_id, package_sha256="9" * 64)
