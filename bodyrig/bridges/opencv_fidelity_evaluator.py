#!/usr/bin/env python
"""BodyRig visual-fidelity evaluator for private convergence workspaces.

This bridge compares a synthetic BodyRig candidate against an operator-selected
Stash performer reference set. It measures visual appearance, photo-domain
realism and broad non-biometric human plausibility only. The metrics remain
subordinate to human visual review and are never identity verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

EVALUATOR = "bodyrig-opencv-visual-fidelity"
REVISION = "3"
SEMANTICS = "visual-fidelity-not-identity-verification"
VIEWS = ("front-full", "three-quarter-full", "side-full", "face-front")


def clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise RuntimeError(f"{label} is not lowercase SHA-256")
    return value


def image_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_image(cv2: Any, path: Path, expected_sha: str | None = None, *, alpha: bool = False):
    if not path.is_file():
        raise RuntimeError(f"image not found: {path}")
    if expected_sha is not None and image_sha(path) != expected_sha:
        raise RuntimeError(f"image SHA-256 mismatch: {path.name}")
    flag = cv2.IMREAD_UNCHANGED if alpha else cv2.IMREAD_COLOR
    image = cv2.imread(str(path), flag)
    if image is None or getattr(image, "size", 0) == 0:
        raise RuntimeError(f"image could not be decoded: {path.name}")
    return image


def largest_face(cv2: Any, cascade: Any, image: Any):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.10, minNeighbors=4, minSize=(28, 28))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda row: int(row[2]) * int(row[3]))
    pad_x = int(w * 0.18)
    pad_y = int(h * 0.18)
    x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
    x1, y1 = min(image.shape[1], x + w + pad_x), min(image.shape[0], y + h + pad_y)
    return image[y0:y1, x0:x1], (x, y, w, h)


def central_face_fallback(image: Any):
    h, w = image.shape[:2]
    side = max(32, int(min(h, w) * 0.58))
    x0 = max(0, (w - side) // 2)
    y0 = max(0, int(h * 0.12))
    y1 = min(h, y0 + side)
    return image[y0:y1, x0:x0 + side]


def normalized_hist(cv2: Any, image: Any, channels: list[int], bins: list[int], ranges: list[float]):
    hist = cv2.calcHist([image], channels, None, bins, ranges)
    cv2.normalize(hist, hist, alpha=1.0, norm_type=cv2.NORM_L1)
    return hist


def hist_similarity(cv2: Any, left: Any, right: Any) -> float:
    left_hsv = cv2.cvtColor(left, cv2.COLOR_BGR2HSV)
    right_hsv = cv2.cvtColor(right, cv2.COLOR_BGR2HSV)
    lh = normalized_hist(cv2, left_hsv, [0, 1], [32, 32], [0, 180, 0, 256])
    rh = normalized_hist(cv2, right_hsv, [0, 1], [32, 32], [0, 180, 0, 256])
    distance = float(cv2.compareHist(lh, rh, cv2.HISTCMP_BHATTACHARYYA))
    return clamp(1.0 - distance)


def edge_similarity(cv2: Any, left: Any, right: Any) -> float:
    size = (160, 160)
    lg = cv2.cvtColor(cv2.resize(left, size), cv2.COLOR_BGR2GRAY)
    rg = cv2.cvtColor(cv2.resize(right, size), cv2.COLOR_BGR2GRAY)
    le = cv2.Canny(cv2.equalizeHist(lg), 60, 150)
    re = cv2.Canny(cv2.equalizeHist(rg), 60, 150)
    inter = float(((le > 0) & (re > 0)).sum())
    union = float(((le > 0) | (re > 0)).sum())
    if union <= 0:
        return 0.0
    return clamp(inter / union)


def face_similarity(cv2: Any, reference: Any, candidate: Any) -> float:
    # Texture/color and coarse edge layout are intentionally mixed. This is a
    # visual heuristic across photo/render domains, not face recognition.
    return clamp(0.62 * hist_similarity(cv2, reference, candidate) + 0.38 * edge_similarity(cv2, reference, candidate))


def _gray_entropy(cv2: Any, np: Any, gray: Any) -> float:
    hist = cv2.calcHist([gray], [0], None, [64], [0, 256]).reshape(-1).astype("float64")
    total = float(hist.sum())
    if total <= 0:
        return 0.0
    probabilities = hist / total
    probabilities = probabilities[probabilities > 0]
    entropy = -float(np.sum(probabilities * np.log2(probabilities)))
    return entropy / 6.0


def photo_statistics(cv2: Any, np: Any, image: Any) -> dict[str, float]:
    """Return generic natural-photo statistics without recognition features."""
    resized = cv2.resize(image, (192, 192), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_32F)
    return {
        "detail": math.log1p(float(laplacian.var())),
        "contrast": float(gray.std()) / 64.0,
        "edge_density": float((cv2.Canny(gray, 60, 150) > 0).mean()),
        "entropy": _gray_entropy(cv2, np, gray),
    }


def photo_statistics_similarity(cv2: Any, np: Any, reference: Any, candidate: Any) -> float:
    left = photo_statistics(cv2, np, reference)
    right = photo_statistics(cv2, np, candidate)
    errors = (
        min(1.0, abs(left["detail"] - right["detail"]) / 2.25),
        min(1.0, abs(left["contrast"] - right["contrast"]) / 0.55),
        min(1.0, abs(left["edge_density"] - right["edge_density"]) / 0.18),
        min(1.0, abs(left["entropy"] - right["entropy"]) / 0.28),
    )
    weighted_error = 0.34 * errors[0] + 0.22 * errors[1] + 0.22 * errors[2] + 0.22 * errors[3]
    return clamp(1.0 - weighted_error)


def hair_crop(image: Any, face_box: tuple[int, int, int, int] | None):
    h, w = image.shape[:2]
    if face_box is None:
        return image[: max(1, int(h * 0.38)), :]
    x, y, fw, fh = face_box
    x0 = max(0, x - int(fw * 0.35))
    x1 = min(w, x + fw + int(fw * 0.35))
    y0 = max(0, y - int(fh * 0.70))
    y1 = min(h, y + int(fh * 0.30))
    return image[y0:y1, x0:x1]


def skin_crop(image: Any, face_box: tuple[int, int, int, int] | None):
    h, w = image.shape[:2]
    if face_box is None:
        y0, y1 = int(h * 0.33), int(h * 0.67)
        x0, x1 = int(w * 0.33), int(w * 0.67)
        return image[y0:y1, x0:x1]
    x, y, fw, fh = face_box
    return image[
        max(0, y + int(fh * 0.28)): min(h, y + int(fh * 0.78)),
        max(0, x + int(fw * 0.20)): min(w, x + int(fw * 0.80)),
    ]


def skin_liveliness(cv2: Any, image: Any) -> tuple[float, float]:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return (
        float(hsv[:, :, 1].mean()) / 255.0,
        float(hsv[:, :, 2].mean()) / 255.0,
    )


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) / 2.0


def skin_liveliness_similarity(reference_stats: list[tuple[float, float]], candidate: tuple[float, float]) -> float:
    if not reference_stats:
        return 0.5
    reference_saturation = _median([item[0] for item in reference_stats])
    reference_value = _median([item[1] for item in reference_stats])
    saturation_error = min(1.0, abs(reference_saturation - candidate[0]) / 0.35)
    value_error = min(1.0, abs(reference_value - candidate[1]) / 0.30)
    return clamp(1.0 - 0.55 * saturation_error - 0.45 * value_error)


def bilateral_face_plausibility(cv2: Any, np: Any, image: Any) -> float:
    """Broad low-frequency bilateral balance, not a facial identity descriptor."""
    resized = cv2.resize(image, (160, 160), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (15, 15), 0)
    left = gray[:, :80].astype(np.float32)
    right = cv2.flip(gray[:, 80:], 1).astype(np.float32)
    left = (left - float(left.mean())) / max(1.0, float(left.std()))
    right = (right - float(right.mean())) / max(1.0, float(right.std()))
    error = float(np.mean(np.abs(left - right)))
    return clamp(1.0 - error / 2.5)


def render_mask(cv2: Any, np: Any, image: Any):
    h, w = image.shape[:2]
    corners = np.array([image[0, 0], image[0, w - 1], image[h - 1, 0], image[h - 1, w - 1]], dtype=np.float32)
    background = corners.mean(axis=0)
    distance = np.linalg.norm(image.astype(np.float32) - background.reshape(1, 1, 3), axis=2)
    mask = (distance > 24.0).astype("uint8") * 255
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise RuntimeError("candidate full-body render has no foreground silhouette")
    contour = max(contours, key=cv2.contourArea)
    clean = np.zeros_like(mask)
    cv2.drawContours(clean, [contour], -1, 255, thickness=-1)
    return clean


def rgba_mask(image: Any):
    if len(image.shape) != 3 or image.shape[2] != 4:
        raise RuntimeError("private body reference must be an RGBA image")
    return (image[:, :, 3] > 32).astype("uint8") * 255


def crop_mask_to_subject(cv2: Any, mask: Any):
    points = cv2.findNonZero(mask)
    if points is None:
        raise RuntimeError("silhouette mask is empty")
    x, y, w, h = cv2.boundingRect(points)
    if w < 4 or h < 8:
        raise RuntimeError("silhouette mask is implausibly small")
    return mask[y:y+h, x:x+w]


def width_profile(cv2: Any, mask: Any) -> list[float]:
    subject = crop_mask_to_subject(cv2, mask)
    height, width = subject.shape[:2]
    rows = (0.12, 0.20, 0.28, 0.36, 0.46, 0.56, 0.66, 0.78, 0.90)
    result: list[float] = []
    for fraction in rows:
        center = min(height - 1, max(0, int(round((height - 1) * fraction))))
        y0, y1 = max(0, center - 2), min(height, center + 3)
        values = []
        for row in subject[y0:y1]:
            xs = (row > 0).nonzero()[0]
            if len(xs):
                values.append((int(xs[-1]) - int(xs[0]) + 1) / float(width))
        result.append(sum(values) / len(values) if values else 0.0)
    return result


def profile_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    error = sum(abs(a - b) for a, b in zip(left, right)) / len(left)
    return clamp(1.0 - error / 0.35)


def head_shoulder_plausibility(profile: list[float]) -> tuple[float, float]:
    if len(profile) < 4:
        return 0.0, 0.0
    head_width = (profile[0] + profile[1]) / 2.0
    shoulder_width = max(1e-6, (profile[2] + profile[3]) / 2.0)
    ratio = head_width / shoulder_width
    if 0.28 <= ratio <= 0.68:
        score = 1.0
    elif ratio < 0.28:
        score = clamp(1.0 - (0.28 - ratio) / 0.18)
    else:
        score = clamp(1.0 - (ratio - 0.68) / 0.25)
    return score, ratio


def human_plausibility_score(
    *,
    face_detected: bool,
    bilateral_balance: float,
    head_shoulder: float,
    liveliness: float,
) -> float:
    detectability = 1.0 if face_detected else 0.45
    components = (detectability, bilateral_balance, head_shoulder, liveliness)
    weighted = 0.30 * components[0] + 0.25 * components[1] + 0.25 * components[2] + 0.20 * components[3]
    bottleneck_cap = 0.60 + 0.40 * min(components)
    return clamp(min(weighted, bottleneck_cap))


def load_reference_images(cv2: Any, root: Path, manifest: dict[str, Any]):
    if manifest.get("format") != "bodyrig-fidelity-reference-set" or manifest.get("version") != 1:
        raise RuntimeError("reference-set contract mismatch")
    if manifest.get("semantics") != SEMANTICS:
        raise RuntimeError("reference-set semantics mismatch")
    reference_sha = require_sha(manifest.get("reference_set_sha256"), "reference_set_sha256")
    refs = manifest.get("references")
    if not isinstance(refs, list) or not refs:
        raise RuntimeError("reference-set contains no images")
    images = []
    for item in refs:
        if not isinstance(item, dict):
            continue
        filename = item.get("file")
        expected = item.get("sha256")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise RuntimeError("reference-set contains an unsafe filename")
        images.append((load_image(cv2, root / filename, require_sha(expected, "reference.sha256")), item))
    return reference_sha, images


def load_render_images(cv2: Any, root: Path, manifest: dict[str, Any]):
    if manifest.get("format") != "bodyrig-fidelity-render-set" or manifest.get("version") != 1:
        raise RuntimeError("render-set contract mismatch")
    if manifest.get("semantics") != SEMANTICS:
        raise RuntimeError("render-set semantics mismatch")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or [item.get("view") for item in snapshots if isinstance(item, dict)] != list(VIEWS):
        raise RuntimeError("render-set canonical views mismatch")
    result = {}
    for item in snapshots:
        filename = item.get("file")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise RuntimeError("render-set contains an unsafe filename")
        result[item["view"]] = load_image(cv2, root / filename, require_sha(item.get("sha256"), "snapshot.sha256"))
    return require_sha(manifest.get("package_sha256"), "render-set.package_sha256"), result


def combined_reference_sha(stash_reference_sha: str, body_reference_sha: str | None) -> str:
    if body_reference_sha is None:
        return stash_reference_sha
    return hashlib.sha256(f"{stash_reference_sha}:{body_reference_sha}".encode("ascii")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-set", required=True)
    parser.add_argument("--render-set", required=True)
    parser.add_argument("--body-reference-rgba", default="")
    parser.add_argument("--iteration", required=True, type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        if not 1 <= args.iteration <= 50:
            raise RuntimeError("iteration must be in 1..50")
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("OpenCV/cv2 and NumPy are required for fidelity evaluation") from exc

        ref_manifest_path = Path(args.reference_set).expanduser().resolve()
        render_manifest_path = Path(args.render_set).expanduser().resolve()
        out = Path(args.out).expanduser().resolve()
        if out.exists():
            raise RuntimeError("fidelity measurement output already exists")
        ref_manifest = read_json(ref_manifest_path, "reference-set manifest")
        render_manifest = read_json(render_manifest_path, "render-set manifest")
        stash_reference_sha, references = load_reference_images(cv2, ref_manifest_path.parent, ref_manifest)
        candidate_sha, renders = load_render_images(cv2, render_manifest_path.parent, render_manifest)

        cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
        if cascade.empty():
            raise RuntimeError("OpenCV frontal face cascade is unavailable")
        candidate_face_detected = largest_face(cv2, cascade, renders["face-front"])
        if candidate_face_detected is None:
            candidate_face = central_face_fallback(renders["face-front"])
            candidate_box = None
        else:
            candidate_face, candidate_box = candidate_face_detected
        candidate_skin = skin_crop(renders["face-front"], candidate_box)

        face_scores: list[float] = []
        hair_scores: list[float] = []
        skin_scores: list[float] = []
        photorealism_scores: list[float] = []
        reference_liveliness: list[tuple[float, float]] = []
        for image, _meta in references:
            detected = largest_face(cv2, cascade, image)
            if detected is None:
                continue
            ref_face, ref_box = detected
            face_scores.append(face_similarity(cv2, ref_face, candidate_face))
            photorealism_scores.append(photo_statistics_similarity(cv2, np, ref_face, candidate_face))
            ref_hair = hair_crop(image, ref_box)
            cand_hair = hair_crop(renders["face-front"], candidate_box)
            if getattr(ref_hair, "size", 0) and getattr(cand_hair, "size", 0):
                hair_scores.append(hist_similarity(cv2, ref_hair, cand_hair))
            ref_skin = skin_crop(image, ref_box)
            if getattr(ref_skin, "size", 0) and getattr(candidate_skin, "size", 0):
                skin_scores.append(hist_similarity(cv2, ref_skin, candidate_skin))
                reference_liveliness.append(skin_liveliness(cv2, ref_skin))

        face_score = max(face_scores) if face_scores else 0.0
        hair_score = max(hair_scores) if hair_scores else 0.0
        skin_score = max(skin_scores) if skin_scores else 0.0
        if photorealism_scores:
            strongest = sorted(photorealism_scores, reverse=True)[: min(3, len(photorealism_scores))]
            photorealism_score = sum(strongest) / len(strongest)
        else:
            photorealism_score = 0.0

        candidate_mask = render_mask(cv2, np, renders["front-full"])
        body_reference_path = Path(args.body_reference_rgba).expanduser().resolve() if args.body_reference_rgba else None
        body_reference_kind = "none"
        body_reference_sha = None
        body_score = 0.0
        reference_profile = None
        candidate_profile = width_profile(cv2, candidate_mask)
        if body_reference_path is not None:
            body_image = load_image(cv2, body_reference_path, alpha=True)
            body_reference_sha = image_sha(body_reference_path)
            reference_profile = width_profile(cv2, rgba_mask(body_image))
            body_score = profile_similarity(reference_profile, candidate_profile)
            body_reference_kind = "private-rgba-capture"
        reference_authority_sha = combined_reference_sha(stash_reference_sha, body_reference_sha)

        bilateral_score = bilateral_face_plausibility(cv2, np, candidate_face)
        head_shoulder_score, head_shoulder_ratio = head_shoulder_plausibility(candidate_profile)
        liveliness_score = skin_liveliness_similarity(
            reference_liveliness,
            skin_liveliness(cv2, candidate_skin),
        ) if getattr(candidate_skin, "size", 0) else 0.0
        plausibility_score = human_plausibility_score(
            face_detected=candidate_face_detected is not None,
            bilateral_balance=bilateral_score,
            head_shoulder=head_shoulder_score,
            liveliness=liveliness_score,
        )

        scores = {
            "face_appearance": round(face_score, 6),
            "body_silhouette": round(body_score, 6),
            "hair_appearance": round(hair_score, 6),
            "skin_material": round(skin_score, 6),
            "photorealism": round(photorealism_score, 6),
            "human_plausibility": round(plausibility_score, 6),
        }
        scores["overall"] = round(
            0.28 * scores["face_appearance"]
            + 0.20 * scores["body_silhouette"]
            + 0.08 * scores["hair_appearance"]
            + 0.10 * scores["skin_material"]
            + 0.18 * scores["photorealism"]
            + 0.16 * scores["human_plausibility"],
            6,
        )

        shape_hint = None
        if reference_profile is not None:
            shoulder_delta = ((reference_profile[2] + reference_profile[3]) - (candidate_profile[2] + candidate_profile[3])) / 2.0
            hip_delta = ((reference_profile[4] + reference_profile[5]) - (candidate_profile[4] + candidate_profile[5])) / 2.0
            shape_hint = {
                "shoulder_direction": "wider" if shoulder_delta > 0.015 else "narrower" if shoulder_delta < -0.015 else "hold",
                "hip_direction": "wider" if hip_delta > 0.015 else "narrower" if hip_delta < -0.015 else "hold",
                "shoulder_profile_delta": round(float(shoulder_delta), 6),
                "hip_profile_delta": round(float(hip_delta), 6),
            }

        result = {
            "format": "bodyrig-fidelity-evaluation",
            "version": 1,
            "measurement": {
                "format": "bodyrig-fidelity-measurement",
                "version": 1,
                "iteration": args.iteration,
                "candidate_sha256": candidate_sha,
                "reference_set_sha256": reference_authority_sha,
                "evaluator": {"name": EVALUATOR, "revision": REVISION},
                "scores": scores,
                "semantics": SEMANTICS,
            },
            "body_reference": {"kind": body_reference_kind, "sha256": body_reference_sha},
            "shape_hint": shape_hint,
            "plausibility": {
                "face_detectability": 1.0 if candidate_face_detected is not None else 0.45,
                "bilateral_balance": round(bilateral_score, 6),
                "head_shoulder_proportion": round(head_shoulder_score, 6),
                "head_shoulder_ratio": round(float(head_shoulder_ratio), 6),
                "skin_liveliness": round(liveliness_score, 6),
                "score": round(plausibility_score, 6),
                "semantics": "broad-render-plausibility-not-age-or-identity-classification",
            },
            "diagnostics": {
                "stash_reference_set_sha256": stash_reference_sha,
                "reference_image_count": len(references),
                "face_reference_count": len(face_scores),
                "photorealism_reference_count": len(photorealism_scores),
                "candidate_face_detected": candidate_face_detected is not None,
            },
            "human_visual_authority_required": True,
            "semantics": SEMANTICS,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        return 0
    except Exception as exc:
        print(f"BodyRig OpenCV fidelity evaluator: FAIL: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
