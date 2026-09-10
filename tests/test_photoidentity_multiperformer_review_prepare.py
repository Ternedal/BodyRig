from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

import bodyrig.photoidentity_multiperformer_review_prepare as prepare
from bodyrig.photoidentity_multiperformer_source_discovery import (
    FORMAT as DISCOVERY_FORMAT,
    PRIVATE_FORMAT as DISCOVERY_PRIVATE_FORMAT,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _discovery(tmp_path: Path, source: Path) -> tuple[Path, str]:
    root = tmp_path / "discovery"
    root.mkdir()
    candidate_id = "multicand-" + "a" * 32
    public = {
        "format": DISCOVERY_FORMAT,
        "version": 1,
        "bodyrig_revision": "b" * 40,
        "performer_id": "42",
        "stash_scene_count": 2,
        "inventory_page_count": 1,
        "inventory_page_size": 250,
        "inventory_schema": "current",
        "stash_inventory_exhausted": True,
        "candidate_count": 1,
        "candidates": [{
            "candidate_id": candidate_id,
            "scene_id": "scene-7",
            "performer_count": 2,
            "width": 320,
            "height": 240,
            "duration": 20.0,
            "framerate": 25.0,
            "review_priority_score": 10.0,
        }],
        "source_paths_persisted": False,
        "source_media_hashed_at_discovery": False,
        "target_track_selected": False,
        "human_identity_attestation_required": True,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "human_review_render_permitted": False,
        "production_activation": False,
    }
    public_path = root / "multiperformer-source-candidates.json"
    public_path.write_text(json.dumps(public, sort_keys=True) + "\n", encoding="utf-8")
    private_root = root / "private-multiperformer-source-candidates"
    private_root.mkdir()
    private = {
        "format": DISCOVERY_PRIVATE_FORMAT,
        "version": 1,
        "bodyrig_revision": "b" * 40,
        "performer_id": "42",
        "public_manifest_sha256": _sha(public_path),
        "candidate_count": 1,
        "candidates": [{
            "candidate_id": candidate_id,
            "scene_id": "scene-7",
            "source_path": str(source.resolve()),
            "performer_ids": ["42", "8"],
        }],
        "source_paths_private": True,
        "target_track_selected": False,
        "production_activation": False,
    }
    (private_root / "private-candidate-index.json").write_text(
        json.dumps(private, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root, candidate_id


def test_prepare_builds_source_derived_review_sheet_without_selecting_target(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"exact-source-media")
    source_sha = _sha(source)
    discovery, candidate_id = _discovery(tmp_path, source)

    def fake_runner(sources, **kwargs):
        assert [Path(item) for item in sources] == [source.resolve()]
        return {
            "sources": [{
                "source_index": 0,
                "source_media_sha256": source_sha,
                "review": {
                    "tracks": [{
                        "track_id": "s00-t7",
                        "observation_count": 4,
                        "first_timestamp_ms": 0,
                        "last_timestamp_ms": 3000,
                        "samples": [
                            {"timestamp_ms": 0, "confidence": 0.9, "bbox_tlwh": [10.0, 20.0, 80.0, 140.0]},
                            {"timestamp_ms": 3000, "confidence": 0.8, "bbox_tlwh": [20.0, 15.0, 85.0, 145.0]},
                        ],
                    }]
                },
            }]
        }

    def fake_extract(*, ffmpeg, source, timestamp, output):
        Image.new("RGB", (320, 240), "gray").save(output, format="PNG")

    monkeypatch.setattr(prepare, "run_multiperformer_track_review", fake_runner)
    monkeypatch.setattr(prepare, "_extract_frame", fake_extract)

    output = tmp_path / "review"
    result = prepare.prepare_multiperformer_track_review(
        discovery_root=discovery,
        source_candidate_id=candidate_id,
        output_dir=output,
        ffmpeg="ffmpeg",
        external_python="/opt/recovery/bin/python",
        four_d_humans_repo="/opt/4D-Humans",
        phalp_repo="/opt/PHALP",
        distribution="Ubuntu-22.04",
    )
    assert result["track_candidate_count"] == 1
    assert result["target_track_selected"] is False
    assert result["human_identity_attestation_required"] is True
    assert result["target_isolated_source_authority"] is False
    assert result["photoidentity_source_evidence_authority"] is False
    assert result["reconstruction_permitted"] is False

    public = json.loads((output / "multiperformer-track-review-candidates.json").read_text(encoding="utf-8"))
    assert str(source.resolve()) not in json.dumps(public)
    assert public["source_media_sha256"] == source_sha
    track = public["tracks"][0]
    assert track["track_id"] == "s00-t7"
    assert len(track["samples"]) == 2

    private = json.loads((output / "private-track-review" / "private-review-index.json").read_text(encoding="utf-8"))
    sheet = Path(private["tracks"][0]["review_sheet"])
    assert output.resolve() in sheet.parents
    assert sheet.is_file()
    assert _sha(sheet) == track["review_sheet_sha256"]


def test_clamped_box_fails_closed_when_detection_has_no_visible_area():
    try:
        prepare._clamped_box([500.0, 500.0, 10.0, 10.0], width=320, height=240)
    except prepare.PhotoIdentityMultiReviewPrepareError:
        pass
    else:
        raise AssertionError("off-frame detection must fail closed")


def test_review_prepare_source_contains_no_machine_identity_selection():
    text = (Path(__file__).resolve().parents[1] / "bodyrig" / "photoidentity_multiperformer_review_prepare.py").read_text(encoding="utf-8")
    assert '"target_track_selected": False' in text
    assert '"biometric_identity_inference_used": False' in text
    assert '"target_isolated_source_authority": False' in text
    assert '"photoidentity_source_evidence_authority": False' in text
    assert '"reconstruction_permitted": False' in text
    assert "run_multiperformer_track_review" in text
    assert "_extract_frame" in text
