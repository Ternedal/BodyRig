from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_multiperformer_target_attestation import (
    FORMAT as ISOLATION_ATTESTATION_FORMAT,
    POLICY as ISOLATION_ATTESTATION_POLICY,
    VERSION as ISOLATION_ATTESTATION_VERSION,
)
from .photoidentity_multiperformer_target_isolation import (
    FORMAT as CANDIDATE_FORMAT,
    PRIVATE_FORMAT as PRIVATE_CANDIDATE_FORMAT,
    PRIVATE_VERSION as PRIVATE_CANDIDATE_VERSION,
    VERSION as CANDIDATE_VERSION,
)
from .photoidentity_openpose_runner import PhotoIdentityOpenPoseRunnerError, _png_size, _run_openpose
from .photoidentity_schp_preflight import PhotoIdentitySchpPreflightError, inspect_runtime
from .photoidentity_target_crop_detail import (
    SUPPORTED_DOMAINS,
    PhotoIdentityTargetCropDetailError,
    analyze_openpose_target_crop,
)

FORMAT = "bodyrig-photoidentity-target-crop-detail-enrichment"
VERSION = 1
PRIVATE_FORMAT = "bodyrig-photoidentity-private-target-crop-detail-enrichment"
PRIVATE_VERSION = 1


class PhotoIdentityTargetCropEnrichError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityTargetCropEnrichError(f"required target-crop evidence is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotoIdentityTargetCropEnrichError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityTargetCropEnrichError(f"{label} must be a JSON object")
    return value


def _canonical_revision(value: object) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentityTargetCropEnrichError("target-crop enrichment requires exact BodyRig Git revision")
    return revision


def _row_map(rows: object, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise PhotoIdentityTargetCropEnrichError(f"{label} samples are invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityTargetCropEnrichError(f"{label} sample row is invalid")
        sample_id = str(raw.get("sample_id") or "")
        if not sample_id.startswith("targetsample-") or sample_id in result:
            raise PhotoIdentityTargetCropEnrichError(f"{label} sample id is invalid/duplicate")
        result[sample_id] = dict(raw)
    return result


def _load_authority(candidate_root: Path, revision: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    public_path = candidate_root / "multiperformer-target-isolation-candidates.json"
    private_path = candidate_root / "private-target-source" / "private-target-source-index.json"
    receipt_path = candidate_root / "photoidentity-multiperformer-target-isolation-attestation.json"
    public = _read_json(public_path, label="Target-isolation candidate manifest")
    private = _read_json(private_path, label="Private target-isolation index")
    receipt = _read_json(receipt_path, label="Human target-isolation attestation")

    if public.get("format") != CANDIDATE_FORMAT or public.get("version") != CANDIDATE_VERSION:
        raise PhotoIdentityTargetCropEnrichError("target-isolation candidate format/version is invalid")
    if private.get("format") != PRIVATE_CANDIDATE_FORMAT or private.get("version") != PRIVATE_CANDIDATE_VERSION:
        raise PhotoIdentityTargetCropEnrichError("private target-isolation format/version is invalid")
    if (
        receipt.get("format") != ISOLATION_ATTESTATION_FORMAT
        or receipt.get("version") != ISOLATION_ATTESTATION_VERSION
        or receipt.get("policy") != ISOLATION_ATTESTATION_POLICY
    ):
        raise PhotoIdentityTargetCropEnrichError("human target-isolation receipt format/version/policy is invalid")
    for item in (public, private, receipt):
        if str(item.get("bodyrig_revision") or "") != revision:
            raise PhotoIdentityTargetCropEnrichError("target-crop authority chain belongs to a different BodyRig revision")
    if receipt.get("candidate_manifest_sha256") != _sha256_file(public_path):
        raise PhotoIdentityTargetCropEnrichError("human isolation receipt is not bound to candidate manifest bytes")
    if receipt.get("private_candidate_index_sha256") != _sha256_file(private_path):
        raise PhotoIdentityTargetCropEnrichError("human isolation receipt is not bound to private candidate index bytes")
    if public.get("private_target_source_index_sha256") != _sha256_file(private_path):
        raise PhotoIdentityTargetCropEnrichError("public/private target-crop candidate binding changed")
    for field in ("performer_id", "scene_id", "source_media_sha256", "track_candidate_id", "selected_track_id"):
        if public.get(field) != private.get(field) or receipt.get(field) != public.get(field):
            raise PhotoIdentityTargetCropEnrichError(f"target-crop authority chain differs on {field}")
    if (
        receipt.get("human_target_isolation_attested") is not True
        or receipt.get("cross_person_contamination_absent_attested") is not True
        or receipt.get("authority_scope") != "accepted-samples-only"
        or receipt.get("target_isolated_source_authority") is not True
    ):
        raise PhotoIdentityTargetCropEnrichError("target-crop enrichment lacks accepted-samples-only human isolation authority")
    for field in ("photoidentity_source_evidence_authority", "reconstruction_permitted", "production_activation"):
        if receipt.get(field) is not False:
            raise PhotoIdentityTargetCropEnrichError(f"human target-isolation receipt crossed downstream boundary: {field}")
    return public, private, receipt, receipt_path


def _run_schp(*, runtime_python: Path, repo_root: Path, model_path: Path, crop: Path) -> list[dict[str, object]]:
    environment = os.environ.copy()
    previous = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(repo_root) + (os.pathsep + previous if previous else "")
    try:
        completed = subprocess.run(
            [str(runtime_python), "-m", "bodyrig.photoidentity_target_crop_schp_infer", "--model", str(model_path), "--image", str(crop)],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
            timeout=300,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PhotoIdentityTargetCropEnrichError("target-crop SCHP inference could not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
        raise PhotoIdentityTargetCropEnrichError(f"target-crop SCHP inference failed: {detail}")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise PhotoIdentityTargetCropEnrichError("target-crop SCHP inference polluted its JSON output channel")
    try:
        value = json.loads(lines[0], parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (json.JSONDecodeError, ValueError) as exc:
        raise PhotoIdentityTargetCropEnrichError("target-crop SCHP inference returned invalid JSON") from exc
    if not isinstance(value, list):
        raise PhotoIdentityTargetCropEnrichError("target-crop SCHP inference result must be a list")
    return [dict(item) for item in value if isinstance(item, Mapping)]


def enrich_target_crops(
    *,
    candidate_root: Path,
    output_dir: Path,
    current_revision: str,
    distribution: str,
    openpose: str,
    wsl_exe: str,
    schp_runtime_root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    revision = _canonical_revision(current_revision)
    root = candidate_root.expanduser().resolve()
    out = output_dir.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    if not root.is_dir() or not repo_root.is_dir():
        raise PhotoIdentityTargetCropEnrichError("target-crop candidate/repository root is missing")
    if out.exists():
        raise PhotoIdentityTargetCropEnrichError(f"target-crop enrichment output already exists: {out}")
    if not str(distribution or "").strip() or not str(openpose or "").startswith("/"):
        raise PhotoIdentityTargetCropEnrichError("pinned OpenPose runtime is incomplete")

    public, private, receipt, receipt_path = _load_authority(root, revision)
    public_map = _row_map(public.get("samples"), label="public target-crop")
    private_map = _row_map(private.get("samples"), label="private target-crop")
    accepted_map = _row_map(receipt.get("accepted_samples"), label="human-accepted target-crop")
    if not set(accepted_map).issubset(public_map) or not set(accepted_map).issubset(private_map):
        raise PhotoIdentityTargetCropEnrichError("human-accepted target sample disappeared from candidate evidence")
    if len(accepted_map) != int(receipt.get("accepted_sample_count") or -1):
        raise PhotoIdentityTargetCropEnrichError("human-accepted target sample count changed")

    try:
        schp = inspect_runtime(schp_runtime_root)
    except PhotoIdentitySchpPreflightError as exc:
        raise PhotoIdentityTargetCropEnrichError(f"pinned SCHP runtime failed preflight: {exc}") from exc
    runtime_python = Path(str(schp["runtime_python"])).resolve()
    model_path = Path(str(schp["model_path"])).resolve()

    out.mkdir(parents=True, exist_ok=False)
    private_out = out / "private-analysis"
    private_out.mkdir()
    results: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    domain_counts = {domain: 0 for domain in sorted(SUPPORTED_DOMAINS)}
    domain_best = {domain: 0.0 for domain in sorted(SUPPORTED_DOMAINS)}
    try:
        for sample_id in sorted(accepted_map):
            public_row = public_map[sample_id]
            private_row = private_map[sample_id]
            accepted_row = accepted_map[sample_id]
            source_crop = Path(str(private_row.get("target_track_crop") or "")).expanduser().resolve()
            expected_sha = str(public_row.get("target_crop_sha256") or "")
            if expected_sha != str(accepted_row.get("target_crop_sha256") or "") or _sha256_file(source_crop) != expected_sha:
                raise PhotoIdentityTargetCropEnrichError("accepted target-crop bytes changed after human isolation attestation")

            sample_root = private_out / sample_id
            sample_root.mkdir()
            crop = sample_root / "accepted-target-crop.png"
            shutil.copyfile(source_crop, crop)
            if _sha256_file(crop) != expected_sha:
                raise PhotoIdentityTargetCropEnrichError("private analysis copy changed accepted target-crop bytes")
            width, height = _png_size(crop)

            try:
                openpose_payload = _run_openpose(frame=crop, distribution=distribution, openpose=openpose, wsl_exe=wsl_exe)
                openpose_candidates = analyze_openpose_target_crop(openpose_payload, width=width, height=height)
            except (PhotoIdentityOpenPoseRunnerError, PhotoIdentityTargetCropDetailError) as exc:
                raise PhotoIdentityTargetCropEnrichError(f"target-crop OpenPose analysis failed: {exc}") from exc
            schp_candidates = _run_schp(runtime_python=runtime_python, repo_root=repo_root, model_path=model_path, crop=crop)
            candidates = [*openpose_candidates, *schp_candidates]
            normalized: list[dict[str, Any]] = []
            for raw in candidates:
                domain = str(raw.get("domain") or "")
                if domain not in SUPPORTED_DOMAINS:
                    raise PhotoIdentityTargetCropEnrichError(f"target-crop analyzer overclaimed unsupported domain: {domain}")
                score = raw.get("machine_observability_score")
                if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0:
                    raise PhotoIdentityTargetCropEnrichError("target-crop analyzer returned invalid observability score")
                if raw.get("source_derived") is not True or raw.get("source_detail_quality_authority") is not False or raw.get("photoidentity_sufficiency_authority") is not False:
                    raise PhotoIdentityTargetCropEnrichError("target-crop analyzer crossed machine-candidate authority boundary")
                row = {**dict(raw), "sample_id": sample_id, "scene_id": str(receipt["scene_id"]), "target_crop_sha256": expected_sha}
                normalized.append(row)
                domain_counts[domain] += 1
                domain_best[domain] = max(domain_best[domain], float(score))
            results.append({"sample_id": sample_id, "scene_id": str(receipt["scene_id"]), "target_crop_sha256": expected_sha, "native_crop_width": width, "native_crop_height": height, "candidates": normalized})
            private_rows.append({"sample_id": sample_id, "analysis_crop": str(crop), "openpose_keypoints": str(crop.with_name(f"{crop.stem}_keypoints.json"))})

        private_index = {
            "format": PRIVATE_FORMAT,
            "version": PRIVATE_VERSION,
            "bodyrig_revision": revision,
            "performer_id": str(receipt["performer_id"]),
            "scene_id": str(receipt["scene_id"]),
            "rows": private_rows,
            "source_paths_private": True,
            "production_activation": False,
        }
        private_path = private_out / "private-analysis-index.json"
        private_path.write_text(json.dumps(private_index, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        public_receipt = {
            "format": FORMAT,
            "version": VERSION,
            "bodyrig_revision": revision,
            "performer_id": str(receipt["performer_id"]),
            "scene_id": str(receipt["scene_id"]),
            "source_media_sha256": str(receipt["source_media_sha256"]),
            "human_target_isolation_attestation_sha256": _sha256_file(receipt_path),
            "accepted_sample_count": len(results),
            "supported_domains": sorted(SUPPORTED_DOMAINS),
            "domain_candidate_counts": domain_counts,
            "domain_best_machine_observability_score": {key: round(value, 4) for key, value in domain_best.items()},
            "samples": results,
            "private_analysis_index_sha256": _sha256_file(private_path),
            "machine_observability_only": True,
            "source_detail_quality_authority": False,
            "photoidentity_source_evidence_authority": False,
            "reconstruction_permitted": False,
            "human_review_render_permitted": False,
            "generic_guessing_permitted": False,
            "production_activation": False,
        }
        public_path = out / "target-crop-detail-enrichment.json"
        public_path.write_text(json.dumps(public_receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        return {**public_receipt, "receipt": str(public_path), "receipt_sha256": _sha256_file(public_path)}
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run pinned source-only detail analyzers over human-accepted target-isolated crops.")
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--current-revision", required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--openpose", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--schp-runtime-root", required=True)
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = enrich_target_crops(
            candidate_root=Path(args.candidate_root), output_dir=Path(args.output_dir), current_revision=args.current_revision,
            distribution=args.distribution, openpose=args.openpose, wsl_exe=args.wsl_exe,
            schp_runtime_root=Path(args.schp_runtime_root), repo_root=Path(args.repo_root),
        )
    except (OSError, ValueError, PhotoIdentityTargetCropEnrichError) as exc:
        print(f"BodyRig target-crop detail enrichment: FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"BodyRig target-crop detail enrichment: PASS | samples={result['accepted_sample_count']} | machine_observability_only=true")
    for domain in sorted(SUPPORTED_DOMAINS):
        print(f"{domain}: candidates={result['domain_candidate_counts'][domain]} best={result['domain_best_machine_observability_score'][domain]:.4f}")
    print(f"Evidence: {result['receipt']}")
    print("Photoidentity source sufficiency authority: FALSE")
    print("Reconstruction permitted: FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
