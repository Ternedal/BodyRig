from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_exavatar_launch_evidence import (
    PhotorealExAvatarLaunchEvidenceError,
    validate_teacher_launch_evidence,
)
from .photoreal_p1_likeness_review import (
    PhotorealP1LikenessReviewError,
    validate_likeness_review_pack,
    validate_likeness_review_receipt,
)

FORMAT = "bodyrig-photoreal-p1-exavatar-lineage"
VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PhotorealP1ExAvatarLineageError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP1ExAvatarLineageError(f"{label} is missing/not regular: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealP1ExAvatarLineageError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealP1ExAvatarLineageError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise PhotorealP1ExAvatarLineageError(f"{label} must be a lowercase SHA-256")
    return text


def _current(teacher_work_root: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    teacher = Path(teacher_work_root).expanduser().resolve()
    p1_root = teacher / "p1-static-teacher-review"
    review_root = p1_root / "likeness-review"
    receipt_path = p1_root / "p1-likeness-review.json"
    try:
        launch = validate_teacher_launch_evidence(teacher)
        manifest = validate_likeness_review_pack(review_root)
        receipt = validate_likeness_review_receipt(
            _read_json(receipt_path, "P1 likeness receipt"),
            review_manifest=manifest,
        )
    except (PhotorealExAvatarLaunchEvidenceError, PhotorealP1LikenessReviewError) as exc:
        raise PhotorealP1ExAvatarLineageError(str(exc)) from exc
    return receipt_path, launch, manifest, receipt


def build_p1_exavatar_lineage(teacher_work_root: str | Path) -> dict[str, Any]:
    teacher = Path(teacher_work_root).expanduser().resolve()
    receipt_path, launch, manifest, receipt = _current(teacher)
    output = teacher / "p1-static-teacher-review" / "exavatar-lineage.json"
    if output.exists():
        raise PhotorealP1ExAvatarLineageError(f"P1 ExAvatar lineage already exists: {output}")
    value = {
        "format": FORMAT,
        "version": VERSION,
        "exavatar_launch_run_id": str(launch["run_id"]),
        "bodyrig_revision": str(launch["bodyrig_revision"]),
        "launch_authority_sha256": _sha(launch["launch_authority_sha256"], "launch authority SHA-256"),
        "teacher_manifest_sha256": _sha(launch["teacher_manifest_sha256"], "teacher manifest SHA-256"),
        "p1_likeness_review_manifest_sha256": _sha(
            manifest["p1_likeness_review_manifest_sha256"],
            "P1 likeness review manifest SHA-256",
        ),
        "p1_likeness_review_sha256": _sha(
            receipt["p1_likeness_review_sha256"],
            "P1 likeness review SHA-256",
        ),
        "p1_likeness_review_file_sha256": _sha256_file(receipt_path),
        "p1_static_teacher_status": str(receipt["p1_static_teacher_status"]),
        "p2_animation_authorized": receipt["p2_animation_authorized"] is True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except FileExistsError as exc:
        raise PhotorealP1ExAvatarLineageError(f"P1 ExAvatar lineage already exists: {output}") from exc
    return validate_p1_exavatar_lineage(teacher)


def validate_p1_exavatar_lineage(teacher_work_root: str | Path) -> dict[str, Any]:
    teacher = Path(teacher_work_root).expanduser().resolve()
    receipt_path, launch, manifest, receipt = _current(teacher)
    path = teacher / "p1-static-teacher-review" / "exavatar-lineage.json"
    value = _read_json(path, "P1 ExAvatar lineage")
    required = {
        "format",
        "version",
        "exavatar_launch_run_id",
        "bodyrig_revision",
        "launch_authority_sha256",
        "teacher_manifest_sha256",
        "p1_likeness_review_manifest_sha256",
        "p1_likeness_review_sha256",
        "p1_likeness_review_file_sha256",
        "p1_static_teacher_status",
        "p2_animation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    }
    if set(value) != required:
        raise PhotorealP1ExAvatarLineageError("P1 ExAvatar lineage fields must match v1 exactly")
    if value.get("format") != FORMAT or type(value.get("version")) is not int or value.get("version") != VERSION:
        raise PhotorealP1ExAvatarLineageError("P1 ExAvatar lineage format/version mismatch")
    expected = {
        "exavatar_launch_run_id": str(launch["run_id"]),
        "bodyrig_revision": str(launch["bodyrig_revision"]),
        "launch_authority_sha256": str(launch["launch_authority_sha256"]),
        "teacher_manifest_sha256": str(launch["teacher_manifest_sha256"]),
        "p1_likeness_review_manifest_sha256": str(manifest["p1_likeness_review_manifest_sha256"]),
        "p1_likeness_review_sha256": str(receipt["p1_likeness_review_sha256"]),
        "p1_likeness_review_file_sha256": _sha256_file(receipt_path),
        "p1_static_teacher_status": str(receipt["p1_static_teacher_status"]),
        "p2_animation_authorized": receipt["p2_animation_authorized"] is True,
    }
    for field, wanted in expected.items():
        if value.get(field) != wanted:
            raise PhotorealP1ExAvatarLineageError(f"P1 ExAvatar lineage mismatch: {field}")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealP1ExAvatarLineageError("P1 ExAvatar lineage crossed photoreal/production authority")
    result = dict(value)
    result["p1_exavatar_lineage_sha256"] = _sha256_file(path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or validate P1-to-ExAvatar provenance lineage.")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("record", "validate"):
        item = sub.add_parser(command)
        item.add_argument("--teacher-work-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = (
            build_p1_exavatar_lineage(args.teacher_work_root)
            if args.command == "record"
            else validate_p1_exavatar_lineage(args.teacher_work_root)
        )
    except PhotorealP1ExAvatarLineageError as exc:
        print(f"BodyRig P1 ExAvatar lineage: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
