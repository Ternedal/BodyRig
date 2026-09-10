from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.photoidentity_multiperformer_source_discovery import (
    PhotoIdentityMultiSourceDiscoveryError,
    _rank_candidates,
)


def _scene(scene_id: str, path: Path, *, performer_ids=("42", "7"), width=1920, height=1080, tags=()):
    return {
        "id": scene_id,
        "title": f"Scene {scene_id}",
        "performers": [{"id": item, "name": item} for item in performer_ids],
        "tags": [{"name": tag} for tag in tags],
        "files": [{
            "path": str(path),
            "width": width,
            "height": height,
            "duration": 120.0,
            "frame_rate": 30.0,
        }],
    }


def test_rank_candidates_keeps_only_local_projection_safe_multi_performer_media(tmp_path: Path):
    good = tmp_path / "good.mp4"
    single = tmp_path / "single.mp4"
    vr = tmp_path / "vr.mp4"
    for path in (good, single, vr):
        path.write_bytes(b"fixture")
    ranked = _rank_candidates(
        [
            _scene("good", good),
            _scene("single", single, performer_ids=("42",)),
            _scene("vr", vr, width=8192, height=4096),
            _scene("missing", tmp_path / "missing.mp4"),
        ],
        performer_id="42",
    )
    assert len(ranked) == 1
    candidate, performer_ids = ranked[0]
    assert candidate.scene_id == "good"
    assert candidate.performer_count == 2
    assert performer_ids == ("42", "7")


def test_rank_candidates_fails_if_inventory_loses_target_binding(tmp_path: Path):
    source = tmp_path / "wrong.mp4"
    source.write_bytes(b"fixture")
    with pytest.raises(PhotoIdentityMultiSourceDiscoveryError, match="lost target performer"):
        _rank_candidates([_scene("wrong", source, performer_ids=("7", "8"))], performer_id="42")


def test_rank_candidates_deduplicates_same_local_path(tmp_path: Path):
    source = tmp_path / "same.mp4"
    source.write_bytes(b"fixture")
    ranked = _rank_candidates(
        [
            _scene("a", source, width=1280, height=720),
            _scene("b", source, width=3840, height=2160),
        ],
        performer_id="42",
    )
    assert len(ranked) == 1
    assert ranked[0][0].scene_id == "b"


def test_module_contract_is_path_free_public_and_machine_cannot_choose_target():
    source = (Path(__file__).resolve().parents[1] / "bodyrig" / "photoidentity_multiperformer_source_discovery.py").read_text(encoding="utf-8")
    assert '"source_paths_persisted": False' in source
    assert '"source_media_hashed_at_discovery": False' in source
    assert '"target_track_selected": False' in source
    assert '"biometric_identity_inference_used": False' in source
    assert '"generic_guessing_permitted": False' in source
    assert '"reconstruction_permitted": False' in source
    assert '"human_review_render_permitted": False' in source
    assert '"production_activation": False' in source
    assert "fetch_exhaustive_performer_scenes" in source
    assert "private-candidate-index.json" in source


def test_public_candidate_fields_do_not_contain_path_or_media_bytes():
    source = (Path(__file__).resolve().parents[1] / "bodyrig" / "photoidentity_multiperformer_source_discovery.py").read_text(encoding="utf-8")
    public_block = source[source.index("public_candidates.append("):source.index("private_candidates.append(")]
    assert '"source_path"' not in public_block
    assert '"performer_ids"' not in public_block
    assert '"source_media_sha256"' not in public_block
