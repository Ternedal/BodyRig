from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_person_binding as binding
from bodyrig.photoreal_person_binding import (
    PhotorealPersonBindingError,
    build_photoreal_person_binding,
    validate_photoreal_person_binding_structure,
    write_photoreal_person_binding,
)

REVISION = "a" * 40
PERSON_ID = "person-" + "1" * 32
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-" + "2" * 32
PACKAGE_SHA = "3" * 64
ASSEMBLY_SHA = "4" * 64
P3_DECLARED_SHA = "5" * 64
TEACHER_SHA = "6" * 64
PLAN_SHA = "7" * 64
SOURCE_EVIDENCE_SHA = "8" * 64


def _profile() -> dict[str, object]:
    return {
        "person_id": PERSON_ID,
        "source": {
            "kind": "stash-performer",
            "performer_id": "42",
            "performer_name": "Performer 42",
            "disambiguation": "",
        },
        "active_person_revision": PERSON_REVISION,
        "body_revisions": [
            {
                "revision_id": BODY_REVISION,
                "body_id": BODY_ID,
                "package_sha256": PACKAGE_SHA,
            }
        ],
        "person_revisions": [
            {
                "revision_id": PERSON_REVISION,
                "body_revision": BODY_REVISION,
                "voice_revision": "voice-r0001",
                "personality_revision": "personality-r0001",
            }
        ],
    }


def _p3(*, performer_id: str = "42", status: str = "pass") -> dict[str, object]:
    passed = status == "pass"
    return {
        "performer_id": performer_id,
        "selected_epoch_id": "epoch-human-a",
        "teacher_input_sha256": TEACHER_SHA,
        "p3_device_runtime_review_plan_sha256": PLAN_SHA,
        "p3_physical_runtime_review_sha256": P3_DECLARED_SHA,
        "target_device_family": "meta-quest",
        "target_device_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "runtime_review_status": status,
        "runtime_acceptance_authority": passed,
        "photoreal_acceptance_authority": passed,
        "production_activation": False,
    }


def _arrange(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    p3: dict[str, object] | None = None,
) -> tuple[Path, Path, Path, Path]:
    library = tmp_path / "persons"
    library.mkdir()
    assembly = tmp_path / "assembly.json"
    release = tmp_path / "release.json"
    p3_path = tmp_path / "p3.json"
    source_binding = tmp_path / "source-binding.json"
    assembly.write_text(json.dumps({"fixture": "assembly"}), encoding="utf-8")
    release.write_text(json.dumps({"fixture": "release"}), encoding="utf-8")
    p3_path.write_text(json.dumps(p3 or _p3()), encoding="utf-8")
    source_binding.write_text(json.dumps({"fixture": "binding"}), encoding="utf-8")

    profile = _profile()
    monkeypatch.setattr(binding, "load_profile", lambda root, person_id: profile)
    monkeypatch.setattr(
        binding,
        "_assembly_identity",
        lambda value: {
            "person_id": PERSON_ID,
            "person_revision": PERSON_REVISION,
            "assembly_fingerprint": ASSEMBLY_SHA,
            "body_revision": BODY_REVISION,
            "body_id": BODY_ID,
        },
    )
    monkeypatch.setattr(
        binding,
        "_release_identity",
        lambda value, assembly_identity: {"package_sha256": PACKAGE_SHA},
    )
    monkeypatch.setattr(
        binding,
        "read_binding",
        lambda root, profile_value, kind, revision_id: {
            "evidence": {"sha256": SOURCE_EVIDENCE_SHA}
        },
    )
    monkeypatch.setattr(
        binding,
        "binding_path",
        lambda root, person_id, kind, revision_id: source_binding,
    )
    monkeypatch.setattr(
        binding,
        "validate_physical_runtime_review_receipt",
        lambda value: dict(value),
    )
    return library, assembly, release, p3_path


def test_passed_p3_binds_to_exact_person_source_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library, assembly, release, p3_path = _arrange(monkeypatch, tmp_path)

    authority = build_photoreal_person_binding(
        library,
        person_id=PERSON_ID,
        assembly_receipt_path=assembly,
        body_release_status_path=release,
        p3_physical_runtime_review_path=p3_path,
        bodyrig_revision=REVISION,
    )

    assert authority["person_id"] == PERSON_ID
    assert authority["person_revision"] == PERSON_REVISION
    assert authority["body_revision"] == BODY_REVISION
    assert authority["body_id"] == BODY_ID
    assert authority["body_package_sha256"] == PACKAGE_SHA
    assert authority["stash_performer_id"] == "42"
    assert authority["photoreal_binding_authority"] is True
    assert authority["m4_photoreal_integration_eligible"] is True
    assert authority["production_activation"] is False
    assert authority["binding_id"].startswith("photoperson-")


def test_different_p3_performer_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library, assembly, release, p3_path = _arrange(
        monkeypatch,
        tmp_path,
        p3=_p3(performer_id="55"),
    )

    with pytest.raises(
        PhotorealPersonBindingError,
        match="different Stash performer",
    ):
        build_photoreal_person_binding(
            library,
            person_id=PERSON_ID,
            assembly_receipt_path=assembly,
            body_release_status_path=release,
            p3_physical_runtime_review_path=p3_path,
            bodyrig_revision=REVISION,
        )


def test_failed_p3_cannot_create_person_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library, assembly, release, p3_path = _arrange(
        monkeypatch,
        tmp_path,
        p3=_p3(status="fail"),
    )

    with pytest.raises(
        PhotorealPersonBindingError,
        match="not an explicit all-PASS",
    ):
        build_photoreal_person_binding(
            library,
            person_id=PERSON_ID,
            assembly_receipt_path=assembly,
            body_release_status_path=release,
            p3_physical_runtime_review_path=p3_path,
            bodyrig_revision=REVISION,
        )


def test_body_source_alignment_is_mandatory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library, assembly, release, p3_path = _arrange(monkeypatch, tmp_path)

    def fail_alignment(*args, **kwargs):
        raise binding.PersonSourceAlignmentError("fixture source drift")

    monkeypatch.setattr(binding, "read_binding", fail_alignment)
    with pytest.raises(
        PhotorealPersonBindingError,
        match="body source alignment is invalid",
    ):
        build_photoreal_person_binding(
            library,
            person_id=PERSON_ID,
            assembly_receipt_path=assembly,
            body_release_status_path=release,
            p3_physical_runtime_review_path=p3_path,
            bodyrig_revision=REVISION,
        )


def test_binding_id_detects_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library, assembly, release, p3_path = _arrange(monkeypatch, tmp_path)
    authority = build_photoreal_person_binding(
        library,
        person_id=PERSON_ID,
        assembly_receipt_path=assembly,
        body_release_status_path=release,
        p3_physical_runtime_review_path=p3_path,
        bodyrig_revision=REVISION,
    )
    tampered = copy.deepcopy(authority)
    tampered["selected_epoch_id"] = "epoch-tampered"

    with pytest.raises(
        PhotorealPersonBindingError,
        match="binding id no longer matches",
    ):
        validate_photoreal_person_binding_structure(tampered)


def test_binding_version_true_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library, assembly, release, p3_path = _arrange(monkeypatch, tmp_path)
    authority = build_photoreal_person_binding(
        library,
        person_id=PERSON_ID,
        assembly_receipt_path=assembly,
        body_release_status_path=release,
        p3_physical_runtime_review_path=p3_path,
        bodyrig_revision=REVISION,
    )
    authority["version"] = True

    with pytest.raises(
        PhotorealPersonBindingError,
        match="format/version mismatch",
    ):
        validate_photoreal_person_binding_structure(authority)


def test_binding_output_is_create_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library, assembly, release, p3_path = _arrange(monkeypatch, tmp_path)
    output = tmp_path / "photoreal-person-binding.json"

    first = write_photoreal_person_binding(
        output,
        person_library=library,
        person_id=PERSON_ID,
        assembly_receipt_path=assembly,
        body_release_status_path=release,
        p3_physical_runtime_review_path=p3_path,
        bodyrig_revision=REVISION,
    )
    assert output.is_file()
    assert first["production_activation"] is False

    with pytest.raises(
        PhotorealPersonBindingError,
        match="already exists",
    ):
        write_photoreal_person_binding(
            output,
            person_library=library,
            person_id=PERSON_ID,
            assembly_receipt_path=assembly,
            body_release_status_path=release,
            p3_physical_runtime_review_path=p3_path,
            bodyrig_revision=REVISION,
        )
