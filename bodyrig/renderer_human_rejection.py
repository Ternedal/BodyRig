from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

FORMAT = "bodyrig-renderer-human-rejection"
VERSION = 1
POLICY_REVISION = "bodyrig-renderer-human-rejection-v1"
PLATFORMS = {
    "windows-unity-univrm": "windows",
    "android-quest-class": "quest",
}
FAILED_CHECKS = frozenset(
    {
        "source_identity",
        "geometry_proportions",
        "skin_appearance",
        "hair_appearance",
        "eye_appearance",
        "face_secondary",
        "small_anatomical_detail",
        "upper_body_deformation",
        "lower_body_deformation",
        "cross_limb_leakage",
    }
)
FIELDS = {
    "format",
    "version",
    "policy_revision",
    "rejected_at",
    "bodyrig_revision",
    "body_id",
    "platform",
    "automated_report_sha256",
    "probe_report_sha256",
    "deformation_report_sha256",
    "package_sha256",
    "runtime_manifest_sha256",
    "failed_checks",
    "quality_note",
    "human_review_pass",
    "production_activation",
}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER_NOTE = re.compile(r"^<[^>]+>$")


class RendererHumanRejectionError(RuntimeError):
    pass


def rejection_path(acceptance_dir: str | Path, platform: str) -> Path:
    prefix = PLATFORMS.get(str(platform or "").strip())
    if not prefix:
        raise RendererHumanRejectionError(f"unsupported renderer rejection platform: {platform}")
    return Path(acceptance_dir).expanduser().resolve() / f"bodyrig-renderer-rejection-{prefix}.json"


def any_rejection_exists(acceptance_dir: str | Path) -> bool:
    root = Path(acceptance_dir).expanduser().resolve()
    return any(
        candidate.exists() or candidate.is_symlink()
        for prefix in PLATFORMS.values()
        for candidate in (root / f"bodyrig-renderer-rejection-{prefix}.json",)
    )


def _sha40(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA40.fullmatch(normalized):
        raise RendererHumanRejectionError(f"{label} is not a canonical Git SHA")
    return normalized


def _sha256(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise RendererHumanRejectionError(f"{label} is not a canonical SHA-256")
    return normalized


def _quality_note(value: Any) -> str:
    note = str(value or "").strip()
    if not note:
        raise RendererHumanRejectionError("renderer human rejection requires a non-empty quality note")
    if _PLACEHOLDER_NOTE.fullmatch(note):
        raise RendererHumanRejectionError("renderer human rejection quality note is still a generated placeholder")
    if len(note) > 4000:
        raise RendererHumanRejectionError("renderer human rejection quality note exceeds 4000 characters")
    return note


def _failed_checks(values: Iterable[str]) -> list[str]:
    normalized = sorted({str(value or "").strip() for value in values if str(value or "").strip()})
    if not normalized:
        raise RendererHumanRejectionError("renderer human rejection requires at least one explicit failed check")
    unknown = sorted(set(normalized) - FAILED_CHECKS)
    if unknown:
        raise RendererHumanRejectionError(f"unsupported renderer human rejection checks: {', '.join(unknown)}")
    return normalized


def write_rejection(
    acceptance_dir: str | Path,
    *,
    platform: str,
    bodyrig_revision: str,
    body_id: str,
    automated_report_sha256: str,
    probe_report_sha256: str,
    deformation_report_sha256: str,
    package_sha256: str,
    runtime_manifest_sha256: str,
    failed_checks: Iterable[str],
    quality_note: str,
) -> dict[str, Any]:
    root = Path(acceptance_dir).expanduser().resolve()
    if not root.is_dir():
        raise RendererHumanRejectionError(f"acceptance directory not found: {root}")
    platform = str(platform or "").strip()
    if platform not in PLATFORMS:
        raise RendererHumanRejectionError(f"unsupported renderer rejection platform: {platform}")
    body = str(body_id or "").strip()
    if not body:
        raise RendererHumanRejectionError("renderer human rejection has no body id")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "rejected_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "bodyrig_revision": _sha40(bodyrig_revision, "bodyrig_revision"),
        "body_id": body,
        "platform": platform,
        "automated_report_sha256": _sha256(automated_report_sha256, "automated_report_sha256"),
        "probe_report_sha256": _sha256(probe_report_sha256, "probe_report_sha256"),
        "deformation_report_sha256": _sha256(deformation_report_sha256, "deformation_report_sha256"),
        "package_sha256": _sha256(package_sha256, "package_sha256"),
        "runtime_manifest_sha256": _sha256(runtime_manifest_sha256, "runtime_manifest_sha256"),
        "failed_checks": _failed_checks(failed_checks),
        "quality_note": _quality_note(quality_note),
        "human_review_pass": False,
        "production_activation": False,
    }
    path = rejection_path(root, platform)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise RendererHumanRejectionError(f"refusing to overwrite existing renderer human rejection: {path}") from exc
    return {**receipt, "rejection_path": str(path)}


def read_rejection(
    acceptance_dir: str | Path,
    *,
    platform: str,
    bodyrig_revision: str,
    body_id: str,
    automated_report_sha256: str,
    probe_report_sha256: str,
    deformation_report_sha256: str,
    package_sha256: str,
    runtime_manifest_sha256: str,
) -> dict[str, Any]:
    path = rejection_path(acceptance_dir, platform)
    if path.is_symlink() or not path.is_file():
        raise RendererHumanRejectionError(f"renderer human rejection is missing or symlinked: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RendererHumanRejectionError(f"renderer human rejection is unreadable: {path}") from exc
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise RendererHumanRejectionError("renderer human rejection fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise RendererHumanRejectionError("renderer human rejection format/version/policy mismatch")
    if not str(value.get("rejected_at") or "").strip():
        raise RendererHumanRejectionError("renderer human rejection has no rejected_at timestamp")
    if str(value.get("platform") or "") != platform:
        raise RendererHumanRejectionError("renderer human rejection platform mismatch")
    if _sha40(value.get("bodyrig_revision"), "rejection.bodyrig_revision") != _sha40(bodyrig_revision, "expected bodyrig_revision"):
        raise RendererHumanRejectionError("renderer human rejection revision mismatch")
    if str(value.get("body_id") or "") != str(body_id or ""):
        raise RendererHumanRejectionError("renderer human rejection body id mismatch")
    expected_hashes = {
        "automated_report_sha256": automated_report_sha256,
        "probe_report_sha256": probe_report_sha256,
        "deformation_report_sha256": deformation_report_sha256,
        "package_sha256": package_sha256,
        "runtime_manifest_sha256": runtime_manifest_sha256,
    }
    for field, expected in expected_hashes.items():
        if _sha256(value.get(field), f"rejection.{field}") != _sha256(expected, f"expected {field}"):
            raise RendererHumanRejectionError(f"renderer human rejection {field} no longer matches evidence")
    failures = value.get("failed_checks")
    if not isinstance(failures, list) or failures != _failed_checks(failures):
        raise RendererHumanRejectionError("renderer human rejection failed_checks are not canonical")
    _quality_note(value.get("quality_note"))
    if value.get("human_review_pass") is not False or value.get("production_activation") is not False:
        raise RendererHumanRejectionError("renderer human rejection must remain non-passing and non-activating")
    return value
