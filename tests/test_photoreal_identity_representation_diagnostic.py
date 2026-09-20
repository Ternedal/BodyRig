from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_identity_representation_diagnostic.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_photoreal_identity_representation_diagnostic_test",
    TOOL,
)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def _request(path: str) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-extractor-request",
        "version": 1,
        "performer_id": "42",
        "revision": "r",
        "model_set_sha256": "a" * 64,
        "sources": [
            {
                "source_key": "scene:1:E:/scene.mp4",
                "source_sha256": "b" * 64,
                "resolved_path": path,
                "projection": "equi",
                "stereo_layout": "side-by-side",
                "reference_samples": [
                    {"timestamp_seconds": 1.25, "eye": "left"},
                ],
            }
        ],
        "measurement_only": True,
        "train_only": True,
        "identity_matching_authority": False,
        "teacher_training_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_request_transport_allows_only_resolved_path_change() -> None:
    origin = _request(r"\\server\share\scene.mp4")
    execution = _request("/mnt/bodyrig/remote/share/scene.mp4")

    diagnostic._request_transport_equivalent(origin, execution)

    changed = _request("/mnt/bodyrig/remote/share/scene.mp4")
    changed["sources"][0]["reference_samples"][0]["timestamp_seconds"] = 2.0
    with pytest.raises(
        diagnostic.PhotorealIdentityRepresentationDiagnosticError,
        match="changed source authority",
    ):
        diagnostic._request_transport_equivalent(origin, changed)


def test_face_center_world_angles_preserves_center_view_direction() -> None:
    viewport = {
        "viewport_id": "v00",
        "yaw_degrees": 23.0,
        "pitch_degrees": -11.0,
        "horizontal_fov_degrees": 110.0,
        "vertical_fov_degrees": 110.0,
    }
    bbox = (300.0, 300.0, 468.0, 468.0)

    yaw, pitch = diagnostic._face_center_world_angles(
        viewport=viewport,
        bbox=bbox,
        image_width=768,
        image_height=768,
    )

    assert yaw == pytest.approx(23.0, abs=1e-6)
    assert pitch == pytest.approx(-11.0, abs=1e-6)


def test_face_center_world_angles_moves_rightward_face_to_larger_yaw() -> None:
    viewport = {
        "viewport_id": "v00",
        "yaw_degrees": 0.0,
        "pitch_degrees": 0.0,
        "horizontal_fov_degrees": 110.0,
        "vertical_fov_degrees": 110.0,
    }

    yaw, pitch = diagnostic._face_center_world_angles(
        viewport=viewport,
        bbox=(500.0, 330.0, 620.0, 438.0),
        image_width=768,
        image_height=768,
    )

    assert yaw > 0.0
    assert abs(pitch) < 10.0


def test_aggregate_reports_coverage_and_leave_group_out() -> None:
    measurements = [
        {
            "group_id": "scene:1",
            "_embedding": [1.0, 0.0],
            "profile_cosine": 1.0,
            "quality": {
                "bbox_min_dimension_pixels": 100.0,
                "det_score": 0.9,
            },
        },
        {
            "group_id": "scene:1",
            "_embedding": [0.99, 0.1],
            "profile_cosine": 0.99,
            "quality": {
                "bbox_min_dimension_pixels": 90.0,
                "det_score": 0.8,
            },
        },
        {
            "group_id": "scene:2",
            "_embedding": [0.98, 0.2],
            "profile_cosine": 0.98,
            "quality": {
                "bbox_min_dimension_pixels": 80.0,
                "det_score": 0.7,
            },
        },
    ]

    result = diagnostic._aggregate(
        measurements,
        total_reference_count=4,
    )

    assert result["measurement_count"] == 3
    assert result["reference_coverage"] == 0.75
    assert result["group_count"] == 2
    assert result["leave_group_out_cosine"]["min"] > 0.97
    assert result["profile_cosine"]["min"] == 0.98
    assert result["face_min_dimension_pixels"]["median"] == 90.0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def test_attestation_validation_requires_all_bank_groups_human_accepted(
    tmp_path: Path,
) -> None:
    review_root = tmp_path / "review"
    sheets = review_root / "private-review-sheets"
    sheets.mkdir(parents=True)
    sheet = sheets / "g.png"
    sheet.write_bytes(b"review-sheet")
    sheet_sha = _sha(sheet)

    public = {
        "format": "bodyrig-photoreal-identity-group-review-candidates",
        "version": 1,
        "bodyrig_revision": "a" * 40,
        "groups": [
            {
                "group_id": "scene:1",
                "review_sheet_sha256": sheet_sha,
            }
        ],
    }
    public_path = review_root / "identity-group-review-candidates.json"
    _write(public_path, public)

    private = {
        "format": "bodyrig-photoreal-private-identity-group-review-index",
        "version": 1,
        "bodyrig_revision": "a" * 40,
        "groups": [
            {
                "group_id": "scene:1",
                "review_sheet": str(sheet),
            }
        ],
    }
    private_path = review_root / "private-review-index.json"
    _write(private_path, private)

    bank = {
        "identity_bank_sha256": "b" * 64,
        "references": [{"group_id": "scene:1"}],
    }
    attestation = {
        "format": "bodyrig-photoreal-identity-group-attestation",
        "version": 1,
        "human_identity_attested": True,
        "identity_group_selection_authority": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "identity_bank_sha256": "b" * 64,
        "review_manifest_sha256": _sha(public_path),
        "private_review_index_sha256": _sha(private_path),
        "accepted_group_ids": ["scene:1"],
        "rejected_group_ids": [],
        "review_sheet_sha256_by_group": {"scene:1": sheet_sha},
    }
    _write(review_root / "identity-group-attestation.json", attestation)

    result = diagnostic._validate_attestation(
        review_root=review_root,
        bank=bank,
    )
    assert result["human_identity_attested"] is True

    attestation["accepted_group_ids"] = []
    attestation["rejected_group_ids"] = ["scene:1"]
    _write(review_root / "identity-group-attestation.json", attestation)
    with pytest.raises(
        diagnostic.PhotorealIdentityRepresentationDiagnosticError,
        match="requires every bank group",
    ):
        diagnostic._validate_attestation(
            review_root=review_root,
            bank=bank,
        )
