import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_hfn_migration as migration


PREVIEW = "hfpreview-" + "1" * 32
PERSON = "person-" + "2" * 32
SOURCE_REV = "a" * 40
INTEGRATION_REV = "b" * 40
PACKAGE_SHA = ""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install(tmp_path: Path, monkeypatch, *, complete: bool = True):
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-promoted-package")
    package_sha = _sha(package)
    monkeypatch.setattr(migration, "ui_jobs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        migration.preview_manager,
        "get",
        lambda _job: {
            "job_id": PREVIEW,
            "status": "succeeded",
            "person_id": PERSON,
            "body_revision": "body-r0001",
            "canonical_body_id": "bodyid-test",
            "bodyrig_revision": SOURCE_REV,
        },
    )
    monkeypatch.setattr(
        migration.legacy_status,
        "inspect_continuation",
        lambda _job: {
            "high_fidelity_complete": complete,
            "current_package_path": str(package),
            "current_package_sha256": package_sha,
        },
    )
    return package, package_sha


def test_prepare_migration_binds_exact_legacy_package_and_current_revision(tmp_path: Path, monkeypatch) -> None:
    _package, package_sha = _install(tmp_path, monkeypatch)

    result = migration.prepare_migration(PREVIEW, integration_bodyrig_revision=INTEGRATION_REV)

    assert result["source_bodyrig_revision"] == SOURCE_REV
    assert result["integration_bodyrig_revision"] == INTEGRATION_REV
    assert result["source_package_sha256"] == package_sha
    assert result["comparison_only"] is True
    assert result["human_review_required"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert Path(result["path"]).is_file()


def test_migration_refuses_legacy_incomplete_preview(tmp_path: Path, monkeypatch) -> None:
    _install(tmp_path, monkeypatch, complete=False)

    with pytest.raises(migration.HighFidelityHfnMigrationError, match="legacy.*complete|historical.*complete"):
        migration.prepare_migration(PREVIEW, integration_bodyrig_revision=INTEGRATION_REV)


def test_migration_is_create_only_across_integration_revisions(tmp_path: Path, monkeypatch) -> None:
    _install(tmp_path, monkeypatch)
    migration.prepare_migration(PREVIEW, integration_bodyrig_revision=INTEGRATION_REV)

    with pytest.raises(migration.HighFidelityHfnMigrationError, match="create-only"):
        migration.prepare_migration(PREVIEW, integration_bodyrig_revision="c" * 40)


def test_read_migration_rejects_boolean_v1(tmp_path: Path, monkeypatch) -> None:
    _package, package_sha = _install(tmp_path, monkeypatch)
    result = migration.prepare_migration(PREVIEW, integration_bodyrig_revision=INTEGRATION_REV)
    path = Path(result["path"])
    value = json.loads(path.read_text(encoding="utf-8"))
    value["version"] = True
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    with pytest.raises(migration.HighFidelityHfnMigrationError, match="format/version"):
        migration.read_migration(
            PREVIEW,
            source_bodyrig_revision=SOURCE_REV,
            source_package_sha256=package_sha,
        )


def test_migration_refuses_source_package_tamper(tmp_path: Path, monkeypatch) -> None:
    package, _package_sha = _install(tmp_path, monkeypatch)
    package.write_bytes(b"tampered")

    with pytest.raises(migration.HighFidelityHfnMigrationError, match="package bytes"):
        migration.prepare_migration(PREVIEW, integration_bodyrig_revision=INTEGRATION_REV)
