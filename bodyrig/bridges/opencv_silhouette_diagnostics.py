#!/usr/bin/env python
"""Generate private silhouette diagnostics for an existing fidelity render.

This bridge is diagnostic-only. It never writes acceptance and never changes
fidelity scores. It reuses the revision-5 width-profile semantics so operators
can inspect the exact foreground masks and row samples that drive BodyRig's
body-silhouette hints.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import opencv_fidelity_evaluator_v5 as evaluator_v5


BASE = evaluator_v5._BASE
FORMAT = "bodyrig-silhouette-diagnostic"
VERSION = 1
SEMANTICS = "private-diagnostic-only-not-fidelity-acceptance"
ROWS = (0.12, 0.20, 0.28, 0.36, 0.46, 0.56, 0.66, 0.78, 0.90)


def _mask_stats(cv2: Any, mask: Any) -> dict[str, float | int]:
    points = cv2.findNonZero(mask)
    if points is None:
        raise RuntimeError("silhouette diagnostic mask is empty")
    x, y, width, height = cv2.boundingRect(points)
    area = int(cv2.countNonZero(mask))
    image_height, image_width = mask.shape[:2]
    bbox_area = max(1, width * height)
    return {
        "bbox_x": int(x),
        "bbox_y": int(y),
        "bbox_width": int(width),
        "bbox_height": int(height),
        "bbox_aspect_width_over_height": round(float(width) / max(1.0, float(height)), 6),
        "foreground_fraction": round(float(area) / max(1.0, float(image_width * image_height)), 6),
        "bbox_fill_fraction": round(float(area) / float(bbox_area), 6),
    }


def _write_mask(cv2: Any, path: Path, mask: Any) -> None:
    if not cv2.imwrite(str(path), mask):
        raise RuntimeError(f"failed to write silhouette diagnostic image: {path.name}")


def _profile_overlay(cv2: Any, mask: Any):
    subject = BASE.crop_mask_to_subject(cv2, mask)
    overlay = cv2.cvtColor(subject, cv2.COLOR_GRAY2BGR)
    height, width = overlay.shape[:2]
    for index, fraction in enumerate(ROWS):
        y = min(height - 1, max(0, int(round((height - 1) * fraction))))
        cv2.line(overlay, (0, y), (max(0, width - 1), y), (0, 0, 255), 1)
        cv2.putText(
            overlay,
            f"{index}:{fraction:.2f}",
            (4, max(12, y - 3)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return overlay


def _entry(cv2: Any, mask: Any, *, mask_file: str, overlay_file: str) -> dict[str, Any]:
    profile = evaluator_v5.width_profile(cv2, mask)
    head_shoulder_score, head_shoulder_ratio = BASE.head_shoulder_plausibility(profile)
    return {
        "mask_file": mask_file,
        "profile_overlay_file": overlay_file,
        "mask": _mask_stats(cv2, mask),
        "width_profile": [round(float(value), 6) for value in profile],
        "head_shoulder_ratio": round(float(head_shoulder_ratio), 6),
        "head_shoulder_score": round(float(head_shoulder_score), 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate private BodyRig silhouette diagnostics from an existing render set.")
    parser.add_argument("--render-set", required=True)
    parser.add_argument("--body-reference-rgba", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    try:
        if out_dir.exists():
            raise RuntimeError("silhouette diagnostic output already exists")
        render_manifest_path = Path(args.render_set).expanduser().resolve()
        body_reference_path = Path(args.body_reference_rgba).expanduser().resolve()
        if not render_manifest_path.is_file() or not body_reference_path.is_file():
            raise RuntimeError("silhouette diagnostic inputs were not found")

        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV/cv2 is required for silhouette diagnostics") from exc

        render_manifest = BASE.read_json(render_manifest_path, "render-set manifest")
        candidate_sha, renders = BASE.load_render_images(cv2, render_manifest_path.parent, render_manifest)
        body_image = BASE.load_image(cv2, body_reference_path, alpha=True)

        candidate_mask = BASE.render_mask(cv2, __import__("numpy"), renders["front-full"])
        reference_mask = BASE.rgba_mask(body_image)

        out_dir.mkdir(parents=True, exist_ok=False)
        candidate_mask_name = "candidate-mask.png"
        reference_mask_name = "reference-mask.png"
        candidate_overlay_name = "candidate-profile-overlay.png"
        reference_overlay_name = "reference-profile-overlay.png"

        _write_mask(cv2, out_dir / candidate_mask_name, candidate_mask)
        _write_mask(cv2, out_dir / reference_mask_name, reference_mask)
        if not cv2.imwrite(str(out_dir / candidate_overlay_name), _profile_overlay(cv2, candidate_mask)):
            raise RuntimeError("failed to write candidate profile overlay")
        if not cv2.imwrite(str(out_dir / reference_overlay_name), _profile_overlay(cv2, reference_mask)):
            raise RuntimeError("failed to write reference profile overlay")

        candidate = _entry(
            cv2,
            candidate_mask,
            mask_file=candidate_mask_name,
            overlay_file=candidate_overlay_name,
        )
        reference = _entry(
            cv2,
            reference_mask,
            mask_file=reference_mask_name,
            overlay_file=reference_overlay_name,
        )

        result = {
            "format": FORMAT,
            "version": VERSION,
            "evaluator_revision": evaluator_v5.REVISION,
            "candidate_sha256": candidate_sha,
            "body_reference_sha256": BASE.image_sha(body_reference_path),
            "profile_similarity": round(
                float(BASE.profile_similarity(reference["width_profile"], candidate["width_profile"])),
                6,
            ),
            "candidate": candidate,
            "reference": reference,
            "semantics": SEMANTICS,
        }
        report_path = out_dir / "silhouette-diagnostic.json"
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        return 0
    except Exception as exc:
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        print(f"BodyRig silhouette diagnostic: FAIL: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
