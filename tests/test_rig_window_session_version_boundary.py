from __future__ import annotations

import json
from pathlib import Path

import bodyrig.rig_window_plan as plan
import bodyrig.rig_window_policy as policy

REVISION = "a" * 40


def _write_session(root: Path, name: str, *, version: object, performer: str, body: str, stamp: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "format": "bodyrig-physical-clone-session",
                "version": version,
                "status": "pass",
                "stage": "complete",
                "bodyrig_revision": REVISION,
                "performer_id": performer,
                "body_id": body,
                "completed_utc": stamp,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_completed_session_discovery_rejects_bool_and_preserves_numeric_float(monkeypatch, tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    valid = _write_session(
        sessions, "valid", version=1.0, performer="performer-a", body="body-a", stamp="2026-09-12T18:00:00Z"
    )
    _write_session(
        sessions, "bool-decoy", version=True, performer="performer-b", body="body-b", stamp="2026-09-12T19:00:00Z"
    )
    monkeypatch.setattr(plan, "_session_roots", lambda _root: (sessions,))

    rows = plan._completed_sessions(tmp_path, revision=REVISION)

    assert rows == [
        {
            "path": str(valid.resolve()),
            "stamp": "2026-09-12T18:00:00Z",
            "performer_id": "performer-a",
            "body_id": "body-a",
        }
    ]


def test_bool_decoy_cannot_poison_policy_scope_or_create_performer_ambiguity(monkeypatch, tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    valid = _write_session(
        sessions, "valid", version=1.0, performer="performer-a", body="body-a", stamp="2026-09-12T18:00:00Z"
    )
    _write_session(
        sessions, "bool-decoy", version=True, performer="performer-b", body="body-b", stamp="2026-09-12T19:00:00Z"
    )
    monkeypatch.setattr(plan, "_session_roots", lambda _root: (sessions,))

    rows = policy._scope_sessions(
        tmp_path, performer_id="", resolved_performer="", body_id=""
    )

    assert len(rows) == 1
    assert rows[0]["path"] == str(valid.resolve())
    assert rows[0]["performer_id"] == "performer-a"
    assert rows[0]["body_id"] == "body-a"
    assert rows[0]["revision"] == REVISION
