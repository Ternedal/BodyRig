from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from bodyrig.photoidentity_nail_source_attestation import (
    PhotoIdentityNailAttestationError,
    _claims,
    _parse_refs,
    _verify_selected_refs,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_candidate(
    sweep: Path,
    *,
    candidate_id: str,
    scene_id: str,
    region: str,
    quality: float = 0.9,
) -> tuple[dict, dict]:
    root = sweep / "private-nail-source-candidates" / candidate_id
    root.mkdir(parents=True, exist_ok=True)
    image = root / f"{region}.png"
    Image.new("RGB", (1024, 1024), (120, 120, 120)).save(image)
    source = sweep / f"{candidate_id}.mp4"
    source.write_bytes((candidate_id + scene_id).encode("utf-8") * 20)
    public = {
        "candidate_id": candidate_id,
        "scene_id": scene_id,
        "source_media_sha256": _sha(source),
        "regions": {
            region: {
                "image_sha256": _sha(image),
                "source_quality": quality,
                "review_eligible": True,
                "native_crop_width": 420,
                "native_crop_height": 420,
            }
        },
    }
    private = {
        "candidate_id": candidate_id,
        "scene_id": scene_id,
        "source_media_sha256": _sha(source),
        "source_path": str(source),
        "region_images": {region: str(image)},
    }
    return public, private


def test_ref_parser_keeps_domain_types_separate() -> None:
    parsed = _parse_refs(
        ["nailcand-" + "a" * 32 + ":left_fingernails"],
        domain="fingernails_detail",
    )
    assert parsed == [("nailcand-" + "a" * 32, "left_fingernails")]
    with pytest.raises(PhotoIdentityNailAttestationError, match="wrong region type"):
        _parse_refs(
            ["nailcand-" + "a" * 32 + ":left_toenails"],
            domain="fingernails_detail",
        )


def test_fingernail_attestation_accepts_two_scenes_with_both_sides(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    left_id = "nailcand-" + "a" * 32
    right_id = "nailcand-" + "b" * 32
    left_public, left_private = _fixture_candidate(
        sweep,
        candidate_id=left_id,
        scene_id="scene-1",
        region="left_fingernails",
    )
    right_public, right_private = _fixture_candidate(
        sweep,
        candidate_id=right_id,
        scene_id="scene-2",
        region="right_fingernails",
    )
    selected = _verify_selected_refs(
        sweep_root=sweep,
        public_map={left_id: left_public, right_id: right_public},
        private_map={left_id: left_private, right_id: right_private},
        refs=[(left_id, "left_fingernails"), (right_id, "right_fingernails")],
        domain="fingernails_detail",
    )
    assert {item["scene_id"] for item in selected} == {"scene-1", "scene-2"}


def test_two_scenes_from_only_one_side_are_still_insufficient(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    first_id = "nailcand-" + "3" * 32
    second_id = "nailcand-" + "4" * 32
    first_public, first_private = _fixture_candidate(
        sweep,
        candidate_id=first_id,
        scene_id="scene-1",
        region="left_fingernails",
    )
    second_public, second_private = _fixture_candidate(
        sweep,
        candidate_id=second_id,
        scene_id="scene-2",
        region="left_fingernails",
    )
    with pytest.raises(PhotoIdentityNailAttestationError, match="both left and right"):
        _verify_selected_refs(
            sweep_root=sweep,
            public_map={first_id: first_public, second_id: second_public},
            private_map={first_id: first_private, second_id: second_private},
            refs=[(first_id, "left_fingernails"), (second_id, "left_fingernails")],
            domain="fingernails_detail",
        )


def test_two_sides_in_one_scene_are_still_insufficient(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    left_id = "nailcand-" + "c" * 32
    right_id = "nailcand-" + "d" * 32
    left_public, left_private = _fixture_candidate(
        sweep,
        candidate_id=left_id,
        scene_id="same-scene",
        region="left_toenails",
    )
    right_public, right_private = _fixture_candidate(
        sweep,
        candidate_id=right_id,
        scene_id="same-scene",
        region="right_toenails",
    )
    with pytest.raises(PhotoIdentityNailAttestationError, match="two distinct source scenes"):
        _verify_selected_refs(
            sweep_root=sweep,
            public_map={left_id: left_public, right_id: right_public},
            private_map={left_id: left_private, right_id: right_private},
            refs=[(left_id, "left_toenails"), (right_id, "right_toenails")],
            domain="toenails_detail",
        )


def test_subthreshold_upscaled_candidate_cannot_be_attested(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    left_id = "nailcand-" + "e" * 32
    right_id = "nailcand-" + "f" * 32
    left_public, left_private = _fixture_candidate(
        sweep,
        candidate_id=left_id,
        scene_id="scene-1",
        region="left_fingernails",
        quality=0.79,
    )
    right_public, right_private = _fixture_candidate(
        sweep,
        candidate_id=right_id,
        scene_id="scene-2",
        region="right_fingernails",
        quality=0.95,
    )
    with pytest.raises(PhotoIdentityNailAttestationError, match="below photoidentity review threshold"):
        _verify_selected_refs(
            sweep_root=sweep,
            public_map={left_id: left_public, right_id: right_public},
            private_map={left_id: left_private, right_id: right_private},
            refs=[(left_id, "left_fingernails"), (right_id, "right_fingernails")],
            domain="fingernails_detail",
        )


def test_tampered_closeup_fails_closed(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    left_id = "nailcand-" + "1" * 32
    right_id = "nailcand-" + "2" * 32
    left_public, left_private = _fixture_candidate(
        sweep,
        candidate_id=left_id,
        scene_id="scene-1",
        region="left_toenails",
    )
    right_public, right_private = _fixture_candidate(
        sweep,
        candidate_id=right_id,
        scene_id="scene-2",
        region="right_toenails",
    )
    Path(left_private["region_images"]["left_toenails"]).write_bytes(b"tampered")
    with pytest.raises(PhotoIdentityNailAttestationError, match="bytes no longer match"):
        _verify_selected_refs(
            sweep_root=sweep,
            public_map={left_id: left_public, right_id: right_public},
            private_map={left_id: left_private, right_id: right_private},
            refs=[(left_id, "left_toenails"), (right_id, "right_toenails")],
            domain="toenails_detail",
        )


def test_scene_claim_uses_weakest_selected_source_quality() -> None:
    result = _claims(
        [
            {"scene_id": "scene-1", "source_quality": 0.93},
            {"scene_id": "scene-1", "source_quality": 0.84},
            {"scene_id": "scene-2", "source_quality": 0.91},
        ]
    )
    assert result == [
        {
            "scene_id": "scene-1",
            "quality": 0.84,
            "source_derived": True,
            "adapter": "human-source-nail-detail-attestation",
            "revision": "1",
        },
        {
            "scene_id": "scene-2",
            "quality": 0.91,
            "source_derived": True,
            "adapter": "human-source-nail-detail-attestation",
            "revision": "1",
        },
    ]
