from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p3_physical_runtime_review import (
    PhotorealP3PhysicalRuntimeReviewError,
    validate_physical_runtime_review_receipt,
)

FORMAT = "bodyrig-runtime-visual-authority"
VERSION = 1
AUTHORITY_FILENAME = "bodyrig-runtime-visual-authority.json"
P3_RECEIPT_FILENAME = "bodyrig-photoreal-p3-runtime-review.json"


class RuntimeVisualAuthorityError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeVisualAuthorityError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeVisualAuthorityError(f"{label} must be a JSON object")
    return value


def _sha256_file(path: Path, *, label: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise RuntimeVisualAuthorityError(f"{label} is missing/not regular: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise RuntimeVisualAuthorityError(f"{label} is not canonical SHA-256")
    return text


def _revision(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise RuntimeVisualAuthorityError(f"{label} is not a canonical Git revision")
    return text


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 1.0:
        raise RuntimeVisualAuthorityError(f"{label} format/version mismatch")


def _runtime_identity(acceptance_dir: Path) -> dict[str, str]:
    acceptance_path = acceptance_dir / "bodyrig-acceptance.json"
    runtime_manifest_path = acceptance_dir / "runtime" / "runtime-manifest.json"
    avatar_path = acceptance_dir / "runtime" / "avatar.vrm"

    acceptance = _read_json(acceptance_path, label="Gate A acceptance")
    if acceptance.get("format") != "bodyrig-rig-acceptance":
        raise RuntimeVisualAuthorityError("Gate A acceptance format mismatch")
    _strict_v1(acceptance.get("version"), label="Gate A acceptance")
    package = acceptance.get("package")
    runtime = acceptance.get("runtime")
    if not isinstance(package, Mapping) or not isinstance(runtime, Mapping):
        raise RuntimeVisualAuthorityError("Gate A package/runtime authority is missing")

    runtime_manifest = _read_json(runtime_manifest_path, label="runtime manifest")
    if runtime_manifest.get("format") != "bodyrig-runtime-assets":
        raise RuntimeVisualAuthorityError("runtime manifest format mismatch")
    _strict_v1(runtime_manifest.get("version"), label="runtime manifest")

    body_id = str(package.get("body_id") or "").strip()
    if not body_id or str(runtime_manifest.get("body_id") or "") != body_id:
        raise RuntimeVisualAuthorityError("runtime body identity differs from Gate A")

    package_sha = _sha(package.get("package_sha256"), label="Gate A package SHA-256")
    if _sha(runtime_manifest.get("package_sha256"), label="runtime package SHA-256") != package_sha:
        raise RuntimeVisualAuthorityError("runtime package identity differs from Gate A")

    runtime_sha = _sha(runtime.get("manifest_sha256"), label="Gate A runtime manifest SHA-256")
    if _sha256_file(runtime_manifest_path, label="runtime manifest") != runtime_sha:
        raise RuntimeVisualAuthorityError("runtime manifest bytes differ from Gate A")

    avatar_sha = _sha(runtime_manifest.get("avatar_sha256"), label="runtime avatar SHA-256")
    if _sha256_file(avatar_path, label="runtime avatar") != avatar_sha:
        raise RuntimeVisualAuthorityError("runtime avatar bytes differ from runtime manifest")

    return {
        "bodyrig_revision": _revision(acceptance.get("bodyrig_revision"), label="Gate A BodyRig revision"),
        "body_id": body_id,
        "package_sha256": package_sha,
        "runtime_manifest_sha256": runtime_sha,
        "avatar_sha256": avatar_sha,
    }


def _p3_avatar_sha(receipt: Mapping[str, Any]) -> str:
    expected: list[str] = []
    for item in receipt.get("student_artifacts") or []:
        if not isinstance(item, Mapping):
            continue
        relative = str(item.get("relative_path") or "").replace("\\", "/")
        if relative == "student/avatar.vrm":
            expected.append(_sha(item.get("sha256"), label="P3 student avatar SHA-256"))
    if len(expected) != 1:
        raise RuntimeVisualAuthorityError("P3 PASS must identify exactly one student/avatar.vrm artifact")

    installed: list[str] = []
    for item in receipt.get("installed_student_artifacts") or []:
        if not isinstance(item, Mapping):
            continue
        relative = str(item.get("relative_path") or "").replace("\\", "/")
        if relative == "student/avatar.vrm":
            installed.append(_sha(item.get("sha256"), label="installed P3 student avatar SHA-256"))
    if installed != expected:
        raise RuntimeVisualAuthorityError("P3 installed avatar bytes do not match the reviewed student avatar")
    return expected[0]


def _validated_p3_receipt(path: Path) -> tuple[dict[str, Any], str]:
    raw = _read_json(path, label="P3 physical runtime review")
    try:
        receipt = validate_physical_runtime_review_receipt(raw)
    except PhotorealP3PhysicalRuntimeReviewError as exc:
        raise RuntimeVisualAuthorityError(f"P3 physical runtime review is invalid: {exc}") from exc

    if receipt.get("runtime_review_status") != "pass":
        raise RuntimeVisualAuthorityError("P3 physical runtime review is not PASS")
    if receipt.get("runtime_acceptance_authority") is not True:
        raise RuntimeVisualAuthorityError("P3 runtime acceptance authority is not granted")
    if receipt.get("photoreal_acceptance_authority") is not True:
        raise RuntimeVisualAuthorityError("P3 photoreal acceptance authority is not granted")
    if receipt.get("physical_device_review_complete") is not True:
        raise RuntimeVisualAuthorityError("P3 physical-device review is incomplete")
    if receipt.get("production_activation") is not False:
        raise RuntimeVisualAuthorityError("P3 review crossed production authority")
    return receipt, _sha256_file(path, label="P3 physical runtime review")


def validate_runtime_visual_authority(acceptance_dir: str | Path) -> dict[str, Any]:
    root = Path(acceptance_dir).expanduser().resolve()
    authority_path = root / AUTHORITY_FILENAME
    p3_copy = root / P3_RECEIPT_FILENAME
    authority = _read_json(authority_path, label="runtime visual authority")

    expected_fields = {
        "format",
        "version",
        "bodyrig_revision",
        "body_id",
        "package_sha256",
        "runtime_manifest_sha256",
        "avatar_sha256",
        "p3_receipt_file_sha256",
        "p3_physical_runtime_review_sha256",
        "performer_id",
        "selected_epoch_id",
        "renderer_visualization_authorized",
        "production_activation",
    }
    if set(authority) != expected_fields or authority.get("format") != FORMAT:
        raise RuntimeVisualAuthorityError("runtime visual authority fields/format mismatch")
    _strict_v1(authority.get("version"), label="runtime visual authority")
    if authority.get("renderer_visualization_authorized") is not True:
        raise RuntimeVisualAuthorityError("runtime visualization authority is not granted")
    if authority.get("production_activation") is not False:
        raise RuntimeVisualAuthorityError("runtime visual authority crossed production authority")

    identity = _runtime_identity(root)
    for field in ("bodyrig_revision", "body_id", "package_sha256", "runtime_manifest_sha256", "avatar_sha256"):
        if str(authority.get(field) or "").lower() != identity[field]:
            raise RuntimeVisualAuthorityError(f"runtime visual authority no longer matches exact {field}")

    p3, p3_file_sha = _validated_p3_receipt(p3_copy)
    if _sha(authority.get("p3_receipt_file_sha256"), label="P3 receipt file SHA-256") != p3_file_sha:
        raise RuntimeVisualAuthorityError("runtime visual authority does not bind the copied P3 receipt bytes")
    if _sha(
        authority.get("p3_physical_runtime_review_sha256"),
        label="P3 physical runtime review SHA-256",
    ) != _sha(
        p3.get("p3_physical_runtime_review_sha256"),
        label="P3 physical runtime review SHA-256",
    ):
        raise RuntimeVisualAuthorityError("runtime visual authority targets a different P3 review receipt")
    if str(authority.get("performer_id") or "") != str(p3.get("performer_id") or ""):
        raise RuntimeVisualAuthorityError("runtime visual authority performer differs from P3 review")
    if str(authority.get("selected_epoch_id") or "") != str(p3.get("selected_epoch_id") or ""):
        raise RuntimeVisualAuthorityError("runtime visual authority epoch differs from P3 review")

    p3_avatar_sha = _p3_avatar_sha(p3)
    if p3_avatar_sha != identity["avatar_sha256"]:
        raise RuntimeVisualAuthorityError(
            "reviewed P3 student avatar bytes do not equal runtime/avatar.vrm; renderer launch is quarantined"
        )
    return dict(authority)


def promote_runtime_visual_authority(
    acceptance_dir: str | Path,
    p3_receipt_path: str | Path,
) -> dict[str, Any]:
    root = Path(acceptance_dir).expanduser().resolve()
    source = Path(p3_receipt_path).expanduser().resolve()
    authority_path = root / AUTHORITY_FILENAME
    p3_copy = root / P3_RECEIPT_FILENAME
    if authority_path.exists() or p3_copy.exists():
        raise RuntimeVisualAuthorityError("runtime visual authority already exists; refusing cross-attempt reuse")

    identity = _runtime_identity(root)
    p3, source_file_sha = _validated_p3_receipt(source)
    if _p3_avatar_sha(p3) != identity["avatar_sha256"]:
        raise RuntimeVisualAuthorityError(
            "P3 PASS is for different avatar bytes than acceptance runtime/avatar.vrm"
        )

    authority: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        **identity,
        "p3_receipt_file_sha256": source_file_sha,
        "p3_physical_runtime_review_sha256": _sha(
            p3.get("p3_physical_runtime_review_sha256"),
            label="P3 physical runtime review SHA-256",
        ),
        "performer_id": str(p3.get("performer_id") or ""),
        "selected_epoch_id": str(p3.get("selected_epoch_id") or ""),
        "renderer_visualization_authorized": True,
        "production_activation": False,
    }
    if not authority["performer_id"] or not authority["selected_epoch_id"]:
        raise RuntimeVisualAuthorityError("P3 receipt has no performer/epoch authority")

    root.mkdir(parents=True, exist_ok=True)
    p3_fd, p3_temp_name = tempfile.mkstemp(prefix=".bodyrig-p3-review.", suffix=".tmp", dir=str(root))
    auth_fd, auth_temp_name = tempfile.mkstemp(prefix=".bodyrig-runtime-visual-authority.", suffix=".tmp", dir=str(root))
    p3_temp = Path(p3_temp_name)
    auth_temp = Path(auth_temp_name)
    try:
        with os.fdopen(p3_fd, "wb") as target:
            target.write(source.read_bytes())
            target.flush()
            os.fsync(target.fileno())
        if _sha256_file(p3_temp, label="staged P3 review") != source_file_sha:
            raise RuntimeVisualAuthorityError("staged P3 review bytes changed")
        with os.fdopen(auth_fd, "w", encoding="utf-8", newline="\n") as target:
            target.write(json.dumps(authority, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(p3_temp, p3_copy)
        os.replace(auth_temp, authority_path)
    finally:
        if p3_temp.exists():
            p3_temp.unlink()
        if auth_temp.exists():
            auth_temp.unlink()

    return validate_runtime_visual_authority(root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bind renderer visualization to exact Photoreal P3-approved runtime avatar bytes")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--acceptance-dir", type=Path, required=True)
    promote = sub.add_parser("promote")
    promote.add_argument("--acceptance-dir", type=Path, required=True)
    promote.add_argument("--p3-receipt", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            authority = validate_runtime_visual_authority(args.acceptance_dir)
        else:
            authority = promote_runtime_visual_authority(args.acceptance_dir, args.p3_receipt)
    except RuntimeVisualAuthorityError as exc:
        print(f"BODYRIG RUNTIME VISUAL AUTHORITY: FAIL | {exc}")
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "body_id": authority["body_id"],
                "avatar_sha256": authority["avatar_sha256"],
                "renderer_visualization_authorized": True,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
