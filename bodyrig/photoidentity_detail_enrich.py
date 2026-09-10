from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .observation import load_stash_source_manifest
from .photoidentity_evidence import (
    PhotoIdentityEvidenceError,
    build_observation_evidence,
    validate_bundle,
    write_bundle,
)
from .photoidentity_openpose_detail import ADAPTER as DETAIL_ADAPTER
from .photoidentity_openpose_detail import CAPABILITIES as DETAIL_CAPABILITIES
from .photoidentity_openpose_detail import REVISION as DETAIL_REVISION
from .photoidentity_openpose_runner import (
    PhotoIdentityOpenPoseRunnerError,
    collect_openpose_detail_evidence,
)

FORMAT = "bodyrig-photoidentity-detail-enrichment"
VERSION = 1
COMPOSITE_ADAPTER = "bodyrig-photoidentity-coarse-openpose-composite"
COMPOSITE_REVISION = "1"


class PhotoIdentityDetailEnrichError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityDetailEnrichError(f"required evidence file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityDetailEnrichError(f"{label} is unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityDetailEnrichError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityDetailEnrichError(f"detail enrichment receipt already exists: {path}")
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


def _private_source_bindings(sweep_root: Path, *, expected_count: int) -> tuple[dict[int, dict[str, Any]], str]:
    private = sweep_root / "private-batches"
    if not private.is_dir():
        raise PhotoIdentityDetailEnrichError("coarse sweep private-batches workspace is missing")
    manifests = sorted(private.glob("batch-*/bodyrig-stash-source-manifest.json"))
    if not manifests:
        raise PhotoIdentityDetailEnrichError("coarse sweep has no private source manifests")

    sources: dict[int, dict[str, Any]] = {}
    manifest_hashes: list[str] = []
    ordinal = 0
    for manifest_path in manifests:
        try:
            _, normalized, _ = load_stash_source_manifest(manifest_path)
        except Exception as exc:
            raise PhotoIdentityDetailEnrichError(
                f"private coarse source manifest is no longer valid: {manifest_path}"
            ) from exc
        manifest_hashes.append(_sha256(manifest_path))
        for source in normalized:
            ordinal += 1
            sources[ordinal] = {
                "scene_id": str(source["scene_id"]),
                "path": str(source["path"]),
            }
    if len(sources) != expected_count:
        raise PhotoIdentityDetailEnrichError(
            f"private source binding count changed: expected {expected_count}, got {len(sources)}"
        )
    set_digest = hashlib.sha256("\n".join(manifest_hashes).encode("ascii")).hexdigest()
    return sources, set_digest


def _merge_details(
    existing: Mapping[str, Any],
    openpose: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for domain, claims in existing.items():
        if not isinstance(claims, list):
            raise PhotoIdentityDetailEnrichError(f"existing detail evidence for {domain} is invalid")
        result[str(domain)] = [dict(item) for item in claims if isinstance(item, Mapping)]
    for domain, claims in openpose.items():
        bucket = result.setdefault(str(domain), [])
        by_scene = {
            str(item.get("scene_id") or ""): dict(item)
            for item in bucket
            if isinstance(item, Mapping) and item.get("scene_id")
        }
        for raw in claims:
            if not isinstance(raw, Mapping):
                continue
            claim = dict(raw)
            scene = str(claim.get("scene_id") or "")
            current = by_scene.get(scene)
            if current is None or float(claim.get("quality", 0.0)) > float(current.get("quality", 0.0)):
                by_scene[scene] = claim
        result[str(domain)] = sorted(
            by_scene.values(), key=lambda item: (-float(item.get("quality", 0.0)), str(item.get("scene_id") or ""))
        )
    return result


def enrich_sweep(
    *,
    sweep_root: Path,
    ffmpeg: str,
    distribution: str,
    openpose: str,
    wsl_exe: str,
) -> dict[str, Any]:
    sweep_root = sweep_root.expanduser().resolve()
    if not sweep_root.is_dir():
        raise PhotoIdentityDetailEnrichError("photoidentity coarse sweep root is missing")
    coarse_observations_path = sweep_root / "evidence" / "photoidentity-observations.json"
    coarse_report_path = sweep_root / "evidence" / "photoidentity-evidence.json"
    try:
        coarse_report = validate_bundle(coarse_report_path, coarse_observations_path)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityDetailEnrichError(f"coarse photoidentity evidence is invalid: {exc}") from exc
    coarse_observations = _read_json(coarse_observations_path, label="Coarse photoidentity observations")

    source_count = int(coarse_report["source_files_scanned"])
    sources_by_ordinal, private_manifest_set_sha256 = _private_source_bindings(
        sweep_root,
        expected_count=source_count,
    )
    private_detail_root = sweep_root / "private-openpose-detail"
    detail_evidence = collect_openpose_detail_evidence(
        rows=list(coarse_observations["rows"]),
        sources_by_ordinal=sources_by_ordinal,
        private_root=private_detail_root,
        ffmpeg=ffmpeg,
        distribution=distribution,
        openpose=openpose,
        wsl_exe=wsl_exe,
    )

    existing_analyzer = coarse_observations["analyzer"]
    capabilities = sorted(
        {
            *[str(item) for item in existing_analyzer.get("capabilities", [])],
            *DETAIL_CAPABILITIES,
        }
    )
    merged_details = _merge_details(
        coarse_observations.get("detail_evidence", {}),
        detail_evidence,
    )
    enriched = build_observation_evidence(
        performer_id=str(coarse_observations["performer_id"]),
        bodyrig_revision=str(coarse_observations["bodyrig_revision"]),
        baseline_source_manifest_sha256=str(coarse_observations["baseline_source_manifest_sha256"]),
        analyzer_adapter=COMPOSITE_ADAPTER,
        analyzer_revision=COMPOSITE_REVISION,
        analyzer_capabilities=capabilities,
        candidate_scenes=int(coarse_observations["candidate_scenes"]),
        source_files_scanned=source_count,
        scan_exhausted=bool(coarse_observations["scan_exhausted"]),
        rows=list(coarse_observations["rows"]),
        detail_evidence=merged_details,
    )

    enriched_observations_path, enriched_report_path, enriched_report = write_bundle(
        sweep_root / "detail-evidence",
        enriched,
    )
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": enriched_report["performer_id"],
        "bodyrig_revision": enriched_report["bodyrig_revision"],
        "baseline_source_manifest_sha256": enriched_report["baseline_source_manifest_sha256"],
        "coarse_observation_evidence_sha256": _sha256(coarse_observations_path),
        "coarse_sufficiency_report_sha256": _sha256(coarse_report_path),
        "private_source_manifest_set_sha256": private_manifest_set_sha256,
        "detail_analyzer": {
            "adapter": DETAIL_ADAPTER,
            "revision": DETAIL_REVISION,
            "capabilities": list(DETAIL_CAPABILITIES),
        },
        "composite_analyzer": {
            "adapter": COMPOSITE_ADAPTER,
            "revision": COMPOSITE_REVISION,
            "capabilities": capabilities,
        },
        "detail_claim_counts": {
            domain: len(claims)
            for domain, claims in sorted(detail_evidence.items())
        },
        "enriched_observation_evidence": str(enriched_observations_path),
        "enriched_observation_evidence_sha256": _sha256(enriched_observations_path),
        "enriched_sufficiency_report": str(enriched_report_path),
        "enriched_sufficiency_report_sha256": _sha256(enriched_report_path),
        "source_paths_persisted": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": bool(enriched_report["reconstruction_permitted"]),
        "human_review_render_permitted": bool(enriched_report["human_review_render_permitted"]),
        "production_activation": False,
    }
    receipt_path = sweep_root / "photoidentity-openpose-detail-enrichment.json"
    _write_create_only(receipt_path, receipt)
    return {**receipt, "receipt": str(receipt_path), "report": enriched_report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enrich a coarse photoidentity Stash sweep with pinned source-derived OpenPose detail evidence."
    )
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--openpose", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        result = enrich_sweep(
            sweep_root=Path(args.sweep_root),
            ffmpeg=args.ffmpeg,
            distribution=args.distribution,
            openpose=args.openpose,
            wsl_exe=args.wsl_exe,
        )
    except (OSError, PhotoIdentityDetailEnrichError, PhotoIdentityOpenPoseRunnerError) as exc:
        print(f"BodyRig photoidentity OpenPose detail enrichment: FAIL: {exc}", file=sys.stderr)
        return 1

    report = result["report"]
    print(
        "BodyRig photoidentity OpenPose detail enrichment: PASS | "
        f"eyes={result['detail_claim_counts'].get('eyes_detail', 0)} | "
        f"hands={result['detail_claim_counts'].get('hands', 0)} | "
        f"feet={result['detail_claim_counts'].get('feet', 0)} | "
        f"source_sufficient={str(bool(report['source_evidence_sufficient'])).lower()}"
    )
    print(f"Enriched evidence: {result['enriched_sufficiency_report']}")
    print("Hair/skin/torso/nail authority is intentionally not synthesized by OpenPose.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
