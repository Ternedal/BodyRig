from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.automatic_run_discovery as discovery
from bodyrig.acceptance_status import AcceptanceStatus


REV = "a" * 40


def write_authority(run_root: Path, *, performer: str = "42", body: str = "body-a", activation: bool = False) -> Path:
    run_root.mkdir(parents=True)
    clone_output = run_root / "clone-output"
    value = {
        "format": "bodyrig-one-command-production-authority",
        "version": 1,
        "started_at": "2026-09-07T12:00:00Z",
        "bodyrig_revision": REV,
        "performer_id": performer,
        "requested_body_alias": body,
        "session_report": str(run_root / "bodyrig-physical-clone-session.json"),
        "clone_output": str(clone_output),
        "acceptance_dir": str(clone_output / "acceptance"),
        "production_activation": activation,
    }
    path = run_root / "run-authority.json"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


def test_run_authority_requires_exact_canonical_layout(tmp_path: Path) -> None:
    run = tmp_path / "run"
    authority = write_authority(run)
    value = json.loads(authority.read_text(encoding="utf-8"))
    value["acceptance_dir"] = str(tmp_path / "other" / "acceptance")
    authority.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(discovery.AutomaticRunDiscoveryError, match="canonical path"):
        discovery.inspect_run_authority(run)


def test_run_authority_activation_flag_is_informational_only(tmp_path: Path) -> None:
    run = tmp_path / "run"
    write_authority(run, activation=True)
    value = discovery.inspect_run_authority(run)
    assert value["declared_production_activation"] is True
    assert "rank" not in value
    assert "state" not in value


def test_candidate_requires_real_session_not_run_flag(tmp_path: Path) -> None:
    run = tmp_path / "run"
    write_authority(run, activation=True)
    value = discovery.inspect_run_authority(run)
    assert discovery.candidate_from_run(value) is None


def test_candidate_uses_structural_acceptance_rank_after_strict_session(tmp_path: Path, monkeypatch) -> None:
    run = tmp_path / "run"
    write_authority(run)
    session_path = run / "bodyrig-physical-clone-session.json"
    session_path.write_text("{}\n", encoding="utf-8")
    acceptance = run / "clone-output" / "acceptance"
    acceptance.mkdir(parents=True)
    (acceptance / "bodyrig-acceptance.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        discovery,
        "_session_status",
        lambda _path: AcceptanceStatus(
            state="ready", gate="gate-a", acceptance_dir=str(acceptance), body_id="body-a",
            bodyrig_revision=REV, message="fixture", next_command="fixture",
        ),
    )
    monkeypatch.setattr(
        discovery,
        "inspect_for_rig_window",
        lambda _path: {
            "state": "ready",
            "gate": "automatic-quest-quality",
            "bodyrig_revision": REV,
            "progress_rank": 50,
        },
    )
    candidate = discovery.candidate_from_run(discovery.inspect_run_authority(run))
    assert candidate is not None
    assert candidate["rank"] == 50
    assert candidate["gate"] == "automatic-quest-quality"
    assert candidate["automatic_run_root"] == str(run.resolve())


def test_candidate_rejects_session_revision_mismatch(tmp_path: Path, monkeypatch) -> None:
    run = tmp_path / "run"
    write_authority(run)
    session_path = run / "bodyrig-physical-clone-session.json"
    session_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        discovery,
        "_session_status",
        lambda _path: AcceptanceStatus(
            state="ready", gate="gate-a", acceptance_dir=None, body_id="body-a",
            bodyrig_revision="b" * 40, message="fixture", next_command="fixture",
        ),
    )
    with pytest.raises(discovery.AutomaticRunDiscoveryError, match="session revision"):
        discovery.candidate_from_run(discovery.inspect_run_authority(run))


def test_discovery_ignores_directories_without_run_authority(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "automatic-production"
    (parent / "noise").mkdir(parents=True)
    run = parent / "valid"
    write_authority(run)
    monkeypatch.setattr(discovery, "default_run_roots", lambda _root: (parent,))
    rows, rejected = discovery.discover_run_authorities(tmp_path)
    assert rejected == []
    assert [Path(row["run_root"]).name for row in rows] == ["valid"]
