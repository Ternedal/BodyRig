from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from bodyrig.bridges.opencv_fidelity_evaluator_v5 import REVISION, width_profile
from bodyrig.fidelity_evaluator_cli import _read_result


class _FakeCv2:
    @staticmethod
    def findNonZero(mask):
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return None
        return np.stack((xs, ys), axis=1).reshape(-1, 1, 2).astype(np.int32)

    @staticmethod
    def boundingRect(points):
        coords = points.reshape(-1, 2)
        x0 = int(coords[:, 0].min())
        x1 = int(coords[:, 0].max())
        y0 = int(coords[:, 1].min())
        y1 = int(coords[:, 1].max())
        return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def _subject_mask(*, wide_arm_span: bool) -> np.ndarray:
    mask = np.zeros((200, 220), dtype=np.uint8)
    # Same head, torso, hips and legs in both masks.
    mask[10:45, 95:125] = 255
    mask[45:130, 80:140] = 255
    mask[90:140, 78:142] = 255
    mask[130:190, 88:105] = 255
    mask[130:190, 115:132] = 255
    if wide_arm_span:
        # Deliberately placed between sampled profile rows: it changes the
        # horizontal bounding box but not the torso widths we want to measure.
        mask[52:55, 20:200] = 255
    return mask


def _revision5_result() -> dict:
    return {
        "format": "bodyrig-fidelity-evaluation",
        "version": 1,
        "measurement": {
            "format": "bodyrig-fidelity-measurement",
            "version": 1,
            "iteration": 1,
            "candidate_sha256": "1" * 64,
            "reference_set_sha256": "2" * 64,
            "evaluator": {"name": "bodyrig-opencv-visual-fidelity", "revision": "5"},
            "scores": {
                "face_appearance": 0.5,
                "body_silhouette": 0.5,
                "hair_appearance": 0.5,
                "skin_material": 0.5,
                "photorealism": 0.5,
                "human_plausibility": 0.5,
                "overall": 0.5,
            },
            "semantics": "visual-fidelity-not-identity-verification",
        },
        "body_reference": {"kind": "private-rgba-capture", "sha256": "3" * 64},
        "shape_hint": None,
        "plausibility": {
            "face_detectability": 1.0,
            "bilateral_balance": 0.8,
            "head_shoulder_proportion": 0.75,
            "head_shoulder_ratio": 0.5,
            "skin_liveliness": 0.7,
            "facial_definition": 0.65,
            "score": 0.73,
            "semantics": "broad-render-plausibility-and-definition-not-age-or-identity-classification",
        },
        "facial_definition": {
            "score": 0.65,
            "candidate": {
                "detail": 4.2,
                "local_contrast": 0.8,
                "eye_edge_density": 0.15,
                "midface_edge_density": 0.18,
            },
            "reference_face_count": 1,
            "photorealism_raw": 0.72,
            "photorealism_definition_cap": 0.81,
            "semantics": "reference-relative-local-feature-definition-not-biometric-identification",
        },
        "diagnostics": {},
        "human_visual_authority_required": True,
        "semantics": "visual-fidelity-not-identity-verification",
    }


def test_revision5_profile_is_invariant_to_unrelated_horizontal_arm_span() -> None:
    relaxed = width_profile(_FakeCv2, _subject_mask(wide_arm_span=False))
    wide = width_profile(_FakeCv2, _subject_mask(wide_arm_span=True))

    assert REVISION == "5"
    assert relaxed == pytest.approx(wide)
    assert max(relaxed) > 0.30


def test_runner_accepts_revision5_extended_result(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps(_revision5_result()) + "\n", encoding="utf-8")

    result = _read_result(path)

    assert result["measurement"]["evaluator"]["revision"] == "5"
    assert result["plausibility"]["head_shoulder_ratio"] == pytest.approx(0.5)
