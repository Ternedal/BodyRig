from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_photoreal_link as link
from bodyrig.digital_twin_photoreal_link import (
    DigitalTwinPhotorealLinkError,
    build_photoreal_link,
    read_photoreal_link,
    validate_photoreal_link_structure,
    write_photoreal_link,
)

REVISION = "a" * 40
PERSON_ID = "person-" + "1" * 32
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-" + "2" * 32
PACKAGE_SHA = "3" * 64
ASSEMBLY_SHA = "4" * 64
M4_ID = "dtcomp-" + "5" * 32
PHOTO_ID = "photoperson-" + "6" * 32
P3_SHA = "7" * 64
TEACHER_SHA = "8" * 64
PLAN_SHA = "9" * 64


def _composition() -> dict[str, object]:
    return {
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": REVISION,
        "authority_id": M4_ID,
    }


def _photoreal() -> dict[str, object]:
    return {
        "binding_id": PHOTO_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": REVISION,
        "stash_performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": TEACHER_SHA,
        "p3_device_runtime_review_plan_sha256": PLAN_SHA,
        "target_device_family": "meta-quest",
        "target_device_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
    }


def _p3() -> dict[str, object]:
    return {
        "p3_physical_runtime_review_sha256": P3_SHA,
        "photoreal_acceptance_authority": True,
    }


def _arrange(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    composition: dict[str, object] | None = None,
    photoreal: dict[str, object] | None = None,
    p3: dict[str, object] | None = None,
) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "persons"
    root.mkdir()
    composition_dir = (
        root
        / "digital-twin-composition-authorities"
        / PERSON_ID
        / PERSON_REVISION
        / M4_ID
    )
    composition_dir.mkdir(parents=True)
    (composition_dir / "authority.json").write_text(
        json.dumps(composition or _composition()),
        encoding="utf-8",
    )
    (composition_dir / "person-assembly-receipt.json").write_text(
        json.dumps({"fixture": "assembly"}),
        encoding="utf-8",
    )
    (composition_dir / "body-release-status.json").write_text(
        json.dumps({"fixture": "release"}),
        encoding="utf-8",
    )

    photo_path = tmp_path / "photoreal-person-binding.json"
    p3_path = tmp_path / "p3-physical-runtime-review.json"
    photo_path.write_text(json.dumps(photoreal or _photoreal()), encoding="utf-8")
    p3_path.write_text(json.dumps(p3 or _p3()), encoding="utf-8")

    monkeypatch.setattr(
        link,
        "composition_authority_dir",
        lambda root_value, person_id, person_revision, authority_id: composition_dir,
    )
    monkeypatch.setattr(
        link,
        "read_composition_authority",
        lambda root_value, person_id, person_revision, authority_id: dict(
            composition or _composition()
        ),
    )
    monkeypatch.setattr(
        link,
        "validate_photoreal_person_binding_structure",
        lambda value: dict(value),
    )
    monkeypatch.setattr(
        link,
        "validate_physical_runtime_review_receipt",
        lambda value: dict(value),
    )
    monkeypatch.setattr(
        link,
        "revalidate_photoreal_person_binding",
        lambda value, **kwargs: dict(value),
    )
    return root, composition_dir, photo_path, p3_path


def test_build_link_binds_exact_m4_and_photoreal_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, photo_path, p3_path = _arrange(monkeypatch, tmp_path)

    authority = build_photoreal_link(
        root,
        composition_authority_dir_path=composition_dir,
        photoreal_person_binding_path=photo_path,
        p3_physical_runtime_review_path=p3_path,
        bodyrig_revision=REVISION,
    )

    assert authority["person_id"] == PERSON_ID
    assert authority["person_revision"] == PERSON_REVISION
    assert authority["composition_authority_id"] == M4_ID
    assert authority["photoreal_binding_id"] == PHOTO_ID
    assert authority["visual_authority"] == "photoreal-v2-p3"
    assert authority["m5_photoreal_integration_eligible"] is True
    assert authority["production_activation"] is False
    assert authority["link_id"].startswith("dtphoto-")


def test_identity_mismatch_between_m4_and_photoreal_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    photoreal = _photoreal()
    photoreal["body_id"] = "body-" + "f" * 32
    root, composition_dir, photo_path, p3_path = _arrange(
        monkeypatch,
        tmp_path,
        photoreal=photoreal,
    )

    with pytest.raises(
        DigitalTwinPhotorealLinkError,
        match="differ on exact body_id",
    ):
        build_photoreal_link(
            root,
            composition_authority_dir_path=composition_dir,
            photoreal_person_binding_path=photo_path,
            p3_physical_runtime_review_path=p3_path,
            bodyrig_revision=REVISION,
        )


def test_link_requires_same_bodyrig_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composition = _composition()
    composition["bodyrig_revision"] = "b" * 40
    root, composition_dir, photo_path, p3_path = _arrange(
        monkeypatch,
        tmp_path,
        composition=composition,
    )

    with pytest.raises(
        DigitalTwinPhotorealLinkError,
        match="same BodyRig revision",
    ):
        build_photoreal_link(
            root,
            composition_authority_dir_path=composition_dir,
            photoreal_person_binding_path=photo_path,
            p3_physical_runtime_review_path=p3_path,
            bodyrig_revision=REVISION,
        )


def test_link_requires_live_p3_photoreal_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p3 = _p3()
    p3["photoreal_acceptance_authority"] = False
    root, composition_dir, photo_path, p3_path = _arrange(
        monkeypatch,
        tmp_path,
        p3=p3,
    )

    with pytest.raises(
        DigitalTwinPhotorealLinkError,
        match="no longer grants photoreal acceptance",
    ):
        build_photoreal_link(
            root,
            composition_authority_dir_path=composition_dir,
            photoreal_person_binding_path=photo_path,
            p3_physical_runtime_review_path=p3_path,
            bodyrig_revision=REVISION,
        )


def test_link_version_true_and_production_activation_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, photo_path, p3_path = _arrange(monkeypatch, tmp_path)
    authority = build_photoreal_link(
        root,
        composition_authority_dir_path=composition_dir,
        photoreal_person_binding_path=photo_path,
        p3_physical_runtime_review_path=p3_path,
        bodyrig_revision=REVISION,
    )

    boolean_version = copy.deepcopy(authority)
    boolean_version["version"] = True
    with pytest.raises(DigitalTwinPhotorealLinkError, match="format/version/policy"):
        validate_photoreal_link_structure(boolean_version)

    activating = copy.deepcopy(authority)
    activating["production_activation"] = True
    with pytest.raises(DigitalTwinPhotorealLinkError, match="cannot activate production"):
        validate_photoreal_link_structure(activating)


def test_link_id_detects_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, photo_path, p3_path = _arrange(monkeypatch, tmp_path)
    authority = build_photoreal_link(
        root,
        composition_authority_dir_path=composition_dir,
        photoreal_person_binding_path=photo_path,
        p3_physical_runtime_review_path=p3_path,
        bodyrig_revision=REVISION,
    )
    authority["selected_epoch_id"] = "tampered"

    with pytest.raises(DigitalTwinPhotorealLinkError, match="link id no longer matches"):
        validate_photoreal_link_structure(authority)


def test_link_is_create_only_and_readback_revalidates_frozen_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, photo_path, p3_path = _arrange(monkeypatch, tmp_path)

    authority = write_photoreal_link(
        root,
        composition_authority_dir_path=composition_dir,
        photoreal_person_binding_path=photo_path,
        p3_physical_runtime_review_path=p3_path,
        bodyrig_revision=REVISION,
    )
    directory = link.photoreal_link_dir(
        root,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        link_id=authority["link_id"],
    )
    assert (directory / "authority.json").is_file()
    assert (directory / "photoreal-person-binding.json").is_file()
    assert (directory / "p3-physical-runtime-review.json").is_file()

    readback = read_photoreal_link(
        root,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        link_id=authority["link_id"],
        composition_authority_dir_path=composition_dir,
    )
    assert readback == authority

    with pytest.raises(DigitalTwinPhotorealLinkError, match="already exists"):
        write_photoreal_link(
            root,
            composition_authority_dir_path=composition_dir,
            photoreal_person_binding_path=photo_path,
            p3_physical_runtime_review_path=p3_path,
            bodyrig_revision=REVISION,
        )
