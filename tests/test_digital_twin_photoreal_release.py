from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_photoreal_release as release
from bodyrig.digital_twin_photoreal_release import (
    DigitalTwinPhotorealReleaseError,
    build_photoreal_release,
    read_photoreal_release,
    validate_photoreal_release_structure,
    write_photoreal_release,
)

REVISION = "a" * 40
PERSON_ID = "person-" + "1" * 32
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-" + "2" * 32
PACKAGE_SHA = "3" * 64
ASSEMBLY_SHA = "4" * 64
CANONICAL_M6_ID = "dtrelease-" + "5" * 32
PHOTO_M5_ID = "dtphotom5-" + "6" * 32
M4_PHOTO_ID = "dtphoto-" + "7" * 32
WINDOWS_SHA = "8" * 64
QUEST_SHA = "9" * 64


def _canonical_m6() -> dict[str, object]:
    return {
        "release_id": CANONICAL_M6_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": REVISION,
        "windows_realization_sha256": WINDOWS_SHA,
        "quest_realization_sha256": QUEST_SHA,
        "state": "released",
        "digital_twin_ready": True,
        "production_activation": True,
    }


def _photoreal_m5() -> dict[str, object]:
    return {
        "link_id": PHOTO_M5_ID,
        "m4_photoreal_link_id": M4_PHOTO_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": REVISION,
        "windows_realization_sha256": WINDOWS_SHA,
        "quest_realization_sha256": QUEST_SHA,
        "photoreal_m5_ready": True,
        "m6_photoreal_release_eligible": True,
        "production_activation": False,
    }


def _arrange(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    canonical_m6: dict[str, object] | None = None,
    photoreal_m5: dict[str, object] | None = None,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    root = tmp_path / "persons"
    root.mkdir()
    canonical_dir = (
        root
        / "digital-twin-releases"
        / PERSON_ID
        / PERSON_REVISION
        / CANONICAL_M6_ID
    )
    canonical_dir.mkdir(parents=True)
    canonical_value = canonical_m6 or _canonical_m6()
    (canonical_dir / "authority.json").write_text(
        json.dumps(canonical_value),
        encoding="utf-8",
    )

    photoreal_m5_dir = (
        root
        / "digital-twin-photoreal-m5-links"
        / PERSON_ID
        / PERSON_REVISION
        / PHOTO_M5_ID
    )
    photoreal_m5_dir.mkdir(parents=True)
    m5_value = photoreal_m5 or _photoreal_m5()
    (photoreal_m5_dir / "authority.json").write_text(
        json.dumps(m5_value),
        encoding="utf-8",
    )

    composition_dir = tmp_path / "composition"
    composition_dir.mkdir()
    acceptance_dir = tmp_path / "acceptance"
    acceptance_dir.mkdir()
    m4_photoreal_dir = tmp_path / "m4-photoreal"
    m4_photoreal_dir.mkdir()

    monkeypatch.setattr(
        release,
        "release_dir",
        lambda root_value, person_id, person_revision, release_id: canonical_dir,
    )
    monkeypatch.setattr(
        release,
        "read_release",
        lambda root_value, **kwargs: dict(canonical_value),
    )
    monkeypatch.setattr(
        release,
        "photoreal_m5_link_dir",
        lambda root_value, person_id, person_revision, link_id: photoreal_m5_dir,
    )
    monkeypatch.setattr(
        release,
        "read_photoreal_m5_link",
        lambda root_value, **kwargs: dict(m5_value),
    )
    return (
        root,
        canonical_dir,
        composition_dir,
        acceptance_dir,
        photoreal_m5_dir,
        m4_photoreal_dir,
    )


def test_photoreal_release_requires_canonical_m6_and_same_realizations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, canonical_dir, composition_dir, acceptance_dir, m5_dir, m4_dir = _arrange(
        monkeypatch,
        tmp_path,
    )

    authority = build_photoreal_release(
        root,
        canonical_m6_release_dir_path=canonical_dir,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance_dir,
        photoreal_m5_link_authority_dir_path=m5_dir,
        m4_photoreal_link_authority_dir_path=m4_dir,
        bodyrig_revision=REVISION,
    )

    assert authority["canonical_m6_release_id"] == CANONICAL_M6_ID
    assert authority["photoreal_m5_link_id"] == PHOTO_M5_ID
    assert authority["m4_photoreal_link_id"] == M4_PHOTO_ID
    assert authority["windows_realization_sha256"] == WINDOWS_SHA
    assert authority["quest_realization_sha256"] == QUEST_SHA
    assert authority["visual_authority"] == "photoreal-v2-p3"
    assert authority["canonical_digital_twin_ready"] is True
    assert authority["photoreal_digital_twin_ready"] is True
    assert authority["production_activation"] is True


def test_photoreal_release_cannot_bypass_incomplete_canonical_m6(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    canonical = _canonical_m6()
    canonical["digital_twin_ready"] = False
    canonical["production_activation"] = False
    root, canonical_dir, composition_dir, acceptance_dir, m5_dir, m4_dir = _arrange(
        monkeypatch,
        tmp_path,
        canonical_m6=canonical,
    )

    with pytest.raises(
        DigitalTwinPhotorealReleaseError,
        match="not an activating complete digital twin",
    ):
        build_photoreal_release(
            root,
            canonical_m6_release_dir_path=canonical_dir,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance_dir,
            photoreal_m5_link_authority_dir_path=m5_dir,
            m4_photoreal_link_authority_dir_path=m4_dir,
            bodyrig_revision=REVISION,
        )


def test_photoreal_release_cannot_bypass_incomplete_photoreal_m5(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    m5_value = _photoreal_m5()
    m5_value["m6_photoreal_release_eligible"] = False
    root, canonical_dir, composition_dir, acceptance_dir, m5_dir, m4_dir = _arrange(
        monkeypatch,
        tmp_path,
        photoreal_m5=m5_value,
    )

    with pytest.raises(
        DigitalTwinPhotorealReleaseError,
        match="does not authorize final Photoreal release",
    ):
        build_photoreal_release(
            root,
            canonical_m6_release_dir_path=canonical_dir,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance_dir,
            photoreal_m5_link_authority_dir_path=m5_dir,
            m4_photoreal_link_authority_dir_path=m4_dir,
            bodyrig_revision=REVISION,
        )


def test_photoreal_release_requires_same_platform_realizations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    m5_value = _photoreal_m5()
    m5_value["quest_realization_sha256"] = "f" * 64
    root, canonical_dir, composition_dir, acceptance_dir, m5_dir, m4_dir = _arrange(
        monkeypatch,
        tmp_path,
        photoreal_m5=m5_value,
    )

    with pytest.raises(
        DigitalTwinPhotorealReleaseError,
        match="differ on quest_realization_sha256",
    ):
        build_photoreal_release(
            root,
            canonical_m6_release_dir_path=canonical_dir,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance_dir,
            photoreal_m5_link_authority_dir_path=m5_dir,
            m4_photoreal_link_authority_dir_path=m4_dir,
            bodyrig_revision=REVISION,
        )


def test_photoreal_release_structure_is_bool_safe_and_activating_only_at_final_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, canonical_dir, composition_dir, acceptance_dir, m5_dir, m4_dir = _arrange(
        monkeypatch,
        tmp_path,
    )
    authority = build_photoreal_release(
        root,
        canonical_m6_release_dir_path=canonical_dir,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance_dir,
        photoreal_m5_link_authority_dir_path=m5_dir,
        m4_photoreal_link_authority_dir_path=m4_dir,
        bodyrig_revision=REVISION,
    )

    boolean_version = copy.deepcopy(authority)
    boolean_version["version"] = True
    with pytest.raises(DigitalTwinPhotorealReleaseError, match="format/version/policy"):
        validate_photoreal_release_structure(boolean_version)

    deactivated = copy.deepcopy(authority)
    deactivated["production_activation"] = False
    with pytest.raises(DigitalTwinPhotorealReleaseError, match="not production activating"):
        validate_photoreal_release_structure(deactivated)


def test_photoreal_release_id_detects_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, canonical_dir, composition_dir, acceptance_dir, m5_dir, m4_dir = _arrange(
        monkeypatch,
        tmp_path,
    )
    authority = build_photoreal_release(
        root,
        canonical_m6_release_dir_path=canonical_dir,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance_dir,
        photoreal_m5_link_authority_dir_path=m5_dir,
        m4_photoreal_link_authority_dir_path=m4_dir,
        bodyrig_revision=REVISION,
    )
    authority["quest_realization_sha256"] = "f" * 64

    with pytest.raises(DigitalTwinPhotorealReleaseError, match="release id no longer matches"):
        validate_photoreal_release_structure(authority)


def test_write_and_readback_are_create_only_and_revalidate_both_chains(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, canonical_dir, composition_dir, acceptance_dir, m5_dir, m4_dir = _arrange(
        monkeypatch,
        tmp_path,
    )

    authority = write_photoreal_release(
        root,
        canonical_m6_release_dir_path=canonical_dir,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance_dir,
        photoreal_m5_link_authority_dir_path=m5_dir,
        m4_photoreal_link_authority_dir_path=m4_dir,
        bodyrig_revision=REVISION,
    )
    directory = release.photoreal_release_dir(
        root,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        release_id=authority["release_id"],
    )
    assert (directory / "canonical-m6-authority.json").is_file()
    assert (directory / "photoreal-m5-link.json").is_file()

    readback = read_photoreal_release(
        root,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        release_id=authority["release_id"],
        canonical_m6_release_dir_path=canonical_dir,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance_dir,
        photoreal_m5_link_authority_dir_path=m5_dir,
        m4_photoreal_link_authority_dir_path=m4_dir,
    )
    assert readback == authority

    with pytest.raises(DigitalTwinPhotorealReleaseError, match="already exists"):
        write_photoreal_release(
            root,
            canonical_m6_release_dir_path=canonical_dir,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance_dir,
            photoreal_m5_link_authority_dir_path=m5_dir,
            m4_photoreal_link_authority_dir_path=m4_dir,
            bodyrig_revision=REVISION,
        )
