from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from bodyrig.photoidentity_anatomy_source_attestation import (
    PhotoIdentityAnatomyAttestationError,
    _claims,
    _parse_refs,
    _verify_selected_refs,
    record_attestation,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_candidate(
    sweep: Path,
    *,
    candidate_id: str,
    scene_id: str,
    region: str,
    quality: float = 0.90,
) -> tuple[dict, dict]:
    root = sweep / "private-anatomy-source-candidates" / candidate_id
    root.mkdir(parents=True, exist_ok=True)
    image = root / f"{region}.png"
    Image.new("RGB", (1024, 1024), (100, 100, 100)).save(image)
    source = sweep / f"{candidate_id}.mp4"
    source.write_bytes((candidate_id + scene_id).encode("utf-8") * 20)
    public = {
        "candidate_id": candidate_id,
        "scene_id": scene_id,
        "source_media_sha256": _sha(source),
        "observation_view_hint": "unknown",
        "observation_face_visibility": 0.05,
        "regions": {
            region: {
                "image_sha256": _sha(image),
                "source_quality": quality,
                "review_eligible": True,
                "native_crop_width": 640,
                "native_crop_height": 720,
                "machine_asserts_anatomy_visible": False,
                "machine_asserts_rear_orientation": False,
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


def test_ref_parser_keeps_domains_separate() -> None:
    candidate = "anatomycand-" + "a" * 32
    assert _parse_refs([f"{candidate}:rear_body"], domain="body_rear") == [(candidate, "rear_body")]
    with pytest.raises(PhotoIdentityAnatomyAttestationError, match="wrong region type"):
        _parse_refs([f"{candidate}:torso_chest"], domain="body_rear")


def test_rear_attestation_accepts_one_real_scene_but_not_machine_semantics(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    candidate = "anatomycand-" + "b" * 32
    public, private = _fixture_candidate(sweep, candidate_id=candidate, scene_id="scene-1", region="rear_body")
    selected = _verify_selected_refs(
        sweep_root=sweep,
        public_map={candidate: public},
        private_map={candidate: private},
        refs=[(candidate, "rear_body")],
        domain="body_rear",
    )
    assert len(selected) == 1
    public["regions"]["rear_body"]["machine_asserts_rear_orientation"] = True
    with pytest.raises(PhotoIdentityAnatomyAttestationError, match="machine/human semantic boundary"):
        _verify_selected_refs(
            sweep_root=sweep,
            public_map={candidate: public},
            private_map={candidate: private},
            refs=[(candidate, "rear_body")],
            domain="body_rear",
        )


def test_torso_and_waist_require_two_distinct_source_scenes(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    first = "anatomycand-" + "c" * 32
    second = "anatomycand-" + "d" * 32
    first_public, first_private = _fixture_candidate(
        sweep, candidate_id=first, scene_id="same-scene", region="torso_chest"
    )
    second_public, second_private = _fixture_candidate(
        sweep, candidate_id=second, scene_id="same-scene", region="torso_chest"
    )
    with pytest.raises(PhotoIdentityAnatomyAttestationError, match="at least 2 distinct source scene"):
        _verify_selected_refs(
            sweep_root=sweep,
            public_map={first: first_public, second: second_public},
            private_map={first: first_private, second: second_private},
            refs=[(first, "torso_chest"), (second, "torso_chest")],
            domain="torso_chest",
        )

    second_public["scene_id"] = "scene-2"
    second_private["scene_id"] = "scene-2"
    selected = _verify_selected_refs(
        sweep_root=sweep,
        public_map={first: first_public, second: second_public},
        private_map={first: first_private, second: second_private},
        refs=[(first, "torso_chest"), (second, "torso_chest")],
        domain="torso_chest",
    )
    assert {item["scene_id"] for item in selected} == {"same-scene", "scene-2"}


def test_subthreshold_source_cannot_be_human_attested(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    first = "anatomycand-" + "e" * 32
    second = "anatomycand-" + "f" * 32
    first_public, first_private = _fixture_candidate(
        sweep, candidate_id=first, scene_id="scene-1", region="waist_hips", quality=0.79
    )
    second_public, second_private = _fixture_candidate(
        sweep, candidate_id=second, scene_id="scene-2", region="waist_hips", quality=0.95
    )
    with pytest.raises(PhotoIdentityAnatomyAttestationError, match="below photoidentity review threshold"):
        _verify_selected_refs(
            sweep_root=sweep,
            public_map={first: first_public, second: second_public},
            private_map={first: first_private, second: second_private},
            refs=[(first, "waist_hips"), (second, "waist_hips")],
            domain="waist_hips",
        )


def test_tampered_closeup_or_source_media_fails_closed(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    candidate = "anatomycand-" + "1" * 32
    public, private = _fixture_candidate(sweep, candidate_id=candidate, scene_id="scene-1", region="rear_body")
    Path(private["region_images"]["rear_body"]).write_bytes(b"tampered")
    with pytest.raises(PhotoIdentityAnatomyAttestationError, match="bytes no longer match"):
        _verify_selected_refs(
            sweep_root=sweep,
            public_map={candidate: public},
            private_map={candidate: private},
            refs=[(candidate, "rear_body")],
            domain="body_rear",
        )

    public, private = _fixture_candidate(
        sweep, candidate_id="anatomycand-" + "2" * 32, scene_id="scene-2", region="rear_body"
    )
    Path(private["source_path"]).write_bytes(b"changed source bytes")
    with pytest.raises(PhotoIdentityAnatomyAttestationError, match="source media bytes no longer match"):
        _verify_selected_refs(
            sweep_root=sweep,
            public_map={public["candidate_id"]: public},
            private_map={private["candidate_id"]: private},
            refs=[(public["candidate_id"], "rear_body")],
            domain="body_rear",
        )


def test_claims_use_human_source_adapter_and_weakest_scene_quality() -> None:
    claims = _claims(
        [
            {"scene_id": "scene-1", "source_quality": 0.93},
            {"scene_id": "scene-1", "source_quality": 0.84},
            {"scene_id": "scene-2", "source_quality": 0.91},
        ]
    )
    assert claims == [
        {
            "scene_id": "scene-1",
            "quality": 0.84,
            "source_derived": True,
            "adapter": "human-source-anatomy-observability-attestation",
            "revision": "1",
        },
        {
            "scene_id": "scene-2",
            "quality": 0.91,
            "source_derived": True,
            "adapter": "human-source-anatomy-observability-attestation",
            "revision": "1",
        },
    ]


def test_attestation_is_atomic_over_all_three_human_confirmations(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    sweep.mkdir()
    with pytest.raises(PhotoIdentityAnatomyAttestationError, match="atomic"):
        record_attestation(
            sweep_root=sweep,
            rear_refs=[],
            torso_refs=[],
            waist_refs=[],
            confirm_rear_view=True,
            confirm_torso_chest_anatomy_visible=True,
            confirm_waist_hips_anatomy_visible=False,
            quality_note="Reviewed real source anatomy in sufficient detail.",
        )
