"""Build local, read-only visual-review sheets from existing ExAvatar optimized fits.

This tool NEVER optimizes or trains a model, mutates source artifacts, chooses
training frames, or grants human/photoreal acceptance. It is only a manual
review aid: each panel compares the actual source viewport and the separate
optimized SMPL-X render from the same indexed observation.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError


REPORT_FORMAT = "bodyrig-exavatar-fit-projection-diagnostic"
CATEGORIES = (
    "suspect_optimized_geometry",
    "geometry_proxy_promising_review_required",
    "body_near_viewport_edge",
    "low_body_keypoint_visibility",
)
TILE_WIDTH, TILE_HEIGHT = 590, 388
IMAGE_SIZE = (270, 270)
BG = (14, 21, 31)
PANEL_BG = (24, 34, 48)
FOREGROUND = (228, 238, 248)
MUTED = (157, 176, 197)
CATEGORY_LABELS = {
    "suspect_optimized_geometry": "SUSPECT GEOMETRY",
    "geometry_proxy_promising_review_required": "PROMISING PROXY - NOT APPROVED",
    "body_near_viewport_edge": "VIEWPORT EDGE / CROPPED",
    "low_body_keypoint_visibility": "LOW KEYPOINT VISIBILITY",
    "requested_frames": "TARGETED FRAMES - NOT APPROVED",
}


class FitReviewSheetError(ValueError):
    """Invalid read-only inputs or output destination."""


def _regular_file(path: Path, *, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise FitReviewSheetError(f"{label} missing or unsafe: {path}")
    return path


def _read_report(dataset: Path, path: Path) -> list[dict[str, Any]]:
    _regular_file(path, label="diagnostic report")
    try:
        report = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FitReviewSheetError("Diagnostic report is unreadable JSON") from exc
    if not isinstance(report, dict) or report.get("format") != REPORT_FORMAT:
        raise FitReviewSheetError("Diagnostic report format is incompatible")
    try:
        report_dataset = Path(str(report["dataset"])).resolve(strict=True)
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        raise FitReviewSheetError("Diagnostic report dataset is invalid") from exc
    if report_dataset != dataset.resolve(strict=True):
        raise FitReviewSheetError("Diagnostic report belongs to a different dataset")
    if (
        report.get("training_authority") is not False
        or report.get("human_fit_review_accepted") is not False
        or report.get("include_smoothed") is not False
    ):
        raise FitReviewSheetError("Expected non-authorizing, optimized-only diagnostic report")
    rows = report.get("frames")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10_000:
        raise FitReviewSheetError("Diagnostic report frame list is invalid")
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get("frame")) is not int:
            raise FitReviewSheetError("Diagnostic report has a malformed frame")
        frame = row["frame"]
        if not 0 <= frame <= 1_000_000 or frame in seen:
            raise FitReviewSheetError("Diagnostic report has repeated/invalid frame numbers")
        seen.add(frame)
        if row.get("triage") not in CATEGORIES:
            raise FitReviewSheetError(f"Unknown triage category for frame {frame}")
        joints = row.get("valid_body_keypoints")
        if type(joints) is not int or not 0 <= joints <= 17:
            raise FitReviewSheetError(f"Invalid joint count for frame {frame}")
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            raise FitReviewSheetError(f"Invalid metrics for frame {frame}")
        optimized = metrics.get("optimized")
        if optimized is not None:
            if not isinstance(optimized, Mapping):
                raise FitReviewSheetError(f"Invalid optimized geometry for frame {frame}")
            score = optimized.get("mesh_keypoint_bbox_iou")
            if (
                not isinstance(score, (float, int))
                or isinstance(score, bool)
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise FitReviewSheetError(f"Invalid IoU for frame {frame}")
        normalized.append(row)
    return normalized


def _optimized_iou(row: Mapping[str, Any]) -> float:
    return float(row.get("metrics", {}).get("optimized", {}).get("mesh_keypoint_bbox_iou", -1))


def _spread(rows: list[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
    """Deterministically cover the full range of a ranking, not just outliers."""
    if len(rows) <= maximum:
        return rows
    if maximum == 1:
        return rows[:1]
    return [rows[round(index * (len(rows) - 1) / (maximum - 1))]
            for index in range(maximum)]


def select_review_frames(
    rows: list[dict[str, Any]],
    *,
    per_category: int,
) -> dict[str, list[dict[str, Any]]]:
    if not 1 <= per_category <= 20:
        raise FitReviewSheetError("Select between 1 and 20 frames per category")
    result: dict[str, list[dict[str, Any]]] = {}
    for category in CATEGORIES:
        items = [row for row in rows if row["triage"] == category]
        if category == "low_body_keypoint_visibility":
            items.sort(key=lambda row: (
                row["valid_body_keypoints"], _optimized_iou(row), row["frame"]
            ))
        elif category == "geometry_proxy_promising_review_required":
            items.sort(key=lambda row: (-_optimized_iou(row), row["frame"]))
        else:
            items.sort(key=lambda row: (_optimized_iou(row), row["frame"]))
        result[category] = _spread(items, per_category)
    return result


def _safe_output_dir(dataset: Path, target: Path) -> Path:
    source = dataset.resolve(strict=True)
    out = target.expanduser().resolve(strict=False)
    if out == source or source in out.parents:
        raise FitReviewSheetError("Review sheets may not be written inside the training dataset")
    if out.exists():
        if out.is_symlink() or not out.is_dir():
            raise FitReviewSheetError(f"Output destination is unsafe: {out}")
        if any(out.iterdir()):
            raise FitReviewSheetError(
                "Output directory must be empty to avoid overwriting prior review evidence"
            )
    else:
        out.mkdir(parents=True)
    return out


def _load_view(path: Path, *, label: str) -> Image.Image:
    _regular_file(path, label=label)
    try:
        with Image.open(path) as image:
            if image.width < 1 or image.height < 1 or max(image.size) > 8192:
                raise FitReviewSheetError(f"Invalid image dimensions for {label}: {path}")
            rgb = ImageOps.exif_transpose(image).convert("RGB")
            rgb.thumbnail(IMAGE_SIZE, Image.Resampling.LANCZOS)
            return rgb
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise FitReviewSheetError(f"Unreadable {label}: {path}") from exc


def render_sheet(
    dataset: Path,
    rows: list[dict[str, Any]],
    *,
    category: str,
    output: Path,
) -> None:
    if category not in CATEGORY_LABELS or not rows:
        raise FitReviewSheetError("Unknown or empty review sheet category")
    cols = 3
    grid_rows = math.ceil(len(rows) / cols)
    sheet = Image.new("RGB", (cols * TILE_WIDTH, 80 + grid_rows * TILE_HEIGHT), BG)
    draw = ImageDraw.Draw(sheet)
    draw.text((18, 12), f"BODYRIG | {CATEGORY_LABELS[category]}", fill=FOREGROUND)
    draw.text(
        (18, 36),
        "Source viewport versus OPTIMIZED (not smoothed) SMPL-X render | VISUAL TRIAGE ONLY",
        fill=MUTED,
    )
    draw.text((18, 54), "NOT an approval of anatomy, identity, cameras or Gaussian training", fill=MUTED)
    for index, row in enumerate(rows):
        frame = row["frame"]
        col, row_i = index % cols, index // cols
        x, y = col * TILE_WIDTH, 80 + row_i * TILE_HEIGHT
        draw.rectangle((x + 4, y + 4, x + TILE_WIDTH - 4, y + TILE_HEIGHT - 5), fill=PANEL_BG)
        iou = _optimized_iou(row)
        score = f"{iou:.3f}" if iou >= 0 else "no bbox metric"
        draw.text((x + 14, y + 11),
                  f"FRAME {frame}  |  {row['valid_body_keypoints']}/17 joints  |  bbox IoU {score}",
                  fill=FOREGROUND)
        original = _load_view(dataset / "frames" / f"{frame}.png", label="source viewport")
        optimized = _load_view(
            dataset / "smplx_optimized" / "renders" / f"{frame}_smplx.jpg",
            label="optimized SMPL-X render",
        )
        for n, (preview, label) in enumerate((
            (original, "SOURCE viewport"),
            (optimized, "OPTIMIZED render"),
        )):
            target_x = x + 13 + n * 286
            image_x = target_x + (IMAGE_SIZE[0] - preview.width) // 2
            image_y = y + 44 + (IMAGE_SIZE[1] - preview.height) // 2
            sheet.paste(preview, (image_x, image_y))
            draw.text((target_x + 4, y + 322), label, fill=MUTED)
        draw.text((x + 13, y + 348),
                  CATEGORY_LABELS.get(row["triage"], "TARGETED"),
                  fill=FOREGROUND)
    sheet.save(output, format="PNG")


def build_sheets(
    dataset: Path,
    report: Path,
    output_dir: Path,
    *,
    per_category: int = 12,
    extra_frames: tuple[int, ...] = (),
) -> dict[str, Any]:
    if not dataset.is_dir() or dataset.is_symlink():
        raise FitReviewSheetError(f"Dataset is missing or unsafe: {dataset}")
    rows = _read_report(dataset, report)
    grouped = select_review_frames(rows, per_category=per_category)
    by_frame = {row["frame"]: row for row in rows}
    if len(extra_frames) > 20 or len(extra_frames) != len(set(extra_frames)):
        raise FitReviewSheetError("Select at most 20 unique targeted review frames")
    if extra_frames:
        if any(frame not in by_frame for frame in extra_frames):
            raise FitReviewSheetError("Targeted review frame is not in diagnostic report")
        grouped["requested_frames"] = [by_frame[frame] for frame in extra_frames]
    destination = _safe_output_dir(dataset, output_dir)
    index: dict[str, Any] = {
        "format": "bodyrig-exavatar-visual-triage-index",
        "version": 1,
        "source_dataset": str(dataset.resolve()),
        "source_report": str(report.resolve()),
        "training_authority": False,
        "human_fit_review_accepted": False,
        "photoreal_acceptance_authority": False,
        "camera_translation_authority": False,
        "visual_confirmation_required": True,
        "sheets": [],
    }
    for category, selected in grouped.items():
        if not selected:
            continue
        name = f"review-{category}.png"
        render_sheet(dataset, selected, category=category, output=destination / name)
        index["sheets"].append({
            "category": category,
            "filename": name,
            "frames": [row["frame"] for row in selected],
            "note": "Manual visual comparison; no acceptance or training authority.",
        })
    (destination / "review-index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--per-category", default=12, type=int)
    parser.add_argument("--extra-frames", default="",
                        help="Optional explicit comma-separated frame indexes")
    args = parser.parse_args(argv)
    try:
        extra = tuple(int(chunk.strip()) for chunk in args.extra_frames.split(",") if chunk.strip())
        index = build_sheets(args.dataset, args.report, args.output_dir,
                             per_category=args.per_category, extra_frames=extra)
        for sheet in index["sheets"]:
            print(f"{sheet['filename']}: {sheet['frames']}")
        print(f"Saved {len(index['sheets'])} review sheets in {args.output_dir}")
        print("Read-only evidence. NO training authority or visual acceptance.")
        return 0
    except (FitReviewSheetError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
