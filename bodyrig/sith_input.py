from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

CAPTURE_FORMAT = "bodyrig-private-identity-capture"
STAGE_FORMAT = "bodyrig-sith-input-stage"
VERSION = 1
EXPECTED_CAPTURE_ADAPTER = "opencv-identity-rgba"
EXPECTED_CAPTURE_REVISION = "1"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class SithInputError(ValueError):
    pass


@dataclass(frozen=True)
class CapturedIdentityInput:
    workspace: Path
    capture_dir: Path
    capture_manifest: dict[str, Any]
    capture_manifest_sha256: str
    rgb_path: Path
    rgba_path: Path
    rgb_sha256: str
    rgba_sha256: str
    rgb_size: tuple[int, int]
    rgba_size: tuple[int, int]


def _canonical_json(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    if not path.is_file():
        raise SithInputError(f"{label} not found: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SithInputError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SithInputError(f"{label} must be an object")
    return raw, value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_leaf(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise SithInputError(f"{field} must be a non-empty filename")
    if value in {".", ".."} or Path(value).name != value or "/" in value or "\\" in value:
        raise SithInputError(f"{field} must be a leaf filename")
    return value


def _hash_value(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise SithInputError(f"{field} must be lowercase SHA-256")
    return value


def _png_size(path: Path, *, label: str) -> tuple[int, int]:
    try:
        header = path.read_bytes()[:24]
    except OSError as exc:
        raise SithInputError(f"could not read {label}") from exc
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise SithInputError(f"{label} is not a canonical PNG")
    width, height = struct.unpack(">II", header[16:24])
    if not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise SithInputError(f"{label} dimensions are invalid")
    return width, height


def load_captured_identity(workspace: str | Path) -> CapturedIdentityInput:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise SithInputError(f"identity workspace not found: {root}")
    capture_dir = root / "identity-capture"
    if not capture_dir.is_dir():
        raise SithInputError("identity-capture directory not found in private workspace")

    capture_path = capture_dir / "capture.json"
    raw, capture = _canonical_json(capture_path, label="private identity capture manifest")
    required = {"format", "version", "adapter", "revision", "subject_track_id", "primary"}
    if set(capture) != required:
        raise SithInputError("private identity capture manifest fields must match v1 exactly")
    if capture["format"] != CAPTURE_FORMAT or capture["version"] != VERSION:
        raise SithInputError("unsupported private identity capture format/version")
    if capture["adapter"] != EXPECTED_CAPTURE_ADAPTER or capture["revision"] != EXPECTED_CAPTURE_REVISION:
        raise SithInputError("SiTH staging currently requires built-in opencv-identity-rgba v1 capture")
    track_id = capture["subject_track_id"]
    if not isinstance(track_id, str) or not track_id or len(track_id) > 160:
        raise SithInputError("private identity subject_track_id is invalid")

    primary = capture["primary"]
    primary_fields = {
        "rgb",
        "rgba",
        "rgb_sha256",
        "rgba_sha256",
        "source_index",
        "time_seconds",
        "foreground_fraction",
    }
    if not isinstance(primary, Mapping) or set(primary) != primary_fields:
        raise SithInputError("private identity primary fields must match v1 exactly")

    rgb_name = _safe_leaf(primary["rgb"], field="primary.rgb")
    rgba_name = _safe_leaf(primary["rgba"], field="primary.rgba")
    if rgb_name != "primary-rgb.png" or rgba_name != "primary-rgba.png":
        raise SithInputError("SiTH staging requires canonical primary-rgb.png and primary-rgba.png")
    rgb_hash = _hash_value(primary["rgb_sha256"], field="primary.rgb_sha256")
    rgba_hash = _hash_value(primary["rgba_sha256"], field="primary.rgba_sha256")

    source_index = primary["source_index"]
    if isinstance(source_index, bool) or not isinstance(source_index, int) or not 0 <= source_index <= 9:
        raise SithInputError("primary.source_index must be in 0..9")
    try:
        timestamp = float(primary["time_seconds"])
        foreground = float(primary["foreground_fraction"])
    except (TypeError, ValueError) as exc:
        raise SithInputError("primary timing/foreground values must be finite numbers") from exc
    if not math.isfinite(timestamp) or timestamp < 0 or timestamp > 172800:
        raise SithInputError("primary.time_seconds is invalid")
    if not math.isfinite(foreground) or not 0.03 <= foreground <= 0.90:
        raise SithInputError("primary.foreground_fraction is invalid")

    rgb_path = capture_dir / rgb_name
    rgba_path = capture_dir / rgba_name
    if not rgb_path.is_file() or not rgba_path.is_file():
        raise SithInputError("private identity capture PNG files are missing")
    if _sha256(rgb_path) != rgb_hash:
        raise SithInputError("primary RGB SHA-256 mismatch")
    if _sha256(rgba_path) != rgba_hash:
        raise SithInputError("primary RGBA SHA-256 mismatch")

    rgb_size = _png_size(rgb_path, label="primary RGB")
    rgba_size = _png_size(rgba_path, label="primary RGBA")
    if rgb_size != rgba_size:
        raise SithInputError("primary RGB/RGBA dimensions differ")

    return CapturedIdentityInput(
        workspace=root,
        capture_dir=capture_dir,
        capture_manifest=dict(capture),
        capture_manifest_sha256=hashlib.sha256(raw).hexdigest(),
        rgb_path=rgb_path,
        rgba_path=rgba_path,
        rgb_sha256=rgb_hash,
        rgba_sha256=rgba_hash,
        rgb_size=rgb_size,
        rgba_size=rgba_size,
    )


def stage_sith_input(workspace: str | Path) -> tuple[Path, dict[str, Any]]:
    captured = load_captured_identity(workspace)
    stage = captured.workspace / "sith-input-v1"
    if stage.exists():
        raise SithInputError("SiTH input stage already exists; refusing cross-run reuse")

    rgba_dir = stage / "rgba"
    images_dir = stage / "images"
    smplx_dir = stage / "smplx"
    back_dir = stage / "back_images"
    meshes_dir = stage / "meshes"
    try:
        for path in (rgba_dir, images_dir, smplx_dir, back_dir, meshes_dir):
            path.mkdir(parents=True, exist_ok=False)
        staged_rgba = rgba_dir / "000.png"
        shutil.copyfile(captured.rgba_path, staged_rgba)
        if _sha256(staged_rgba) != captured.rgba_sha256:
            raise SithInputError("staged SiTH RGBA hash mismatch")

        manifest = {
            "format": STAGE_FORMAT,
            "version": VERSION,
            "capture_manifest_sha256": captured.capture_manifest_sha256,
            "subject_track_id": captured.capture_manifest["subject_track_id"],
            "source_rgba_sha256": captured.rgba_sha256,
            "input_width": captured.rgba_size[0],
            "input_height": captured.rgba_size[1],
            "staged_rgba": "rgba/000.png",
            "centralize": {"size": 1024, "ratio": 0.85},
            "openpose": {
                "model": "BODY_25",
                "number_people_max": 1,
                "net_resolution": "-1x544",
                "scale_number": 3,
                "scale_gap": 0.25,
                "hand": True,
                "face": True,
            },
        }
        (stage / "stage.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        return stage, manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage hash-bound private BodyRig identity capture for pinned SiTH input prep.")
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    try:
        stage, manifest = stage_sith_input(args.workspace)
    except (OSError, SithInputError) as exc:
        print(f"BodyRig SiTH input staging: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"BodyRig SiTH input staging: PASS | {stage} | "
        f"RGBA {manifest['input_width']}x{manifest['input_height']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
