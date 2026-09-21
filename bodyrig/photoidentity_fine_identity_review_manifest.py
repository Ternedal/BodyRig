from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_detail_enrich import _private_source_bindings
from .photoidentity_fine_identity_attestation import (
    DETAIL_QUALITY_THRESHOLD,
    PRIVATE_FORMAT,
    PRIVATE_VERSION,
    REQUIRED_DOMAINS,
    _validate_marker_inventory,
)

FORMAT = "bodyrig-photoidentity-fine-identity-evidence-list"
VERSION = 1


class PhotoIdentityFineIdentityReviewManifestError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotoIdentityFineIdentityReviewManifestError(f"fine-identity evidence file is missing or symlinked: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityFineIdentityReviewManifestError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityFineIdentityReviewManifestError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityFineIdentityReviewManifestError(f"private fine-identity review manifest already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_text(
            json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _quality(raw: object) -> float:
    try:
        value = float(str(raw))
    except (TypeError, ValueError, OverflowError) as exc:
        raise PhotoIdentityFineIdentityReviewManifestError("fine-identity evidence quality is not numeric") from exc
    if not DETAIL_QUALITY_THRESHOLD <= value <= 1.0:
        raise PhotoIdentityFineIdentityReviewManifestError(
            f"fine-identity evidence quality must be {DETAIL_QUALITY_THRESHOLD:.2f}..1.00"
        )
    return round(value, 4)


def build_private_review_manifest(
    *,
    sweep_root: Path,
    evidence_csv: Path,
    marker_inventory: Path,
    output: Path,
) -> dict[str, Any]:
    sweep_root = sweep_root.expanduser().resolve()
    anatomy_obs = sweep_root / "anatomy-attested-evidence" / "photoidentity-observations.json"
    anatomy_report = sweep_root / "anatomy-attested-evidence" / "photoidentity-evidence.json"
    observations = _read_json(anatomy_obs, label="Anatomy observation evidence")
    report = _read_json(anatomy_report, label="Anatomy sufficiency report")
    performer_id = str(report.get("performer_id") or "").strip()
    revision = str(report.get("bodyrig_revision") or "").strip().lower()
    if not performer_id or not re.fullmatch(r"^[0-9a-f]{40}$", revision):
        raise PhotoIdentityFineIdentityReviewManifestError("anatomy evidence lacks canonical performer/revision identity")
    if str(observations.get("performer_id") or "") != performer_id or str(observations.get("bodyrig_revision") or "").lower() != revision:
        raise PhotoIdentityFineIdentityReviewManifestError("anatomy observation/report identity mismatch")

    evidence_csv = evidence_csv.expanduser().resolve()
    if not evidence_csv.is_file() or evidence_csv.is_symlink():
        raise PhotoIdentityFineIdentityReviewManifestError("fine-identity evidence CSV is missing or symlinked")
    expected_columns = {
        "reference",
        "domain",
        "scene_id",
        "region",
        "source_ordinal",
        "review_image_path",
        "source_quality",
    }
    source_count = int(report.get("source_files_scanned", 0))
    if source_count < 1:
        raise PhotoIdentityFineIdentityReviewManifestError("anatomy report lacks source-file count")
    try:
        sources_by_ordinal, _ = _private_source_bindings(sweep_root, expected_count=source_count)
    except Exception as exc:
        raise PhotoIdentityFineIdentityReviewManifestError(f"could not resolve exact sweep source bindings: {exc}") from exc

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    scenes: dict[str, set[str]] = {domain: set() for domain in REQUIRED_DOMAINS}
    with evidence_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or []) != expected_columns:
            raise PhotoIdentityFineIdentityReviewManifestError(
                "fine-identity evidence CSV columns must be exactly: " + ", ".join(sorted(expected_columns))
            )
        for raw in reader:
            reference = str(raw.get("reference") or "").strip()
            domain = str(raw.get("domain") or "").strip()
            scene_id = str(raw.get("scene_id") or "").strip()
            region = str(raw.get("region") or "").strip()
            if not reference or reference in seen:
                raise PhotoIdentityFineIdentityReviewManifestError("fine-identity evidence reference is empty or duplicated")
            if domain not in REQUIRED_DOMAINS:
                raise PhotoIdentityFineIdentityReviewManifestError(f"unsupported fine-identity domain: {domain or 'empty'}")
            if not scene_id or not region:
                raise PhotoIdentityFineIdentityReviewManifestError("fine-identity scene/region is missing")
            try:
                source_ordinal = int(str(raw.get("source_ordinal") or ""))
            except ValueError as exc:
                raise PhotoIdentityFineIdentityReviewManifestError("fine-identity source ordinal is invalid") from exc
            source_meta = sources_by_ordinal.get(source_ordinal)
            if source_ordinal < 1 or not isinstance(source_meta, Mapping):
                raise PhotoIdentityFineIdentityReviewManifestError("fine-identity source ordinal is outside the exact sweep")
            if str(source_meta.get("scene_id") or "") != scene_id:
                raise PhotoIdentityFineIdentityReviewManifestError(
                    "fine-identity scene id does not match exact sweep source binding"
                )
            source = Path(str(source_meta.get("path") or "")).expanduser().resolve()
            review = Path(str(raw.get("review_image_path") or "")).expanduser().resolve()
            source_sha = _sha256(source)
            review_sha = _sha256(review)
            if source_sha == review_sha:
                raise PhotoIdentityFineIdentityReviewManifestError("source media and review image SHA unexpectedly match")
            entries.append(
                {
                    "reference": reference,
                    "domain": domain,
                    "scene_id": scene_id,
                    "region": region,
                    "source_ordinal": source_ordinal,
                    "source_media_path": str(source),
                    "source_media_sha256": source_sha,
                    "review_image_path": str(review),
                    "review_image_sha256": review_sha,
                    "source_quality": _quality(raw.get("source_quality")),
                }
            )
            seen.add(reference)
            scenes[domain].add(scene_id)

    for domain, minimum in REQUIRED_DOMAINS.items():
        if len(scenes[domain]) < minimum:
            raise PhotoIdentityFineIdentityReviewManifestError(
                f"{domain} requires at least {minimum} distinct source scenes"
            )

    marker_inventory = marker_inventory.expanduser().resolve()
    marker_refs = {item["reference"] for item in entries if item["domain"] == "distinctive_markers_detail"}
    _validate_marker_inventory(marker_inventory, allowed_source_refs=marker_refs)
    manifest = {
        "format": PRIVATE_FORMAT,
        "version": PRIVATE_VERSION,
        "performer_id": performer_id,
        "bodyrig_revision": revision,
        "anatomy_observation_evidence_sha256": _sha256(anatomy_obs),
        "anatomy_sufficiency_report_sha256": _sha256(anatomy_report),
        "marker_inventory_path": str(marker_inventory),
        "marker_inventory_sha256": _sha256(marker_inventory),
        "entries": sorted(entries, key=lambda item: (item["domain"], item["scene_id"], item["reference"])),
    }
    _write_create_only(output.expanduser().resolve(), manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a private hash-bound fine-identity review manifest from reviewed source evidence.")
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--evidence-csv", required=True)
    parser.add_argument("--marker-inventory", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_private_review_manifest(
            sweep_root=Path(args.sweep_root),
            evidence_csv=Path(args.evidence_csv),
            marker_inventory=Path(args.marker_inventory),
            output=Path(args.output),
        )
    except (OSError, PhotoIdentityFineIdentityReviewManifestError) as exc:
        print(f"BodyRig fine-identity review manifest: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "BodyRig fine-identity review manifest: READY | "
        f"entries={len(result['entries'])} | domains={len(REQUIRED_DOMAINS)} | private=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
