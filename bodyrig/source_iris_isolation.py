from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-source-iris-isolation-candidate"
VERSION = 1
METHOD = "human-guided-source-eye-circle-v1"
SOURCE_FORMAT = "bodyrig-eye-appearance-candidate"
SOURCE_VERSION = 1
MIN_RADIUS_PX = 3
MIN_OPAQUE_FRACTION = 0.70
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class SourceIrisIsolationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceIrisIsolationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise SourceIrisIsolationError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SourceIrisIsolationError(f"refusing to overwrite existing iris isolation artifact: {path}") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _revision(value: str) -> str:
    clean = str(value or "").strip().lower()
    if not REVISION_RE.fullmatch(clean):
        raise SourceIrisIsolationError("BodyRig revision must be a canonical lowercase Git SHA")
    return clean


def _source_authority(source_dir: Path) -> tuple[dict[str, Any], Path, Path, Path]:
    receipt_path = source_dir / "eye-appearance-candidate.json"
    left = source_dir / "left_eye_appearance.png"
    right = source_dir / "right_eye_appearance.png"
    bake = source_dir / "canonical_eye_source_bake.png"
    for path in (receipt_path, left, right, bake):
        if not path.is_file():
            raise SourceIrisIsolationError(f"source eye appearance artifact is missing: {path.name}")
    receipt = _read_json(receipt_path, label="source eye appearance receipt")
    if receipt.get("format") != SOURCE_FORMAT or receipt.get("version") != SOURCE_VERSION:
        raise SourceIrisIsolationError("source eye appearance receipt format/version mismatch")
    if (
        receipt.get("sourceDerivedEyeSurfaceAppearance") is not True
        or receipt.get("irisIdentityIsolated") is not False
        or receipt.get("irisAppearanceStatus") != "review-pending"
        or receipt.get("comparisonOnly") is not True
        or receipt.get("humanReviewRequired") is not True
        or receipt.get("productionReady") is not False
    ):
        raise SourceIrisIsolationError("source eye appearance does not satisfy the review-pending source authority boundary")
    expected = {
        "canonicalBakeSha256": _sha256(bake),
        "leftEyeAppearancePngSha256": _sha256(left),
        "rightEyeAppearancePngSha256": _sha256(right),
    }
    for field, actual in expected.items():
        if receipt.get(field) != actual:
            raise SourceIrisIsolationError(f"source eye appearance bytes changed after extraction: {field}")
    return receipt, receipt_path, left, right


def _annotation(value: Mapping[str, Any], *, width: int, height: int, side: str) -> dict[str, int]:
    if set(value) != {"cx", "cy", "radius"}:
        raise SourceIrisIsolationError(f"{side} iris annotation fields must be cx/cy/radius")
    clean: dict[str, int] = {}
    for key in ("cx", "cy", "radius"):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int):
            raise SourceIrisIsolationError(f"{side} iris annotation {key} must be an integer pixel coordinate")
        clean[key] = item
    radius = clean["radius"]
    if radius < MIN_RADIUS_PX:
        raise SourceIrisIsolationError(f"{side} iris radius is implausibly small")
    if radius > min(width, height) // 2:
        raise SourceIrisIsolationError(f"{side} iris radius is implausibly large")
    if clean["cx"] - radius < 0 or clean["cy"] - radius < 0 or clean["cx"] + radius >= width or clean["cy"] + radius >= height:
        raise SourceIrisIsolationError(f"{side} iris circle must stay fully inside the exact source eye crop")
    return clean


def _isolate(source: Path, annotation: Mapping[str, Any], *, side: str) -> tuple[bytes, dict[str, Any]]:
    try:
        from PIL import Image, ImageChops, ImageDraw
    except ImportError as exc:
        raise SourceIrisIsolationError("Pillow is required for source iris isolation") from exc
    try:
        with Image.open(source) as image:
            rgba = image.convert("RGBA")
    except OSError as exc:
        raise SourceIrisIsolationError(f"{side} source eye crop is not a readable image") from exc
    width, height = rgba.size
    ann = _annotation(annotation, width=width, height=height, side=side)
    cx, cy, radius = ann["cx"], ann["cy"], ann["radius"]
    box = (cx - radius, cy - radius, cx + radius + 1, cy + radius + 1)
    crop = rgba.crop(box)
    circle = Image.new("L", crop.size, 0)
    draw = ImageDraw.Draw(circle)
    draw.ellipse((0, 0, crop.width - 1, crop.height - 1), fill=255)
    source_alpha = crop.getchannel("A")
    final_alpha = ImageChops.multiply(source_alpha, circle)
    circle_pixels = sum(1 for value in circle.getdata() if value > 0)
    opaque_pixels = sum(1 for value in final_alpha.getdata() if value > 0)
    if circle_pixels < 1:
        raise SourceIrisIsolationError(f"{side} iris circle mask is empty")
    opaque_fraction = opaque_pixels / circle_pixels
    if opaque_fraction < MIN_OPAQUE_FRACTION:
        raise SourceIrisIsolationError(
            f"{side} iris proposal overlaps too little source eye authority: {opaque_fraction:.3f} < {MIN_OPAQUE_FRACTION:.3f}"
        )
    crop.putalpha(final_alpha)
    import io

    output = io.BytesIO()
    crop.save(output, format="PNG", optimize=False)
    raw = output.getvalue()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SourceIrisIsolationError(f"{side} isolated iris output is not PNG")
    return raw, {
        "annotation": ann,
        "sourceWidth": width,
        "sourceHeight": height,
        "outputWidth": crop.width,
        "outputHeight": crop.height,
        "circlePixelCount": circle_pixels,
        "sourceOpaquePixelCount": opaque_pixels,
        "sourceOpaqueFraction": round(opaque_fraction, 6),
    }


def build_candidate(
    *,
    source_eye_appearance_dir: str | Path,
    output_dir: str | Path,
    bodyrig_revision: str,
    left_annotation: Mapping[str, Any],
    right_annotation: Mapping[str, Any],
) -> dict[str, Any]:
    revision = _revision(bodyrig_revision)
    source_dir = Path(source_eye_appearance_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if not source_dir.is_dir():
        raise SourceIrisIsolationError("source eye appearance directory is missing")
    if output.exists():
        raise SourceIrisIsolationError(f"iris isolation output already exists: {output}")
    receipt, receipt_path, left_source, right_source = _source_authority(source_dir)
    left_raw, left_metrics = _isolate(left_source, left_annotation, side="left")
    right_raw, right_metrics = _isolate(right_source, right_annotation, side="right")

    output.mkdir(parents=True, exist_ok=False)
    left_output = output / "left_iris_candidate.png"
    right_output = output / "right_iris_candidate.png"
    candidate_path = output / "iris-isolation-candidate.json"
    created: list[Path] = []
    try:
        _write_create_only(left_output, left_raw)
        created.append(left_output)
        _write_create_only(right_output, right_raw)
        created.append(right_output)
        candidate = {
            "format": FORMAT,
            "version": VERSION,
            "method": METHOD,
            "bodyrigRevision": revision,
            "sourceEyeAppearanceReceiptSha256": _sha256(receipt_path),
            "sourceCanonicalEyeBakeSha256": str(receipt["canonicalBakeSha256"]),
            "sourceLeftEyeAppearanceSha256": _sha256(left_source),
            "sourceRightEyeAppearanceSha256": _sha256(right_source),
            "targetModelFamily": str(receipt["targetModelFamily"]),
            "left": {**left_metrics, "candidatePngSha256": _sha256(left_output)},
            "right": {**right_metrics, "candidatePngSha256": _sha256(right_output)},
            "sourceDerived": True,
            "humanGuidedIsolation": True,
            "irisIdentityIsolated": False,
            "irisIsolationStatus": "candidate-human-review-required",
            "humanReviewRequired": True,
            "eyeComponentAuthority": False,
            "productionActivation": False,
        }
        raw = (json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        _write_create_only(candidate_path, raw)
        created.append(candidate_path)
        return {**candidate, "candidatePath": str(candidate_path), "leftPath": str(left_output), "rightPath": str(right_output)}
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        try:
            output.rmdir()
        except OSError:
            pass
        raise


def read_candidate(output_dir: str | Path, *, source_eye_appearance_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir).expanduser().resolve()
    source_dir = Path(source_eye_appearance_dir).expanduser().resolve()
    receipt, receipt_path, left_source, right_source = _source_authority(source_dir)
    candidate_path = output / "iris-isolation-candidate.json"
    left_output = output / "left_iris_candidate.png"
    right_output = output / "right_iris_candidate.png"
    for path in (candidate_path, left_output, right_output):
        if not path.is_file():
            raise SourceIrisIsolationError(f"iris isolation artifact is missing: {path.name}")
    value = _read_json(candidate_path, label="iris isolation candidate")
    required = {
        "format", "version", "method", "bodyrigRevision", "sourceEyeAppearanceReceiptSha256",
        "sourceCanonicalEyeBakeSha256", "sourceLeftEyeAppearanceSha256", "sourceRightEyeAppearanceSha256",
        "targetModelFamily", "left", "right", "sourceDerived", "humanGuidedIsolation",
        "irisIdentityIsolated", "irisIsolationStatus", "humanReviewRequired",
        "eyeComponentAuthority", "productionActivation",
    }
    if set(value) != required or value.get("format") != FORMAT or value.get("version") != VERSION or value.get("method") != METHOD:
        raise SourceIrisIsolationError("iris isolation candidate fields/format do not match v1")
    _revision(str(value.get("bodyrigRevision") or ""))
    exact = {
        "sourceEyeAppearanceReceiptSha256": _sha256(receipt_path),
        "sourceCanonicalEyeBakeSha256": str(receipt["canonicalBakeSha256"]),
        "sourceLeftEyeAppearanceSha256": _sha256(left_source),
        "sourceRightEyeAppearanceSha256": _sha256(right_source),
        "targetModelFamily": str(receipt["targetModelFamily"]),
    }
    for field, expected in exact.items():
        if value.get(field) != expected:
            raise SourceIrisIsolationError(f"iris isolation candidate no longer matches source authority: {field}")

    side_fields = {
        "annotation", "sourceWidth", "sourceHeight", "outputWidth", "outputHeight",
        "circlePixelCount", "sourceOpaquePixelCount", "sourceOpaqueFraction", "candidatePngSha256",
    }
    for side, output_path, source_path in (
        ("left", left_output, left_source),
        ("right", right_output, right_source),
    ):
        block = value.get(side)
        if not isinstance(block, dict) or set(block) != side_fields:
            raise SourceIrisIsolationError(f"{side} iris candidate metadata is not canonical")
        annotation = block.get("annotation")
        if not isinstance(annotation, dict):
            raise SourceIrisIsolationError(f"{side} iris candidate annotation is invalid")
        expected_raw, expected_metrics = _isolate(source_path, annotation, side=side)
        expected_hash = hashlib.sha256(expected_raw).hexdigest()
        if block.get("candidatePngSha256") != expected_hash or _sha256(output_path) != expected_hash:
            raise SourceIrisIsolationError(f"{side} iris candidate bytes differ from deterministic source isolation")
        for field, expected in expected_metrics.items():
            if block.get(field) != expected:
                raise SourceIrisIsolationError(
                    f"{side} iris candidate metadata differs from deterministic source isolation: {field}"
                )
    if (
        value.get("sourceDerived") is not True
        or value.get("humanGuidedIsolation") is not True
        or value.get("irisIdentityIsolated") is not False
        or value.get("irisIsolationStatus") != "candidate-human-review-required"
        or value.get("humanReviewRequired") is not True
        or value.get("eyeComponentAuthority") is not False
        or value.get("productionActivation") is not False
    ):
        raise SourceIrisIsolationError("iris candidate crossed the pre-review authority boundary")
    return {**value, "candidatePath": str(candidate_path), "leftPath": str(left_output), "rightPath": str(right_output)}
