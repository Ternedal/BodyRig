from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bodyrig import photoreal_calibration_ui as ui
from bodyrig.stash_source import StashSourceError


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _profile(performer_id: str = "42") -> dict:
    return {
        "person_id": "person-" + ("1" * 32),
        "display_name": "Performer 42",
        "source": {
            "kind": "stash-performer",
            "performer_id": performer_id,
            "performer_name": "Target",
            "disambiguation": "",
        },
    }


def _run(
    root: Path,
    name: str,
    *,
    performer_id: str = "42",
    calibration: bool = True,
    diagnostic: bool = False,
) -> Path:
    run = root / "photoreal-v2" / "overnight" / name
    run.mkdir(parents=True)
    _write_json(
        run / "source-resume-receipt.json",
        {"performer_id": performer_id},
    )
    _write_json(
        run / "identity-bank.json",
        {"performer_id": performer_id},
    )
    _write_json(
        run / "identity-calibration-plan.json",
        {"target_performer_id": performer_id},
    )
    _write_json(
        run
        / "identity-calibration-extractor"
        / "output"
        / "negative-observations.json",
        {"observations": []},
    )
    if calibration:
        _write_json(
            run / "identity-calibration.json",
            {
                "format": "bodyrig-photoreal-identity-calibration",
                "version": 1,
                "target_performer_id": performer_id,
                "identity_matching_authorized": False,
                "match_threshold_calibrated": False,
                "match_threshold": None,
                "observed_separation_margin": -0.202397704,
                "minimum_required_separation_margin": 0.05,
                "positive_reference_count": 4,
                "positive_group_count": 2,
                "negative_observation_count": 21,
                "negative_performer_count": 4,
                "negative_to_target_centroid_cosine_max": 0.91,
                "positive_leave_group_out_cosine_min": 0.707602296,
                "calibration_blockers": [
                    "observed positive/negative cosine separation "
                    "-0.202398 is below required 0.050000"
                ],
            },
        )
    if diagnostic:
        _write_json(
            run / "identity-calibration-diagnostic.json",
            {
                "format":
                    "bodyrig-photoreal-identity-calibration-diagnostic",
                "version": 1,
                "target_performer_id": performer_id,
                "highest_negative_match": {
                    "subject_performer_id": "7",
                    "subject_performer_name": "Negative",
                    "cosine": 0.91,
                    "resolved_path": r"C:\negative\p7.mp4",
                    "timestamp_seconds": 30.0,
                    "quality_metadata_complete": True,
                    "quality_metadata": {
                        "candidate_id": "person-000",
                        "candidate_count": 1,
                        "person_detected": True,
                        "width": 1920,
                        "height": 1080,
                        "view_bin": "front",
                        "face_visibility": 0.9,
                        "full_body_visibility": 0.8,
                        "person_fraction": 0.25,
                        "sharpness": 0.7,
                        "motion": 0.0,
                        "occlusion": 0.1,
                        "identity_measurement_status": "available",
                        "identity_measurement_reason": "embedding-available",
                    },
                    "closest_positive_group": {
                        "group_id": "a",
                        "cosine": 0.95,
                    },
                    "closest_positive_group_margin": 0.1,
                    "closest_positive_reference": {
                        "group_id": "a",
                        "source_key": "target-a",
                        "cosine": 0.96,
                    },
                },
                "negative_observation_count": 21,
                "negative_observation_quality_metadata": {
                    "complete_quality_audit_available": False,
                    "complete_observation_count": 0,
                    "missing_fields": ["sharpness"],
                },
                "diagnostic_only": True,
                "identity_matching_authority": False,
                "teacher_training_authorized": False,
                "photoreal_acceptance_authority": False,
                "production_activation": False,
            },
        )
    return run


class _Stash:
    def __init__(self, media_path: Path) -> None:
        self.media_path = media_path

    def version(self) -> str:
        return "v0.31.1"

    def performer(self, performer_id: str) -> dict[str, str]:
        return {
            "id": performer_id,
            "name": "Target from Stash",
            "disambiguation": "context",
        }

    def scenes_for_performer(
        self,
        performer_id: str,
        *,
        limit: int = 200,
    ) -> list[dict]:
        del limit
        return [
            {
                "id": "scene-1",
                "title": "Solo source",
                "performers": [
                    {"id": performer_id, "name": "Target from Stash"}
                ],
                "tags": [],
                "files": [
                    {
                        "path": str(self.media_path),
                        "width": 3840,
                        "height": 2160,
                        "duration": 120.0,
                        "frame_rate": 30.0,
                    }
                ],
            },
            {
                "id": "scene-2",
                "title": "Multi source",
                "performers": [
                    {"id": performer_id, "name": "Target from Stash"},
                    {"id": "other", "name": "Other"},
                ],
                "tags": [],
                "files": [],
            },
        ]


class _BrokenStash(_Stash):
    def version(self) -> str:
        raise StashSourceError("stash unavailable")


def test_latest_run_uses_artifact_performer_binding(
    tmp_path: Path,
) -> None:
    correct = _run(
        tmp_path,
        "performer-42-20260918-072820-resume4",
        performer_id="42",
    )
    _run(
        tmp_path,
        "performer-42-20260918-080000-resume4",
        performer_id="99",
    )

    found = ui.find_latest_performer_run(tmp_path, "42")

    assert found == correct


def test_performer_run_history_is_bounded_and_artifact_bound(
    tmp_path: Path,
) -> None:
    older = _run(
        tmp_path,
        "performer-42-20260918-070000-resume1",
        performer_id="42",
    )
    newer = _run(
        tmp_path,
        "performer-42-20260918-080000-resume2",
        performer_id="42",
    )
    rejected = _run(
        tmp_path,
        "performer-42-20260918-090000-resume3",
        performer_id="99",
    )
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    os.utime(rejected, (3000, 3000))

    runs = ui.list_performer_runs(tmp_path, "42", limit=2)

    assert runs == [newer, older]
    assert rejected not in runs
    assert ui.find_latest_performer_run(tmp_path, "42") == newer
    assert ui.list_performer_runs(tmp_path, "42", limit=0) == []


def test_status_combines_stage13_diagnostic_and_stash_context(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media.mp4"
    media.write_bytes(b"x")
    run = _run(
        tmp_path,
        "performer-42-20260918-072820-resume4",
        diagnostic=True,
    )

    value = ui.inspect_person_calibration(
        _profile(),
        tmp_path,
        stash_client=_Stash(media),
    )

    assert value["state"] == "diagnosed"
    assert value["run"]["path"] == str(run)
    assert value["run"]["stage13"]["state"] == "blocked"
    assert (
        value["run"]["stage13"]["observed_separation_margin"]
        == -0.202397704
    )
    assert value["run"]["diagnostic_available"] is True
    assert (
        value["run"]["diagnostic"]["highest_negative_match"]
        ["resolved_path"]
        == r"C:\negative\p7.mp4"
    )
    assert (
        value["run"]["diagnostic"]["highest_negative_match"]
        ["quality_metadata"]["sharpness"]
        == 0.7
    )
    assert (
        value["run"]["diagnostic"]["highest_negative_match"]
        ["quality_metadata_complete"]
        is True
    )
    assert value["stash"]["available"] is True
    assert value["stash"]["version"] == "v0.31.1"
    assert value["stash"]["scene_count_observed"] == 2
    assert value["stash"]["single_performer_scene_count"] == 1
    assert value["stash"]["multi_performer_scene_count"] == 1
    assert len(value["stash"]["top_local_sources"]) == 1
    assert value["authority"]["diagnostic_only"] is True
    assert value["authority"]["identity_matching_authority"] is False
    assert value["authority"]["production_activation"] is False


def test_stash_failure_does_not_hide_local_calibration(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media.mp4"
    media.write_bytes(b"x")
    _run(
        tmp_path,
        "performer-42-20260918-072820-resume4",
        diagnostic=True,
    )

    value = ui.inspect_person_calibration(
        _profile(),
        tmp_path,
        stash_client=_BrokenStash(media),
    )

    assert value["state"] == "diagnosed"
    assert value["run"]["stage13"]["state"] == "blocked"
    assert value["stash"]["available"] is False
    assert "stash unavailable" in value["stash"]["reason"]


def test_unbound_person_is_fail_closed_without_run_lookup(
    tmp_path: Path,
) -> None:
    profile = _profile()
    profile["source"] = None

    value = ui.inspect_person_calibration(profile, tmp_path)

    assert value["state"] == "unbound"
    assert value["run"] is None
    assert value["authority"]["production_activation"] is False


def test_run_diagnostic_reuses_existing_non_authoritative_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _run(
        tmp_path,
        "performer-42-20260918-072820-resume4",
        diagnostic=True,
    )

    def _unexpected(*args, **kwargs):
        raise AssertionError("existing diagnostic must not be overwritten")

    monkeypatch.setattr(
        ui,
        "build_identity_calibration_diagnostic_files",
        _unexpected,
    )

    value = ui.run_person_calibration_diagnostic(
        _profile(),
        tmp_path,
    )

    assert value["state"] == "diagnosed"
    assert value["run"]["diagnostic_available"] is True
    assert (
        value["run"]["diagnostic"]["production_activation"]
        is False
    )


def test_run_diagnostic_materializes_missing_artifact_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        "performer-42-20260918-072820-resume4",
        diagnostic=False,
    )
    calls: list[Path] = []

    def _fake_build(bank, plan, negatives, output, *, top_matches):
        del bank, plan, negatives
        calls.append(Path(output))
        assert top_matches == 10
        value = {
            "format":
                "bodyrig-photoreal-identity-calibration-diagnostic",
            "version": 1,
            "target_performer_id": "42",
            "highest_negative_match": {},
            "negative_observation_quality_metadata": {},
            "diagnostic_only": True,
            "identity_matching_authority": False,
            "teacher_training_authorized": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        _write_json(Path(output), value)
        return value

    monkeypatch.setattr(
        ui,
        "build_identity_calibration_diagnostic_files",
        _fake_build,
    )

    value = ui.run_person_calibration_diagnostic(
        _profile(),
        tmp_path,
    )

    assert calls == [
        run / "identity-calibration-diagnostic.json"
    ]
    assert value["run"]["diagnostic_available"] is True

def test_run_candidate_audit_surfaces_mismatch_and_conflicting_identity(
    tmp_path: Path,
) -> None:
    valid = _run(
        tmp_path,
        "performer-42-20260918-072820-resume4",
        performer_id="42",
    )
    mismatch = _run(
        tmp_path,
        "performer-42-20260918-082820-resume5",
        performer_id="99",
    )
    conflict = _run(
        tmp_path,
        "performer-42-20260918-092820-resume6",
        performer_id="42",
    )
    _write_json(
        conflict / "p0-status.json",
        {"performer_id": "99"},
    )
    os.utime(valid, (1000, 1000))
    os.utime(mismatch, (2000, 2000))
    os.utime(conflict, (3000, 3000))

    candidates = ui.inspect_performer_run_candidates(tmp_path, "42", limit=8)

    assert [item["name"] for item in candidates] == [
        conflict.name,
        mismatch.name,
        valid.name,
    ]
    assert candidates[0]["valid"] is False
    assert "conflicting performer declarations" in candidates[0]["rejection_reason"]
    assert candidates[1]["valid"] is False
    assert "does not match expected" in candidates[1]["rejection_reason"]
    assert candidates[2]["valid"] is True
    assert candidates[2]["rejection_reason"] is None


def test_run_candidate_audit_never_trusts_symlinked_run_root(
    tmp_path: Path,
) -> None:
    overnight = tmp_path / "photoreal-v2" / "overnight"
    external = tmp_path / "external-run"
    external.mkdir(parents=True)
    _write_json(external / "source-resume-receipt.json", {"performer_id": "42"})
    link = overnight / "performer-42-20260918-102820-resume7"
    overnight.mkdir(parents=True)
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this CI host")

    candidates = ui.inspect_performer_run_candidates(tmp_path, "42", limit=8)

    assert len(candidates) == 1
    assert candidates[0]["valid"] is False
    assert candidates[0]["rejection_reason"] == "run path is symlinked"
    assert candidates[0]["path"] == str(link.absolute())

