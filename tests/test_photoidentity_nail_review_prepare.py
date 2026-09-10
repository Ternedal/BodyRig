from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from bodyrig.photoidentity_nail_review_prepare import prepare_review_set


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _build_discovery(sweep: Path) -> None:
    private_root = sweep / "private-nail-source-candidates"
    candidates = []
    private_candidates = []
    specs = [
        ("a", "scene-1", "left_fingernails", 0.91, True),
        ("b", "scene-2", "right_fingernails", 0.80, True),
        ("c", "scene-3", "left_toenails", 0.79, True),
        ("d", "scene-4", "right_toenails", 0.95, False),
    ]
    for suffix, scene, region, quality, eligible in specs:
        candidate_id = "nailcand-" + suffix * 32
        root = private_root / candidate_id
        root.mkdir(parents=True, exist_ok=True)
        image = root / f"{region}.png"
        Image.new("RGB", (1024, 1024), (100, 100, 100)).save(image)
        public = {
            "candidate_id": candidate_id,
            "scene_id": scene,
            "source_media_sha256": "1" * 64,
            "regions": {
                region: {
                    "image_sha256": _sha(image),
                    "source_quality": quality,
                    "review_eligible": eligible,
                    "native_crop_width": 400,
                    "native_crop_height": 400,
                }
            },
        }
        private = {
            "candidate_id": candidate_id,
            "scene_id": scene,
            "source_media_sha256": "1" * 64,
            "source_path": str(sweep / f"{suffix}.mp4"),
            "region_images": {region: str(image)},
        }
        candidates.append(public)
        private_candidates.append(private)
    public_manifest = {
        "format": "bodyrig-photoidentity-nail-source-discovery",
        "version": 1,
        "performer_id": "42",
        "bodyrig_revision": "a" * 40,
        "source_paths_persisted": False,
        "machine_nail_identity_authority": False,
        "generic_guessing_permitted": False,
        "production_activation": False,
        "candidates": candidates,
    }
    public_path = sweep / "nail-source-candidates.json"
    _write_json(public_path, public_manifest)
    _write_json(
        private_root / "private-candidate-index.json",
        {
            "format": "bodyrig-photoidentity-private-nail-source-index",
            "version": 1,
            "public_manifest_sha256": _sha(public_path),
            "candidates": private_candidates,
        },
    )


def test_review_set_only_flattens_attestable_source_closeups(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    _build_discovery(sweep)
    result = prepare_review_set(sweep)
    assert len(result["entries"]) == 2
    assert {entry["region"] for entry in result["entries"]} == {"left_fingernails", "right_fingernails"}
    assert result["nail_authority"] is False
    assert result["source_only"] is True
    assert result["production_activation"] is False
    for entry in result["entries"]:
        copied = Path(result["review_root"]) / entry["image"]
        assert copied.is_file()
        assert _sha(copied) == entry["image_sha256"]


def test_review_reference_list_contains_exact_candidate_refs(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    _build_discovery(sweep)
    result = prepare_review_set(sweep)
    refs = Path(result["review_refs"]).read_text(encoding="utf-8")
    assert "nailcand-" + "a" * 32 + ":left_fingernails" in refs
    assert "nailcand-" + "b" * 32 + ":right_fingernails" in refs
    assert "left_toenails" not in refs
    assert "right_toenails" not in refs
