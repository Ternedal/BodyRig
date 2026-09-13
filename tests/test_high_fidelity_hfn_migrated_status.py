import hashlib
from pathlib import Path

import bodyrig.high_fidelity_hfn_migrated_status as migrated


PREVIEW = "hfpreview-" + "1" * 32
PERSON = "person-" + "2" * 32
SOURCE_REV = "a" * 40
INTEGRATION_REV = "b" * 40


def _source(tmp_path: Path):
    package = tmp_path / "legacy-promoted.mrbody"
    package.write_bytes(b"legacy-promoted")
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    return package, sha


def _install_base(monkeypatch, tmp_path: Path, *, complete: bool = True):
    package, sha = _source(tmp_path)
    monkeypatch.setattr(
        migrated.current._legacy,
        "inspect_continuation",
        lambda _job: {
            "format": "bodyrig-high-fidelity-continuation-status",
            "version": 1,
            "preview_job_id": PREVIEW,
            "state": "complete" if complete else "incomplete",
            "gates": [],
            "next_gate": None,
            "current_package_path": str(package),
            "current_package_sha256": sha,
            "components": {"hair": "complete"},
            "high_fidelity_complete": complete,
            "production_ready": False,
            "production_activation": False,
        },
    )
    monkeypatch.setattr(migrated.current._legacy, "_job", lambda value: value)
    monkeypatch.setattr(
        migrated.current._legacy.preview_manager,
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
        migrated.current,
        "continuation_paths",
        lambda _job: {
            "face_promotion": tmp_path / "face",
            "hfn_render": tmp_path / "hfn-render",
            "hfn_review": tmp_path / "hfn-review",
        },
    )
    return package, sha


def test_legacy_incomplete_never_exposes_migration(monkeypatch, tmp_path: Path) -> None:
    _install_base(monkeypatch, tmp_path, complete=False)

    result = migrated.inspect_migrated_continuation(PREVIEW)

    assert result["high_fidelity_complete"] is False
    assert "hfn_migration_active" not in result


def test_legacy_complete_requires_explicit_migration(monkeypatch, tmp_path: Path) -> None:
    _package, sha = _install_base(monkeypatch, tmp_path)
    monkeypatch.setattr(migrated, "read_migration", lambda *_args, **_kwargs: None)

    result = migrated.inspect_migrated_continuation(PREVIEW)

    assert result["high_fidelity_complete"] is False
    assert result["hfn_migration_active"] is False
    assert result["legacy_bodyrig_revision"] == SOURCE_REV
    assert result["current_package_sha256"] == sha
    assert "prepare-high-fidelity-hfn-migration.ps1" in result["next_gate"]["command"]


def test_migration_revision_is_used_only_for_hfn_layer(monkeypatch, tmp_path: Path) -> None:
    package, sha = _install_base(monkeypatch, tmp_path)
    monkeypatch.setattr(
        migrated,
        "read_migration",
        lambda *_args, **_kwargs: {
            "integration_bodyrig_revision": INTEGRATION_REV,
            "sha256": "c" * 64,
        },
    )
    seen = {}

    def inspect_hfn(**kwargs):
        seen.update(kwargs)
        return {
            "gates": [
                {
                    "id": migrated.current.CANDIDATE_GATE,
                    "state": "required",
                    "reason": "candidate missing",
                    "evidence": {},
                }
            ],
            "actions": {
                migrated.current.CANDIDATE_GATE: {
                    "gate": migrated.current.CANDIDATE_GATE,
                    "command": ".\\prepare-hands-feet-nails-detail-candidate.ps1",
                    "operator_input_required": True,
                    "reason": "candidate missing",
                }
            },
            "package_path": package,
            "package_sha256": sha,
        }

    monkeypatch.setattr(migrated.current, "inspect_hfn_continuation", inspect_hfn)

    result = migrated.inspect_migrated_continuation(PREVIEW)

    assert seen["bodyrig_revision"] == INTEGRATION_REV
    assert seen["source_package_path"] == package.resolve()
    assert seen["source_package_sha256"] == sha
    assert result["legacy_bodyrig_revision"] == SOURCE_REV
    assert result["hfn_bodyrig_revision"] == INTEGRATION_REV
    assert result["hfn_migration_active"] is True
    assert result["next_gate"]["gate"] == migrated.current.CANDIDATE_GATE


def test_invalid_migration_fails_closed(monkeypatch, tmp_path: Path) -> None:
    _install_base(monkeypatch, tmp_path)

    def fail(*_args, **_kwargs):
        raise migrated.HighFidelityHfnMigrationError("tampered migration")

    monkeypatch.setattr(migrated, "read_migration", fail)

    result = migrated.inspect_migrated_continuation(PREVIEW)

    assert result["state"] == "blocked"
    assert result["next_gate"]["command"] is None
    assert "tampered migration" in result["next_gate"]["reason"]
