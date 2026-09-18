from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_frame_index import PhotorealFrameIndexError, build_frame_index

MODEL_SET_SHA = "c" * 64
BANK_SHA = "d" * 64
CALIBRATION_SHA = "e" * 64


def _source(key: str, group: str, kind: str = "video") -> dict[str, object]:
    return {
        "kind": kind,
        "source_id": key,
        "group_id": group,
        "path": key.split(":", 2)[-1],
        "information_score": 100.0,
    }


def _plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [_source("scene:s-train:E:/train.mp4", "scene:s-train")],
        "evaluation": [
            _source("scene:s-eval-front:E:/eval-front.mp4", "scene:s-eval-front"),
            _source("scene:s-eval-34:E:/eval-34.mp4", "scene:s-eval-34"),
            _source("scene:s-eval-profile:E:/eval-profile.mp4", "scene:s-eval-profile"),
        ],
        "held_out_view_coverage_required": [
            "face-front",
            "face-three-quarter",
            "face-profile",
            "full-body-front",
            "full-body-three-quarter",
        ],
        "rear_view_required_when_source_observable": True,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt(plan: dict[str, object]) -> dict[str, object]:
    sources = []
    for split in ("train", "evaluation"):
        for item in plan[split]:
            key = str(item["source_id"])
            sources.append(
                {
                    "kind": item["kind"],
                    "source_id": key.split(":", 2)[1],
                    "source_key": key,
                    "sha256": ("a" if split == "train" else "b") * 64,
                }
            )
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "sources": sources,
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _observation(
    source_key: str,
    source_sha: str,
    *,
    timestamp: float,
    view: str,
    face: float,
    body: float,
    phash: str,
    verified: bool = True,
    candidate_id: str = "person-0",
    candidate_count: int = 1,
    ambiguous: bool = False,
) -> dict[str, object]:
    return {
        "source_key": source_key,
        "source_sha256": source_sha,
        "kind": "video",
        "timestamp_seconds": timestamp,
        "eye": "mono",
        "projection": "flat",
        "frame_sha256": (hex(int(timestamp * 1000) + 1)[2:][-1] or "1") * 64,
        "perceptual_hash": phash,
        "candidate_id": candidate_id,
        "person_detected": True,
        "measured_person_candidate_count": candidate_count,
        "identity_sample_ambiguous": ambiguous,
        "width": 3840,
        "height": 2160,
        "view_bin": view,
        "face_visibility": face,
        "full_body_visibility": body,
        "person_fraction": 0.7,
        "sharpness": 0.9,
        "motion": 0.1,
        "occlusion": 0.05,
        "identity_measurement_status": "available",
        "identity_similarity": 0.95 if verified else 0.2,
        "identity_authority": "calibrated-identity-bank-v1" if verified else "identity-unresolved-v1",
        "target_identity_verified": verified,
    }


def _observations(plan: dict[str, object], receipt: dict[str, object]) -> dict[str, object]:
    sha = {item["source_key"]: item["sha256"] for item in receipt["sources"]}
    train_key = str(plan["train"][0]["source_id"])
    front_key = str(plan["evaluation"][0]["source_id"])
    q34_key = str(plan["evaluation"][1]["source_id"])
    profile_key = str(plan["evaluation"][2]["source_id"])
    return {
        "format": "bodyrig-photoreal-frame-authorized-observations",
        "version": 1,
        "performer_id": "42",
        "analyzer": "synthetic-photoreal-frame-analyzer",
        "analyzer_revision": "test-v1",
        "analyzer_model_set_sha256": MODEL_SET_SHA,
        "identity_bank_sha256": BANK_SHA,
        "identity_calibration_sha256": CALIBRATION_SHA,
        "identity_matching_calibrated": True,
        "identity_match_threshold": 0.8,
        "identity_ambiguous_sample_count": 0,
        "observations": [
            _observation(train_key, sha[train_key], timestamp=1.0, view="front", face=0.9, body=0.9, phash="0000000000000000"),
            _observation(front_key, sha[front_key], timestamp=2.0, view="front", face=0.9, body=0.9, phash="1111111111111111"),
            _observation(q34_key, sha[q34_key], timestamp=3.0, view="three-quarter-left", face=0.9, body=0.9, phash="3333333333333333"),
            _observation(profile_key, sha[profile_key], timestamp=4.0, view="profile-right", face=0.9, body=0.2, phash="7777777777777777"),
        ],
        "identity_authority_is_core_derived": True,
        "multi_candidate_identity_safe": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }


def test_frame_index_authorizes_training_only_after_held_out_coverage() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    result = build_frame_index(plan, receipt, _observations(plan, receipt))
    assert result["teacher_training_authorized"] is True
    assert result["multi_candidate_identity_safe"] is True
    assert result["identity_ambiguous_sample_count"] == 0
    assert result["cross_split_near_duplicate_count"] == 0
    assert result["held_out_view_coverage_missing"] == []
    assert result["photoreal_acceptance_authority"] is False
    assert result["human_visual_acceptance_required"] is True
    assert result["production_activation"] is False


def test_frame_index_allows_multiple_candidates_but_only_one_verified_target() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    base = observations["observations"][1]
    base["measured_person_candidate_count"] = 2
    observations["observations"].append(
        _observation(
            base["source_key"],
            base["source_sha256"],
            timestamp=2.0,
            view="front",
            face=0.8,
            body=0.8,
            phash="1111111111111111",
            verified=False,
            candidate_id="person-1",
            candidate_count=2,
        )
    )
    result = build_frame_index(plan, receipt, observations)
    assert result["teacher_training_authorized"] is True
    assert len([row for row in result["observations"] if row["source_key"] == base["source_key"]]) == 2
    assert len([row for row in result["observations"] if row["source_key"] == base["source_key"] and row["eligible_for_teacher"]]) == 1


def test_frame_index_rejects_two_verified_targets_in_one_sample() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    base = observations["observations"][1]
    base["measured_person_candidate_count"] = 2
    observations["observations"].append(
        _observation(
            base["source_key"], base["source_sha256"], timestamp=2.0, view="front", face=0.8, body=0.8,
            phash="1111111111111111", verified=True, candidate_id="person-1", candidate_count=2,
        )
    )
    with pytest.raises(PhotorealFrameIndexError, match="multiple target identities"):
        build_frame_index(plan, receipt, observations)


def test_frame_index_validates_ambiguous_sample_count() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    row = observations["observations"][1]
    row["identity_sample_ambiguous"] = True
    row["target_identity_verified"] = False
    row["identity_authority"] = "identity-unresolved-v1"
    observations["identity_ambiguous_sample_count"] = 0
    with pytest.raises(PhotorealFrameIndexError, match="ambiguous sample count"):
        build_frame_index(plan, receipt, observations)


def test_frame_index_blocks_cross_split_perceptual_near_duplicate() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    observations["observations"][1]["perceptual_hash"] = "0000000000000001"
    result = build_frame_index(plan, receipt, observations)
    assert result["teacher_training_authorized"] is False
    assert result["cross_split_near_duplicate_count"] >= 1
    assert "cross-split perceptual near-duplicates detected" in result["training_blockers"]


def test_frame_index_requires_rear_in_eval_when_rear_is_source_observable() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    train_key = str(plan["train"][0]["source_id"])
    train_sha = next(item["sha256"] for item in receipt["sources"] if item["source_key"] == train_key)
    observations["observations"].append(
        _observation(train_key, train_sha, timestamp=5.0, view="rear", face=0.0, body=0.95, phash="aaaaaaaaaaaaaaaa")
    )
    result = build_frame_index(plan, receipt, observations)
    assert result["rear_view_source_observable"] is True
    assert "full-body-rear" in result["held_out_view_coverage_missing"]
    assert result["teacher_training_authorized"] is False


def test_frame_index_excludes_identity_unresolved_observation() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    observations["observations"][1] = _observation(
        str(plan["evaluation"][0]["source_id"]), "b" * 64, timestamp=2.0, view="front", face=0.9,
        body=0.9, phash="1111111111111111", verified=False,
    )
    result = build_frame_index(plan, receipt, observations)
    assert result["teacher_training_authorized"] is False
    assert "held-out evaluation view coverage is incomplete" in result["training_blockers"]


def test_frame_index_rejects_raw_analyzer_observations_without_core_authority() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    observations["format"] = "bodyrig-photoreal-frame-observations"
    with pytest.raises(PhotorealFrameIndexError, match="authorized frame observations format/version"):
        build_frame_index(plan, receipt, observations)


def test_frame_index_rejects_false_core_authority_marker() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    observations["identity_authority_is_core_derived"] = False
    with pytest.raises(PhotorealFrameIndexError, match="core-derived identity authority"):
        build_frame_index(plan, receipt, observations)


def test_frame_index_rejects_missing_multi_candidate_safety_marker() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    observations["multi_candidate_identity_safe"] = False
    with pytest.raises(PhotorealFrameIndexError, match="multi-candidate identity safety"):
        build_frame_index(plan, receipt, observations)


def test_frame_index_rejects_inconsistent_identity_authority() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    observations["observations"][0]["target_identity_verified"] = False
    with pytest.raises(PhotorealFrameIndexError, match="unverified target identity"):
        build_frame_index(plan, receipt, observations)


def test_frame_index_rejects_unanalyzed_planned_source() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    missing_key = str(plan["evaluation"][2]["source_id"])
    observations["observations"] = [item for item in observations["observations"] if item["source_key"] != missing_key]
    with pytest.raises(PhotorealFrameIndexError, match="did not cover every planned source"):
        build_frame_index(plan, receipt, observations)


def test_frame_index_rejects_source_byte_mismatch() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    observations = _observations(plan, receipt)
    observations["observations"][0]["source_sha256"] = "f" * 64
    with pytest.raises(PhotorealFrameIndexError, match="different source bytes"):
        build_frame_index(plan, receipt, observations)


def test_frame_index_rejects_plan_receipt_universe_mismatch() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    bad_receipt = copy.deepcopy(receipt)
    bad_receipt["sources"].pop()
    with pytest.raises(PhotorealFrameIndexError, match="disagree on exact source universe"):
        build_frame_index(plan, bad_receipt, _observations(plan, receipt))
