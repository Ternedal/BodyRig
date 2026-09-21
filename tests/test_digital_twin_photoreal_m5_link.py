from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_photoreal_m5_link as m5
from bodyrig.digital_twin_photoreal_m5_link import (
    DigitalTwinPhotorealM5LinkError,
    build_photoreal_m5_link,
    read_photoreal_m5_link,
    validate_photoreal_m5_link_structure,
    write_photoreal_m5_link,
)

REVISION = "a" * 40
PERSON_ID = "person-" + "1" * 32
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-" + "2" * 32
PACKAGE_SHA = "3" * 64
ASSEMBLY_SHA = "4" * 64
M4_ID = "dtcomp-" + "5" * 32
M4_PHOTO_LINK_ID = "dtphoto-" + "6" * 32


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _m4_link() -> dict[str, object]:
    return {
        "link_id": M4_PHOTO_LINK_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": REVISION,
        "composition_authority_id": M4_ID,
        "visual_authority": "photoreal-v2-p3",
        "m5_photoreal_integration_eligible": True,
        "production_activation": False,
    }


def _platform_input(platform: str) -> dict[str, object]:
    return {
        "platform": platform,
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "composition_authority_id": M4_ID,
    }


def _realization(platform: str) -> dict[str, object]:
    return {
        "platform": platform,
        "device_model": "Windows Test Rig" if platform == "windows-unity-univrm" else "Meta Quest 2",
    }


def _arrange(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    m4_link: dict[str, object] | None = None,
    ready: bool = True,
) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "persons"
    root.mkdir()
    composition_dir = tmp_path / "composition"
    composition_dir.mkdir()
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()

    link_dir = (
        root
        / "digital-twin-photoreal-links"
        / PERSON_ID
        / PERSON_REVISION
        / M4_PHOTO_LINK_ID
    )
    link_dir.mkdir(parents=True)
    link_value = m4_link or _m4_link()
    (link_dir / "authority.json").write_text(json.dumps(link_value), encoding="utf-8")

    evidence_dirs: dict[str, Path] = {}
    status_platforms: dict[str, dict[str, object]] = {}
    for platform, folder in (
        ("windows-unity-univrm", "windows"),
        ("android-quest-class", "quest"),
    ):
        directory = acceptance / folder
        directory.mkdir()
        platform_input = _platform_input(platform)
        realization = _realization(platform)
        input_raw = json.dumps(platform_input).encode("utf-8")
        realization_raw = json.dumps(realization).encode("utf-8")
        (directory / "platform-input.json").write_bytes(input_raw)
        (directory / "realization.json").write_bytes(realization_raw)
        evidence_dirs[platform] = directory
        status_platforms[platform] = {
            "ready": ready,
            "state": "complete" if ready else "required",
            "realization_sha256": _sha(realization_raw),
            "device_model": realization["device_model"],
        }

    monkeypatch.setattr(
        m5,
        "photoreal_link_dir",
        lambda root_value, person_id, person_revision, link_id: link_dir,
    )
    monkeypatch.setattr(
        m5,
        "read_photoreal_link",
        lambda root_value, **kwargs: dict(link_value),
    )
    monkeypatch.setattr(
        m5,
        "platform_evidence_dir",
        lambda acceptance_value, platform: evidence_dirs[platform],
    )
    monkeypatch.setattr(
        m5,
        "inspect_digital_twin_platform_acceptance",
        lambda **kwargs: {
            "format": "bodyrig-digital-twin-platform-status",
            "version": 1,
            "m5_ready": ready,
            "digital_twin_ready": False,
            "production_activation": False,
            "platforms": status_platforms,
            "blockers": [] if ready else ["fixture"],
        },
    )
    return root, composition_dir, acceptance, link_dir


def test_build_photoreal_m5_link_binds_both_platform_realizations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, acceptance, link_dir = _arrange(monkeypatch, tmp_path)

    authority = build_photoreal_m5_link(
        root,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance,
        photoreal_link_authority_dir_path=link_dir,
        bodyrig_revision=REVISION,
    )

    assert authority["person_id"] == PERSON_ID
    assert authority["m4_photoreal_link_id"] == M4_PHOTO_LINK_ID
    assert authority["windows_device_model"] == "Windows Test Rig"
    assert authority["quest_device_model"] == "Meta Quest 2"
    assert authority["visual_authority"] == "photoreal-v2-p3"
    assert authority["photoreal_m5_ready"] is True
    assert authority["m6_photoreal_release_eligible"] is True
    assert authority["production_activation"] is False


def test_incomplete_existing_m5_cannot_gain_photoreal_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, acceptance, link_dir = _arrange(
        monkeypatch,
        tmp_path,
        ready=False,
    )

    with pytest.raises(
        DigitalTwinPhotorealM5LinkError,
        match="not complete and non-activating",
    ):
        build_photoreal_m5_link(
            root,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance,
            photoreal_link_authority_dir_path=link_dir,
            bodyrig_revision=REVISION,
        )


def test_m5_platform_input_must_match_photoreal_composition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, acceptance, link_dir = _arrange(monkeypatch, tmp_path)
    windows = acceptance / "windows" / "platform-input.json"
    value = json.loads(windows.read_text(encoding="utf-8"))
    value["composition_authority_id"] = "dtcomp-" + "f" * 32
    windows.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(
        DigitalTwinPhotorealM5LinkError,
        match="composition differs from Photoreal authority",
    ):
        build_photoreal_m5_link(
            root,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance,
            photoreal_link_authority_dir_path=link_dir,
            bodyrig_revision=REVISION,
        )


def test_m4_photoreal_link_must_share_exact_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    link_value = _m4_link()
    link_value["bodyrig_revision"] = "b" * 40
    root, composition_dir, acceptance, link_dir = _arrange(
        monkeypatch,
        tmp_path,
        m4_link=link_value,
    )

    with pytest.raises(
        DigitalTwinPhotorealM5LinkError,
        match="same BodyRig revision",
    ):
        build_photoreal_m5_link(
            root,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance,
            photoreal_link_authority_dir_path=link_dir,
            bodyrig_revision=REVISION,
        )


def test_photoreal_m5_structure_is_bool_safe_and_non_activating(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, acceptance, link_dir = _arrange(monkeypatch, tmp_path)
    authority = build_photoreal_m5_link(
        root,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance,
        photoreal_link_authority_dir_path=link_dir,
        bodyrig_revision=REVISION,
    )

    boolean_version = copy.deepcopy(authority)
    boolean_version["version"] = True
    with pytest.raises(DigitalTwinPhotorealM5LinkError, match="format/version/policy"):
        validate_photoreal_m5_link_structure(boolean_version)

    activating = copy.deepcopy(authority)
    activating["production_activation"] = True
    with pytest.raises(DigitalTwinPhotorealM5LinkError, match="cannot activate production"):
        validate_photoreal_m5_link_structure(activating)


def test_photoreal_m5_link_id_detects_resealed_platform_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, acceptance, link_dir = _arrange(monkeypatch, tmp_path)
    authority = build_photoreal_m5_link(
        root,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance,
        photoreal_link_authority_dir_path=link_dir,
        bodyrig_revision=REVISION,
    )
    authority["quest_device_model"] = "Other Quest"

    with pytest.raises(DigitalTwinPhotorealM5LinkError, match="link id no longer matches"):
        validate_photoreal_m5_link_structure(authority)


def test_write_and_readback_are_create_only_and_revalidate_live_m5(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, composition_dir, acceptance, link_dir = _arrange(monkeypatch, tmp_path)

    authority = write_photoreal_m5_link(
        root,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance,
        photoreal_link_authority_dir_path=link_dir,
        bodyrig_revision=REVISION,
    )
    directory = m5.photoreal_m5_link_dir(
        root,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        link_id=authority["link_id"],
    )
    assert (directory / "m4-photoreal-link.json").is_file()
    assert (directory / "windows-platform-input.json").is_file()
    assert (directory / "windows-realization.json").is_file()
    assert (directory / "quest-platform-input.json").is_file()
    assert (directory / "quest-realization.json").is_file()

    readback = read_photoreal_m5_link(
        root,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        link_id=authority["link_id"],
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance,
        photoreal_link_authority_dir_path=link_dir,
    )
    assert readback == authority

    with pytest.raises(DigitalTwinPhotorealM5LinkError, match="already exists"):
        write_photoreal_m5_link(
            root,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance,
            photoreal_link_authority_dir_path=link_dir,
            bodyrig_revision=REVISION,
        )
