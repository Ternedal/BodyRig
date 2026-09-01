from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-fidelity-review-bundle-receipt"
VERSION = 1
SNAPSHOT_FILES = ("front-full.png", "three-quarter-full.png", "side-full.png", "face-front.png")
PREFIXES = ("historical", "pr40", "pr41")
RENDER_MANIFESTS = tuple(f"{prefix}-fidelity-render-set.json" for prefix in PREFIXES)
IMAGE_FILES = tuple(f"{prefix}-{name}" for prefix in PREFIXES for name in SNAPSHOT_FILES)
BOUND_FILES = IMAGE_FILES + RENDER_MANIFESTS + ("fidelity-ab-evidence.json", "index.html")
RECEIPT_NAME = "review-bundle-receipt.json"


class FidelityReviewReceiptError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise FidelityReviewReceiptError(f"could not hash review-bundle file: {path}") from exc
    return digest.hexdigest()


def _need_sha256(value: Any, *, label: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(char not in "0123456789abcdef" for char in raw):
        raise FidelityReviewReceiptError(f"{label} is not a canonical SHA-256")
    return raw


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FidelityReviewReceiptError(f"{label} not found: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FidelityReviewReceiptError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FidelityReviewReceiptError(f"{label} must be a JSON object")
    return value


def seal_review_bundle(
    root: str | Path,
    *,
    historical_package_sha256: str,
    pr40_package_sha256: str,
    pr41_package_sha256: str,
    evidence_sha256: str,
) -> Path:
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise FidelityReviewReceiptError(f"review bundle directory not found: {directory}")
    receipt_path = directory / RECEIPT_NAME
    if receipt_path.exists():
        raise FidelityReviewReceiptError(f"review bundle receipt already exists: {receipt_path}")

    files = []
    for name in BOUND_FILES:
        path = directory / name
        if not path.is_file():
            raise FidelityReviewReceiptError(f"review bundle file missing before seal: {name}")
        files.append({"path": name, "sha256": _sha256_file(path)})
    expected_evidence_sha = _need_sha256(evidence_sha256, label="source A/B evidence SHA")
    evidence_entry = next(item for item in files if item["path"] == "fidelity-ab-evidence.json")
    if evidence_entry["sha256"] != expected_evidence_sha:
        raise FidelityReviewReceiptError("bundled A/B evidence differs from the source evidence bytes")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "packages": {
            "historical": _need_sha256(historical_package_sha256, label="historical package SHA"),
            "pr40": _need_sha256(pr40_package_sha256, label="#40 package SHA"),
            "pr41": _need_sha256(pr41_package_sha256, label="#41 package SHA"),
        },
        "source_ab_evidence_sha256": expected_evidence_sha,
        "files": files,
        "human_visual_authority_required": True,
        "production_activation": False,
    }
    raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    try:
        with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(raw)
    except OSError as exc:
        raise FidelityReviewReceiptError(f"could not create review bundle receipt: {receipt_path}") from exc
    return receipt_path


def verify_review_bundle(
    root: str | Path,
    *,
    expected_historical_package_sha256: str,
    expected_pr40_package_sha256: str,
    expected_pr41_package_sha256: str,
    expected_evidence_sha256: str,
) -> dict[str, Any]:
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise FidelityReviewReceiptError(f"review bundle directory not found: {directory}")
    receipt = _read_json(directory / RECEIPT_NAME, label="review bundle receipt")
    required = {
        "format",
        "version",
        "packages",
        "source_ab_evidence_sha256",
        "files",
        "human_visual_authority_required",
        "production_activation",
    }
    if set(receipt) != required or receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise FidelityReviewReceiptError("unsupported review bundle receipt")
    if receipt.get("human_visual_authority_required") is not True or receipt.get("production_activation") is not False:
        raise FidelityReviewReceiptError("review bundle receipt has invalid authority semantics")

    packages = receipt.get("packages")
    if not isinstance(packages, Mapping) or set(packages) != {"historical", "pr40", "pr41"}:
        raise FidelityReviewReceiptError("review bundle package authority is invalid")
    expected_packages = {
        "historical": _need_sha256(expected_historical_package_sha256, label="expected historical package SHA"),
        "pr40": _need_sha256(expected_pr40_package_sha256, label="expected #40 package SHA"),
        "pr41": _need_sha256(expected_pr41_package_sha256, label="expected #41 package SHA"),
    }
    for key, expected in expected_packages.items():
        if _need_sha256(packages.get(key), label=f"receipt {key} package SHA") != expected:
            raise FidelityReviewReceiptError(f"review bundle {key} package authority mismatch")

    expected_evidence = _need_sha256(expected_evidence_sha256, label="expected source A/B evidence SHA")
    if _need_sha256(receipt.get("source_ab_evidence_sha256"), label="receipt source A/B evidence SHA") != expected_evidence:
        raise FidelityReviewReceiptError("review bundle source A/B evidence authority mismatch")

    files = receipt.get("files")
    if not isinstance(files, list) or len(files) != len(BOUND_FILES):
        raise FidelityReviewReceiptError("review bundle receipt file set is incomplete")
    by_path: dict[str, str] = {}
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
            raise FidelityReviewReceiptError("review bundle receipt file entry is invalid")
        name = item.get("path")
        if not isinstance(name, str) or name not in BOUND_FILES or name in by_path:
            raise FidelityReviewReceiptError("review bundle receipt file path is invalid or duplicated")
        by_path[name] = _need_sha256(item.get("sha256"), label=f"review bundle {name} SHA")
    if set(by_path) != set(BOUND_FILES):
        raise FidelityReviewReceiptError("review bundle receipt file set differs from the canonical set")

    actual_names = {path.name for path in directory.iterdir() if path.is_file()}
    if actual_names != set(BOUND_FILES) | {RECEIPT_NAME}:
        raise FidelityReviewReceiptError("review bundle contains missing or unexpected top-level files")
    if any(path.is_dir() for path in directory.iterdir()):
        raise FidelityReviewReceiptError("review bundle contains unexpected subdirectories")

    for name, expected_sha in by_path.items():
        path = directory / name
        if not path.is_file() or _sha256_file(path) != expected_sha:
            raise FidelityReviewReceiptError(f"review bundle file hash mismatch: {name}")
    if by_path["fidelity-ab-evidence.json"] != expected_evidence:
        raise FidelityReviewReceiptError("review bundle A/B evidence bytes no longer match the source evidence")

    evidence = _read_json(directory / "fidelity-ab-evidence.json", label="bundled A/B evidence")
    if evidence.get("format") != "bodyrig-fidelity-ab-evidence" or evidence.get("version") != 1:
        raise FidelityReviewReceiptError("bundled A/B evidence format/version is invalid")
    invariants = evidence.get("invariants")
    if not isinstance(invariants, Mapping) or invariants.get("clean_appearance_ab") is not True:
        raise FidelityReviewReceiptError("bundled A/B evidence is not a clean appearance-only comparison")
    left = evidence.get("left")
    right = evidence.get("right")
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise FidelityReviewReceiptError("bundled A/B evidence is missing package-side authority")
    if _need_sha256(left.get("package_sha256"), label="bundled #40 package SHA") != expected_packages["pr40"]:
        raise FidelityReviewReceiptError("bundled A/B evidence #40 package authority mismatch")
    if _need_sha256(right.get("package_sha256"), label="bundled #41 package SHA") != expected_packages["pr41"]:
        raise FidelityReviewReceiptError("bundled A/B evidence #41 package authority mismatch")
    if evidence.get("human_visual_authority_required") is not True or evidence.get("production_activation") is not False:
        raise FidelityReviewReceiptError("bundled A/B evidence has invalid authority semantics")
    return receipt
