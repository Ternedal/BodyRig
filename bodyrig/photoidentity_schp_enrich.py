from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_detail_enrich import _merge_details, _private_source_bindings
from .photoidentity_evidence import (
    PhotoIdentityEvidenceError,
    build_observation_evidence,
    validate_bundle,
    write_bundle,
)
from .photoidentity_schp_contract import (
    ADAPTER as SCHP_ADAPTER,
    ADAPTER_REVISION as SCHP_ADAPTER_REVISION,
    CAPABILITIES as SCHP_CAPABILITIES,
    MODEL_REVISION,
    MODEL_SHA256,
    UPSTREAM_REVISION,
)
from .photoidentity_schp_preflight import PhotoIdentitySchpPreflightError, inspect_runtime
from .photoidentity_schp_runner import PhotoIdentitySchpRunnerError, collect_schp_detail_evidence

FORMAT = "bodyrig-photoidentity-schp-enrichment"
VERSION = 1
COMPOSITE_ADAPTER = "bodyrig-photoidentity-coarse-openpose-schp-composite"
COMPOSITE_REVISION = "1"


class PhotoIdentitySchpEnrichError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentitySchpEnrichError(f"required SCHP enrichment evidence is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentitySchpEnrichError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentitySchpEnrichError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentitySchpEnrichError(f"SCHP enrichment receipt already exists: {path}")
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


def enrich_with_schp(
    *,
    sweep_root: Path,
    runtime_root: Path,
    ffmpeg: str,
    repo_root: Path,
) -> dict[str, Any]:
    sweep_root = sweep_root.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    if not sweep_root.is_dir() or not repo_root.is_dir():
        raise PhotoIdentitySchpEnrichError("SCHP enrichment sweep/repository root is missing")

    prior_observations_path = sweep_root / "detail-evidence" / "photoidentity-observations.json"
    prior_report_path = sweep_root / "detail-evidence" / "photoidentity-evidence.json"
    try:
        prior_report = validate_bundle(prior_report_path, prior_observations_path)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentitySchpEnrichError(f"OpenPose-enriched photoidentity evidence is invalid: {exc}") from exc
    prior_observations = _read_json(prior_observations_path, label="OpenPose-enriched photoidentity observations")

    try:
        runtime = inspect_runtime(runtime_root)
    except PhotoIdentitySchpPreflightError as exc:
        raise PhotoIdentitySchpEnrichError(f"SCHP runtime is not authoritative: {exc}") from exc
    runtime_python = Path(str(runtime["runtime_python"])).resolve()
    model_path = Path(str(runtime["model_path"])).resolve()
    runtime_receipt = Path(runtime_root).expanduser().resolve() / "runtime.json"

    source_count = int(prior_report["source_files_scanned"])
    try:
        sources_by_ordinal, private_manifest_set_sha256 = _private_source_bindings(
            sweep_root,
            expected_count=source_count,
        )
    except Exception as exc:
        raise PhotoIdentitySchpEnrichError(f"private source authority changed before SCHP enrichment: {exc}") from exc

    claims = collect_schp_detail_evidence(
        rows=list(prior_observations["rows"]),
        sources_by_ordinal=sources_by_ordinal,
        private_root=sweep_root / "private-schp-detail",
        ffmpeg=ffmpeg,
        runtime_python=runtime_python,
        model_path=model_path,
        repo_root=repo_root,
    )
    existing_analyzer = prior_observations.get("analyzer")
    if not isinstance(existing_analyzer, Mapping):
        raise PhotoIdentitySchpEnrichError("prior photoidentity analyzer authority is missing")
    capabilities = sorted(
        {
            *[str(item) for item in existing_analyzer.get("capabilities", [])],
            *SCHP_CAPABILITIES,
        }
    )
    merged_details = _merge_details(
        prior_observations.get("detail_evidence", {}),
        claims,
    )
    enriched = build_observation_evidence(
        performer_id=str(prior_observations["performer_id"]),
        bodyrig_revision=str(prior_observations["bodyrig_revision"]),
        baseline_source_manifest_sha256=str(prior_observations["baseline_source_manifest_sha256"]),
        analyzer_adapter=COMPOSITE_ADAPTER,
        analyzer_revision=COMPOSITE_REVISION,
        analyzer_capabilities=capabilities,
        candidate_scenes=int(prior_observations["candidate_scenes"]),
        source_files_scanned=source_count,
        scan_exhausted=bool(prior_observations["scan_exhausted"]),
        rows=list(prior_observations["rows"]),
        detail_evidence=merged_details,
    )
    observations_path, report_path, report = write_bundle(
        sweep_root / "human-parsing-evidence",
        enriched,
    )
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": report["performer_id"],
        "bodyrig_revision": report["bodyrig_revision"],
        "baseline_source_manifest_sha256": report["baseline_source_manifest_sha256"],
        "prior_observation_evidence_sha256": _sha256(prior_observations_path),
        "prior_sufficiency_report_sha256": _sha256(prior_report_path),
        "private_source_manifest_set_sha256": private_manifest_set_sha256,
        "schp_runtime_receipt_sha256": _sha256(runtime_receipt),
        "schp_model_sha256": MODEL_SHA256,
        "schp_model_revision": MODEL_REVISION,
        "schp_upstream_revision": UPSTREAM_REVISION,
        "schp_adapter": {
            "adapter": SCHP_ADAPTER,
            "revision": SCHP_ADAPTER_REVISION,
            "capabilities": list(SCHP_CAPABILITIES),
        },
        "composite_analyzer": {
            "adapter": COMPOSITE_ADAPTER,
            "revision": COMPOSITE_REVISION,
            "capabilities": capabilities,
        },
        "detail_claim_counts": {domain: len(items) for domain, items in sorted(claims.items())},
        "enriched_observation_evidence": str(observations_path),
        "enriched_observation_evidence_sha256": _sha256(observations_path),
        "enriched_sufficiency_report": str(report_path),
        "enriched_sufficiency_report_sha256": _sha256(report_path),
        "weights_redistributed_by_bodyrig": False,
        "source_paths_persisted": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": bool(report["reconstruction_permitted"]),
        "human_review_render_permitted": bool(report["human_review_render_permitted"]),
        "production_activation": False,
    }
    receipt_path = sweep_root / "photoidentity-schp-enrichment.json"
    _write_create_only(receipt_path, receipt)
    return {**receipt, "receipt": str(receipt_path), "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enrich photoidentity evidence with pinned SCHP hair/skin source observability."
    )
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = enrich_with_schp(
            sweep_root=Path(args.sweep_root),
            runtime_root=Path(args.runtime_root),
            ffmpeg=args.ffmpeg,
            repo_root=Path(args.repo_root),
        )
    except (OSError, PhotoIdentitySchpEnrichError, PhotoIdentitySchpRunnerError) as exc:
        print(f"BodyRig SCHP photoidentity enrichment: FAIL: {exc}", file=sys.stderr)
        return 1
    report = result["report"]
    print(
        "BodyRig SCHP photoidentity enrichment: PASS | "
        f"hair={result['detail_claim_counts'].get('hair_hairline', 0)} | "
        f"skin={result['detail_claim_counts'].get('skin_detail', 0)} | "
        f"source_sufficient={str(bool(report['source_evidence_sufficient'])).lower()}"
    )
    print(f"Enriched evidence: {result['enriched_sufficiency_report']}")
    print("Torso/chest, waist/hips, rear orientation and nail domains remain fail-closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
