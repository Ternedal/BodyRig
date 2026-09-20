from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_temporal_person_consistency_diagnostic.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_photoreal_temporal_person_consistency_test",
    TOOL,
)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def test_non_biometric_policy_is_explicit_and_face_free() -> None:
    source = TOOL.read_text(encoding="utf-8")

    assert "uses_face_recognition" in source
    assert "uses_face_embedding" in source
    assert "uses_biometric_identity_decision" in source
    assert '"uses_face_recognition": False' in source
    assert '"uses_face_embedding": False' in source
    assert '"uses_biometric_identity_decision": False' in source
    assert "._embedding(" not in source
    assert "face_app.get(" not in source
    assert "_faces(" not in source
    assert "identity_embedding" not in source


def test_temporal_window_is_fixed_a_priori() -> None:
    assert diagnostic.OFFSETS_SECONDS == (-0.20, -0.10, 0.0, 0.10, 0.20)
    assert diagnostic.MIN_VALID_FRAMES == 3
    assert diagnostic.KEYPOINT_SCORE_MIN == 0.30
    assert diagnostic.DIRECT_PERSON_DETECTOR_SCORE_MIN == 0.30
    assert diagnostic.DIRECT_PERSON_DETECTOR_NMS_IOU == 0.30


def test_bbox_iou_and_center_shift() -> None:
    box = (10.0, 10.0, 30.0, 40.0)
    assert diagnostic._bbox_iou(box, box) == pytest.approx(1.0)
    assert diagnostic._center_shift(
        box,
        box,
        width=100,
        height=100,
    ) == pytest.approx(0.0)

    other = (20.0, 10.0, 40.0, 40.0)
    assert 0.0 < diagnostic._bbox_iou(box, other) < 1.0
    assert diagnostic._center_shift(
        box,
        other,
        width=100,
        height=100,
    ) > 0.0


def test_neighbor_selection_uses_tracking_roi_continuity() -> None:
    anchor = {
        "tracking_bbox": (10.0, 10.0, 30.0, 40.0),
    }
    candidates = [
        {
            "tracking_bbox": (70.0, 70.0, 90.0, 95.0),
            "pose": {},
        },
        {
            "tracking_bbox": (12.0, 11.0, 31.0, 40.0),
            "pose": {},
        },
    ]
    selected, iou = diagnostic._choose_neighbor_candidate(
        anchor=anchor,
        candidates=candidates,
    )

    assert selected is candidates[1]
    assert iou > 0.5


def test_pose_distance_uses_visible_body_keypoints() -> None:
    class Base:
        @staticmethod
        def _listish(value):
            if isinstance(value, (list, tuple)):
                return list(value)
            return None

    class Adapter:
        base = Base()

    anchor = {
        "bbox": (0.0, 0.0, 100.0, 100.0),
        "pose": {
            "keypoints": [[float(i), float(i)] for i in range(17)],
            "keypoint_scores": [1.0] * 17,
        },
    }
    candidate = {
        "bbox": (0.0, 0.0, 100.0, 100.0),
        "pose": {
            "keypoints": [[float(i) + 1.0, float(i)] for i in range(17)],
            "keypoint_scores": [1.0] * 17,
        },
    }

    distance, common = diagnostic._normalized_pose_distance(
        Adapter(),
        anchor,
        candidate,
    )

    assert common == 17
    assert distance is not None
    assert distance > 0.0
    assert distance < 0.02


def test_summary_does_not_make_identity_decision() -> None:
    rows = [
        {
            "status": "available",
            "anchor_pose_bbox_is_full_frame": True,
            "anchor_tracking_bbox_source": "direct-rtmdet",
            "median_tracking_bbox_iou": 0.8,
            "median_tracking_center_shift": 0.05,
            "median_pose_bbox_iou": 1.0,
            "median_keypoint_bbox_iou": 0.7,
            "median_appearance_cosine": 0.9,
            "median_pose_distance": 0.08,
        },
        {
            "status": "insufficient-valid-frames",
            "anchor_pose_bbox_is_full_frame": True,
            "anchor_tracking_bbox_source": "none",
            "median_tracking_bbox_iou": None,
            "median_tracking_center_shift": None,
            "median_pose_bbox_iou": None,
            "median_keypoint_bbox_iou": None,
            "median_appearance_cosine": None,
            "median_pose_distance": None,
        },
    ]

    summary = diagnostic._summary(rows)

    assert summary["anchor_count"] == 2
    assert summary["available_anchor_count"] == 1
    assert summary["coverage"] == pytest.approx(0.5)
    assert "match" not in summary
    assert "identity" not in summary


def test_duplicate_decoded_frames_do_not_count_as_temporal_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Image:
        shape = (100, 100, 3)

    anchor_image = Image()

    monkeypatch.setattr(
        diagnostic,
        "_choose_anchor_candidate",
        lambda *_args, **_kwargs: {
            "bbox": (0.0, 0.0, 100.0, 100.0),
            "pose_bbox": (0.0, 0.0, 100.0, 100.0),
            "pose_bbox_is_full_frame": True,
            "direct_detector_bbox": (10.0, 10.0, 40.0, 80.0),
            "direct_detector_score": 0.9,
            "direct_detector_count": 1,
            "keypoint_bbox": (12.0, 12.0, 38.0, 78.0),
            "visible_keypoint_count": 8,
            "tracking_bbox": (10.0, 10.0, 40.0, 80.0),
            "tracking_bbox_source": "direct-rtmdet",
            "pose": {},
        },
    )
    monkeypatch.setattr(
        diagnostic,
        "_appearance_histogram",
        lambda *_args, **_kwargs: [1.0],
    )
    monkeypatch.setattr(
        diagnostic,
        "_keypoints",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        diagnostic,
        "_project_anchor_view",
        lambda **_kwargs: (Image(), "anchor-sha"),
    )

    row = diagnostic._track_anchor(
        representation=object(),
        adapter=object(),
        runtime=object(),
        source={"kind": "video"},
        sample={"timestamp_seconds": 10.0},
        anchor_image=anchor_image,
        anchor_raw_frame_sha="anchor-sha",
        anchor_viewport=None,
        anchor_kind="test-anchor",
        anchor_index=0,
        group_id=None,
        subject_label=None,
    )

    assert row["status"] == "insufficient-valid-frames"
    assert row["valid_frame_count"] == 1
    assert row["distinct_decoded_frame_count"] == 1
    assert row["duplicate_decoded_frame_count"] == 4
    statuses = [item["status"] for item in row["observations"]]
    assert statuses.count("duplicate-anchor-frame") == 4


def test_summary_reports_duplicate_decode_evidence() -> None:
    rows = [
        {
            "status": "insufficient-valid-frames",
            "distinct_decoded_frame_count": 1,
            "duplicate_decoded_frame_count": 4,
            "anchor_pose_bbox_is_full_frame": True,
            "anchor_tracking_bbox_source": "none",
            "median_tracking_bbox_iou": None,
            "median_tracking_center_shift": None,
            "median_pose_bbox_iou": None,
            "median_keypoint_bbox_iou": None,
            "median_appearance_cosine": None,
            "median_pose_distance": None,
        },
        {
            "status": "available",
            "distinct_decoded_frame_count": 5,
            "duplicate_decoded_frame_count": 0,
            "anchor_pose_bbox_is_full_frame": True,
            "anchor_tracking_bbox_source": "direct-rtmdet",
            "median_tracking_bbox_iou": 0.8,
            "median_tracking_center_shift": 0.02,
            "median_pose_bbox_iou": 1.0,
            "median_keypoint_bbox_iou": 0.7,
            "median_appearance_cosine": 0.9,
            "median_pose_distance": 0.04,
        },
    ]

    summary = diagnostic._summary(rows)

    assert summary["anchors_with_duplicate_decodes"] == 1
    assert summary["minimum_distinct_decoded_frames"] == 1


def test_keypoint_envelope_is_not_full_frame_detector_box() -> None:
    class Base:
        @staticmethod
        def _listish(value):
            if isinstance(value, (list, tuple)):
                return list(value)
            return None

    class Adapter:
        base = Base()

    prediction = {
        "keypoints": [
            [40.0, 20.0],
            [45.0, 25.0],
            [50.0, 30.0],
            [55.0, 35.0],
            [60.0, 40.0],
            [65.0, 45.0],
        ],
        "keypoint_scores": [1.0] * 6,
    }
    box, count = diagnostic._keypoint_envelope(
        Adapter(),
        prediction,
        width=100,
        height=100,
    )

    assert count == 6
    assert box is not None
    assert box != (0.0, 0.0, 100.0, 100.0)
    assert diagnostic._is_full_frame_box(
        (0.0, 0.0, 100.0, 100.0),
        width=100,
        height=100,
    ) is True
    assert diagnostic._is_full_frame_box(
        box,
        width=100,
        height=100,
    ) is False


def test_keypoint_envelope_requires_five_visible_points() -> None:
    class Base:
        @staticmethod
        def _listish(value):
            if isinstance(value, (list, tuple)):
                return list(value)
            return None

    class Adapter:
        base = Base()

    prediction = {
        "keypoints": [[10.0, 10.0]] * 4,
        "keypoint_scores": [1.0] * 4,
    }
    box, count = diagnostic._keypoint_envelope(
        Adapter(),
        prediction,
        width=100,
        height=100,
    )

    assert count == 4
    assert box is None


def test_direct_person_detector_uses_fixed_score_and_nms() -> None:
    np = pytest.importorskip("numpy")

    class Instances:
        def cpu(self):
            return self

        def numpy(self):
            return self

        bboxes = np.asarray(
            [
                [10.0, 10.0, 50.0, 90.0],
                [12.0, 12.0, 48.0, 88.0],
                [60.0, 10.0, 90.0, 90.0],
                [0.0, 0.0, 20.0, 20.0],
            ],
            dtype=np.float32,
        )
        scores = np.asarray([0.95, 0.90, 0.80, 0.29], dtype=np.float32)
        labels = np.asarray([0, 0, 1, 0], dtype=np.int64)

    class Sample:
        pred_instances = Instances()

    class Detector:
        def __call__(self, _image, **kwargs):
            assert kwargs.get("return_datasamples") is True
            return {"predictions": [Sample()]}

    class PoseInferencer:
        detector = Detector()
        det_cat_ids = [0]

    class Runtime:
        pose_inferencer = PoseInferencer()
        np = np

    detections = diagnostic._direct_person_detections(Runtime(), object())

    assert len(detections) == 1
    assert detections[0]["score"] == pytest.approx(0.95)
    assert detections[0]["label"] == 0
    assert detections[0]["bbox"] == pytest.approx((10.0, 10.0, 50.0, 90.0))


def test_direct_detector_roi_survives_missing_keypoint_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostic,
        "_direct_person_detections",
        lambda _runtime, _image: [
            {"bbox": (10.0, 10.0, 50.0, 90.0), "score": 0.91, "label": 0}
        ],
    )
    monkeypatch.setattr(
        diagnostic,
        "_keypoint_envelope",
        lambda *_args, **_kwargs: (None, 2),
    )

    class Base:
        @staticmethod
        def _pose_predictions(_runtime, _image):
            return [{"bbox": [0.0, 0.0, 100.0, 100.0]}]

        @staticmethod
        def _pose_bbox(prediction):
            return tuple(prediction["bbox"])

    class Adapter:
        base = Base()

    class Image:
        shape = (100, 100, 3)

    rows = diagnostic._pose_candidates(Adapter(), object(), Image())

    assert len(rows) == 1
    assert rows[0]["tracking_bbox_source"] == "direct-rtmdet"
    assert rows[0]["tracking_bbox"] == (10.0, 10.0, 50.0, 90.0)
    assert rows[0]["visible_keypoint_count"] == 2
    assert rows[0]["pose_bbox_is_full_frame"] is True
