from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from bodyrig.photoidentity_anatomy_review_prepare import prepare_review_set
from bodyrig.photoidentity_anatomy_source_discovery import FORMAT, POLICY_REVISION, VERSION


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_discovery_fixture(sweep: Path) -> tuple[str, str]:
    private_root = sweep / "private-anatomy-source-candidates"
    private_root.mkdir(parents=True)
    good_id = "anatomycand-" + "a" * 32
    low_id = "anatomycand-" + "b" * 32
    public_candidates = []
    private_candidates = []
    for candidate_id, scene_id, region, quality, eligible in (
        (good_id, "scene-1", "torso_chest", 0.91, True),
        (low_id, "scene-2", "waist_hips", 0.79, False),
    ):
        root = private_root / candidate_id
        root.mkdir()
        image = root / f"{region}.png"
        Image.new("RGB", (1024, 1024), (90, 90, 90)).save(image)
        entry = {
            "image_sha256": _sha(image),
            "source_quality": quality,
            "review_eligible": eligible,
            "native_crop_width": 640,
            "native_crop_height": 640,
            "machine_asserts_anatomy_visible": False,
            "machine_asserts_rear_orientation": False,
        }
        public = {
            "candidate_id": candidate_id,
            "scene_id": scene_id,
            "source_media_sha256": "1" * 64,
            "observation_view_hint": "unknown",
            "observation_face_visibility": 0.1,
            "regions": {region: entry},
        }
        private = {
            **public,
            "source_path": str(sweep / f"{candidate_id}.mp4"),
            "region_images": {region: str(image)},
        }
        public_candidates.append(public)
        private_candidates.append(private)
    public_manifest = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "performer_id": "42",
        "bodyrig_revision": "c" * 40,
        "candidates": public_candidates,
        "source_paths_persisted": False,
        "machine_anatomy_identity_authority": False,
        "machine_rear_orientation_authority": False,
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    public_path = sweep / "anatomy-source-candidates.json"
    public_path.write_text(json.dumps(public_manifest), encoding="utf-8")
    private_index = {
        "format": "bodyrig-photoidentity-private-anatomy-source-index",
        "version": 1,
        "public_manifest_sha256": _sha(public_path),
        "candidates": private_candidates,
    }
    (private_root / "private-candidate-index.json").write_text(json.dumps(private_index), encoding="utf-8")
    return good_id, low_id


def test_review_set_copies_only_threshold_eligible_source_bytes(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    sweep.mkdir()
    good_id, low_id = _write_discovery_fixture(sweep)
    result = prepare_review_set(sweep)
    assert len(result["entries"]) == 1
    row = result["entries"][0]
    assert row["candidate_id"] == good_id
    assert low_id not in Path(result["review_refs"]).read_text(encoding="utf-8")
    assert row["source_quality"] == 0.91
    copied = Path(result["review_root"]) / row["image"]
    assert _sha(copied) == row["image_sha256"]


def test_review_index_grants_no_anatomy_or_rear_authority(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    sweep.mkdir()
    _write_discovery_fixture(sweep)
    result = prepare_review_set(sweep)
    index = json.loads(Path(result["review_index"]).read_text(encoding="utf-8"))
    assert index["source_only"] is True
    assert index["human_review_required"] is True
    assert index["anatomy_authority"] is False
    assert index["rear_orientation_authority"] is False
    assert index["generic_guessing_permitted"] is False
    assert index["production_activation"] is False
