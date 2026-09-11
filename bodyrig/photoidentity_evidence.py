from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

OBSERVATION_FORMAT = "bodyrig-photoidentity-observation-evidence"
REPORT_FORMAT = "bodyrig-photoidentity-evidence-sufficiency"
VERSION = 1
SHA256_LENGTH = 64

# These are source-evidence requirements, not a claim that satisfying them alone
# guarantees a photo-identical reconstruction. They only prove that BodyRig has
# enough observable source material to proceed without silently substituting a
# generic human prior for identity-critical regions.
DOMAIN_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "face_front": {"capability": "coarse-face-view", "minimum_distinct_scenes": 2},
    "face_left_profile": {"capability": "coarse-face-view", "minimum_distinct_scenes": 1},
    "face_right_profile": {"capability": "coarse-face-view", "minimum_distinct_scenes": 1},
    "body_front": {"capability": "coarse-full-body-view", "minimum_distinct_scenes": 2},
    "body_left_profile": {"capability": "coarse-full-body-view", "minimum_distinct_scenes": 1},
    "body_right_profile": {"capability": "coarse-full-body-view", "minimum_distinct_scenes": 1},
    "body_rear": {"capability": "rear-body-view", "minimum_distinct_scenes": 1},
    "eyes_detail": {"capability": "eyes-detail", "minimum_distinct_scenes": 2},
    # `hair_hairline` is intentionally scalp/head hair + facial hairline only.
    # Eyebrows, facial hair and body hair are separate identity domains because
    # SCHP/ATR's generic Hair class cannot honestly prove them.
    "hair_hairline": {"capability": "hair-detail", "minimum_distinct_scenes": 2},
    "eyebrows_detail": {"capability": "eyebrows-detail", "minimum_distinct_scenes": 2},
    "facial_hair_detail": {"capability": "facial-hair-detail", "minimum_distinct_scenes": 2},
    "body_hair_detail": {"capability": "body-hair-detail", "minimum_distinct_scenes": 2},
    "skin_detail": {"capability": "skin-detail", "minimum_distinct_scenes": 2},
    "torso_chest": {"capability": "torso-chest-detail", "minimum_distinct_scenes": 2},
    "waist_hips": {"capability": "waist-hips-detail", "minimum_distinct_scenes": 2},
    "hands": {"capability": "hands-detail", "minimum_distinct_scenes": 2},
    "fingernails_detail": {"capability": "fingernails-detail", "minimum_distinct_scenes": 2},
    "feet": {"capability": "feet-detail", "minimum_distinct_scenes": 2},
    "toenails_detail": {"capability": "toenails-detail", "minimum_distinct_scenes": 2},
}

COARSE_FACE_THRESHOLD = {
    "target_confidence": 0.70,
    "face_visibility": 0.80,
    "sharpness": 0.62,
    "occlusion_max": 0.18,
}
COARSE_BODY_THRESHOLD = {
    "target_confidence": 0.68,
    "full_body_visibility": 0.78,
    "sharpness": 0.50,
    "occlusion_max": 0.22,
}
DETAIL_QUALITY_THRESHOLD = 0.80


class PhotoIdentityEvidenceError(ValueError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityEvidenceError(f"photoidentity evidence file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: object, *, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != SHA256_LENGTH or any(ch not in "0123456789abcdef" for ch in digest):
        raise PhotoIdentityEvidenceError(f"{label} is not a canonical SHA-256")
    return digest


def _revision(value: object) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentityEvidenceError("BodyRig revision is not an exact Git SHA")
    return revision


def _finite(value: object, *, label: str, minimum: float = 0.0, maximum: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentityEvidenceError(f"{label} is not numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise PhotoIdentityEvidenceError(f"{label} is outside {minimum}..{maximum}")
    return result


def _canonical_row(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "scene_id",
        "source_ordinal",
        "start_seconds",
        "duration_seconds",
        "target_confidence",
        "target_screen_fraction",
        "face_visibility",
        "full_body_visibility",
        "sharpness",
        "occlusion",
        "motion",
        "view",
    }
    if set(value) != required:
        raise PhotoIdentityEvidenceError("photoidentity observation row fields must match v1 exactly")
    scene_id = str(value.get("scene_id") or "").strip()
    if not scene_id or len(scene_id) > 256:
        raise PhotoIdentityEvidenceError("photoidentity observation scene id is invalid")
    ordinal = value.get("source_ordinal")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise PhotoIdentityEvidenceError("photoidentity source ordinal is invalid")
    start = value.get("start_seconds")
    duration = value.get("duration_seconds")
    if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(float(start)) or float(start) < 0.0:
        raise PhotoIdentityEvidenceError("photoidentity observation start is invalid")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(float(duration)) or not 1.0 <= float(duration) <= 12.0:
        raise PhotoIdentityEvidenceError("photoidentity observation duration is invalid")
    view = str(value.get("view") or "")
    if view not in {"front", "left_profile", "right_profile", "rear", "unknown"}:
        raise PhotoIdentityEvidenceError("photoidentity observation view is invalid")
    return {
        "scene_id": scene_id,
        "source_ordinal": ordinal,
        "start_seconds": round(float(start), 3),
        "duration_seconds": round(float(duration), 3),
        "target_confidence": _finite(value.get("target_confidence"), label="target_confidence"),
        "target_screen_fraction": _finite(value.get("target_screen_fraction"), label="target_screen_fraction"),
        "face_visibility": _finite(value.get("face_visibility"), label="face_visibility"),
        "full_body_visibility": _finite(value.get("full_body_visibility"), label="full_body_visibility"),
        "sharpness": _finite(value.get("sharpness"), label="sharpness"),
        "occlusion": _finite(value.get("occlusion"), label="occlusion"),
        "motion": _finite(value.get("motion"), label="motion"),
        "view": view,
    }


def _canonical_detail_claim(domain: str, value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"scene_id", "quality", "source_derived", "adapter", "revision"}
    if set(value) != required:
        raise PhotoIdentityEvidenceError(f"photoidentity detail claim fields for {domain} must match v1 exactly")
    scene_id = str(value.get("scene_id") or "").strip()
    adapter = str(value.get("adapter") or "").strip()
    revision = str(value.get("revision") or "").strip()
    if not scene_id or len(scene_id) > 256 or not adapter or len(adapter) > 80 or not revision or len(revision) > 160:
        raise PhotoIdentityEvidenceError(f"photoidentity detail claim identity for {domain} is invalid")
    if value.get("source_derived") is not True:
        raise PhotoIdentityEvidenceError(f"photoidentity detail claim for {domain} is not source-derived")
    return {
        "scene_id": scene_id,
        "quality": _finite(value.get("quality"), label=f"{domain} detail quality"),
        "source_derived": True,
        "adapter": adapter,
        "revision": revision,
    }


def build_observation_evidence(
    *,
    performer_id: str,
    bodyrig_revision: str,
    baseline_source_manifest_sha256: str,
    analyzer_adapter: str,
    analyzer_revision: str,
    analyzer_capabilities: Sequence[str],
    candidate_scenes: int,
    source_files_scanned: int,
    scan_exhausted: bool,
    rows: Sequence[Mapping[str, Any]],
    detail_evidence: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    performer = str(performer_id or "").strip()
    if not performer or len(performer) > 256:
        raise PhotoIdentityEvidenceError("photoidentity performer id is invalid")
    revision = _revision(bodyrig_revision)
    baseline_sha = _sha(baseline_source_manifest_sha256, label="baseline source manifest SHA-256")
    adapter = str(analyzer_adapter or "").strip()
    adapter_revision = str(analyzer_revision or "").strip()
    if not adapter or len(adapter) > 80 or not adapter_revision or len(adapter_revision) > 160:
        raise PhotoIdentityEvidenceError("photoidentity analyzer identity is invalid")
    capabilities = sorted({str(item).strip() for item in analyzer_capabilities if str(item).strip()})
    if any(len(item) > 80 for item in capabilities):
        raise PhotoIdentityEvidenceError("photoidentity analyzer capability is invalid")
    if isinstance(candidate_scenes, bool) or not isinstance(candidate_scenes, int) or candidate_scenes < 1:
        raise PhotoIdentityEvidenceError("photoidentity candidate scene count is invalid")
    if isinstance(source_files_scanned, bool) or not isinstance(source_files_scanned, int) or not 1 <= source_files_scanned <= 1000:
        raise PhotoIdentityEvidenceError("photoidentity scanned source count is invalid")
    if type(scan_exhausted) is not bool:
        raise PhotoIdentityEvidenceError("photoidentity scan exhaustion claim is invalid")

    normalized_rows = [_canonical_row(dict(item)) for item in rows]
    if not normalized_rows:
        raise PhotoIdentityEvidenceError("photoidentity sweep produced no usable observations")
    details: dict[str, list[dict[str, Any]]] = {}
    for domain, claims in (detail_evidence or {}).items():
        if domain not in DOMAIN_REQUIREMENTS:
            raise PhotoIdentityEvidenceError(f"unknown photoidentity detail domain: {domain}")
        details[domain] = [_canonical_detail_claim(domain, dict(item)) for item in claims]

    return {
        "format": OBSERVATION_FORMAT,
        "version": VERSION,
        "performer_id": performer,
        "bodyrig_revision": revision,
        "baseline_source_manifest_sha256": baseline_sha,
        "analyzer": {"adapter": adapter, "revision": adapter_revision, "capabilities": capabilities},
        "candidate_scenes": candidate_scenes,
        "source_files_scanned": source_files_scanned,
        "scan_exhausted": scan_exhausted,
        "rows": normalized_rows,
        "detail_evidence": details,
        "source_paths_persisted": False,
        "generic_guessing_permitted": False,
        "production_activation": False,
    }


def validate_observation_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "performer_id",
        "bodyrig_revision",
        "baseline_source_manifest_sha256",
        "analyzer",
        "candidate_scenes",
        "source_files_scanned",
        "scan_exhausted",
        "rows",
        "detail_evidence",
        "source_paths_persisted",
        "generic_guessing_permitted",
        "production_activation",
    }
    if set(value) != required or value.get("format") != OBSERVATION_FORMAT or value.get("version") != VERSION:
        raise PhotoIdentityEvidenceError("photoidentity observation evidence fields/format are invalid")
    analyzer = value.get("analyzer")
    if not isinstance(analyzer, Mapping) or set(analyzer) != {"adapter", "revision", "capabilities"}:
        raise PhotoIdentityEvidenceError("photoidentity analyzer block is invalid")
    if value.get("source_paths_persisted") is not False or value.get("generic_guessing_permitted") is not False or value.get("production_activation") is not False:
        raise PhotoIdentityEvidenceError("photoidentity observation authority boundary is invalid")
    return build_observation_evidence(
        performer_id=str(value.get("performer_id") or ""),
        bodyrig_revision=str(value.get("bodyrig_revision") or ""),
        baseline_source_manifest_sha256=str(value.get("baseline_source_manifest_sha256") or ""),
        analyzer_adapter=str(analyzer.get("adapter") or ""),
        analyzer_revision=str(analyzer.get("revision") or ""),
        analyzer_capabilities=list(analyzer.get("capabilities") or []),
        candidate_scenes=value.get("candidate_scenes"),
        source_files_scanned=value.get("source_files_scanned"),
        scan_exhausted=value.get("scan_exhausted"),
        rows=list(value.get("rows") or []),
        detail_evidence=value.get("detail_evidence") if isinstance(value.get("detail_evidence"), Mapping) else None,
    )


def _coarse_scene_ids(rows: Sequence[Mapping[str, Any]], domain: str) -> set[str]:
    if domain.startswith("face_"):
        expected_view = domain.removeprefix("face_")
        view = {"front": "front", "left_profile": "left_profile", "right_profile": "right_profile"}.get(expected_view)
        if view is None:
            return set()
        return {
            str(row["scene_id"])
            for row in rows
            if row["view"] == view
            and float(row["target_confidence"]) >= COARSE_FACE_THRESHOLD["target_confidence"]
            and float(row["face_visibility"]) >= COARSE_FACE_THRESHOLD["face_visibility"]
            and float(row["sharpness"]) >= COARSE_FACE_THRESHOLD["sharpness"]
            and float(row["occlusion"]) <= COARSE_FACE_THRESHOLD["occlusion_max"]
        }
    if domain.startswith("body_") and domain != "body_rear":
        expected_view = domain.removeprefix("body_")
        view = {"front": "front", "left_profile": "left_profile", "right_profile": "right_profile"}.get(expected_view)
        if view is None:
            return set()
        return {
            str(row["scene_id"])
            for row in rows
            if row["view"] == view
            and float(row["target_confidence"]) >= COARSE_BODY_THRESHOLD["target_confidence"]
            and float(row["full_body_visibility"]) >= COARSE_BODY_THRESHOLD["full_body_visibility"]
            and float(row["sharpness"]) >= COARSE_BODY_THRESHOLD["sharpness"]
            and float(row["occlusion"]) <= COARSE_BODY_THRESHOLD["occlusion_max"]
        }
    return set()


def evaluate_sufficiency(observation_evidence: Mapping[str, Any]) -> dict[str, Any]:
    evidence = validate_observation_evidence(observation_evidence)
    analyzer = evidence["analyzer"]
    capabilities = set(analyzer["capabilities"])
    rows = list(evidence["rows"])
    details = dict(evidence["detail_evidence"])
    domains: dict[str, dict[str, Any]] = {}

    for domain, requirement in DOMAIN_REQUIREMENTS.items():
        capability = str(requirement["capability"])
        minimum = int(requirement["minimum_distinct_scenes"])
        if capability not in capabilities:
            domains[domain] = {
                "status": "analyzer_cannot_prove",
                "required_capability": capability,
                "minimum_distinct_scenes": minimum,
                "qualifying_distinct_scenes": 0,
            }
            continue

        if capability in {"coarse-face-view", "coarse-full-body-view"}:
            scenes = _coarse_scene_ids(rows, domain)
        else:
            claims = details.get(domain, [])
            scenes = {
                str(item["scene_id"])
                for item in claims
                if float(item["quality"]) >= DETAIL_QUALITY_THRESHOLD and item.get("source_derived") is True
            }
        domains[domain] = {
            "status": "pass" if len(scenes) >= minimum else "source_missing",
            "required_capability": capability,
            "minimum_distinct_scenes": minimum,
            "qualifying_distinct_scenes": len(scenes),
        }

    analyzer_blockers = sorted(domain for domain, item in domains.items() if item["status"] == "analyzer_cannot_prove")
    source_blockers = sorted(domain for domain, item in domains.items() if item["status"] == "source_missing")
    sufficient = not analyzer_blockers and not source_blockers
    if analyzer_blockers:
        next_action = "upgrade_identity_analyzer"
    elif source_blockers and evidence["scan_exhausted"]:
        next_action = "acquire_more_source_media"
    elif source_blockers:
        next_action = "scan_additional_stash_sources"
    else:
        next_action = "source_evidence_ready_for_reconstruction"

    return {
        "format": REPORT_FORMAT,
        "version": VERSION,
        "performer_id": evidence["performer_id"],
        "bodyrig_revision": evidence["bodyrig_revision"],
        "baseline_source_manifest_sha256": evidence["baseline_source_manifest_sha256"],
        "analyzer": analyzer,
        "candidate_scenes": evidence["candidate_scenes"],
        "source_files_scanned": evidence["source_files_scanned"],
        "scan_exhausted": evidence["scan_exhausted"],
        "domains": domains,
        "analyzer_blockers": analyzer_blockers,
        "source_blockers": source_blockers,
        "source_evidence_sufficient": sufficient,
        "reconstruction_permitted": sufficient,
        "human_review_render_permitted": sufficient,
        "generic_guessing_permitted": False,
        "next_action": next_action,
        "production_activation": False,
    }


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise PhotoIdentityEvidenceError(f"photoidentity evidence output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_bundle(output_dir: str | Path, observation_evidence: Mapping[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise PhotoIdentityEvidenceError(f"photoidentity evidence directory already exists: {output}")
    output.mkdir(parents=True, exist_ok=False)
    observations_path = output / "photoidentity-observations.json"
    report_path = output / "photoidentity-evidence.json"
    evidence = validate_observation_evidence(observation_evidence)
    _write_create_only(observations_path, evidence)
    report = evaluate_sufficiency(evidence)
    report = {**report, "observation_evidence_sha256": _sha256(observations_path)}
    _write_create_only(report_path, report)
    return observations_path, report_path, report


def validate_bundle(
    report_path: str | Path,
    observation_path: str | Path | None = None,
    *,
    require_sufficient: bool = False,
    expected_performer_id: str | None = None,
    expected_bodyrig_revision: str | None = None,
    expected_baseline_source_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    report_file = Path(report_path).expanduser().resolve()
    if not report_file.is_file():
        raise PhotoIdentityEvidenceError("photoidentity sufficiency report is missing")
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityEvidenceError("photoidentity sufficiency report is invalid JSON") from exc
    if not isinstance(report, dict) or report.get("format") != REPORT_FORMAT or report.get("version") != VERSION:
        raise PhotoIdentityEvidenceError("photoidentity sufficiency report format/version is invalid")
    observations_file = (
        Path(observation_path).expanduser().resolve()
        if observation_path is not None
        else report_file.with_name("photoidentity-observations.json")
    )
    if _sha256(observations_file) != _sha(report.get("observation_evidence_sha256"), label="photoidentity observation evidence SHA-256"):
        raise PhotoIdentityEvidenceError("photoidentity report does not bind exact observation evidence bytes")
    try:
        raw_observations = json.loads(observations_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityEvidenceError("photoidentity observation evidence is invalid JSON") from exc
    if not isinstance(raw_observations, dict):
        raise PhotoIdentityEvidenceError("photoidentity observation evidence must be an object")
    expected_report = {**evaluate_sufficiency(raw_observations), "observation_evidence_sha256": _sha256(observations_file)}
    if report != expected_report:
        raise PhotoIdentityEvidenceError("photoidentity sufficiency report is inconsistent with bound observation evidence")
    if expected_performer_id is not None and report["performer_id"] != str(expected_performer_id):
        raise PhotoIdentityEvidenceError("photoidentity report performer does not match requested authority")
    if expected_bodyrig_revision is not None and report["bodyrig_revision"] != _revision(expected_bodyrig_revision):
        raise PhotoIdentityEvidenceError("photoidentity report BodyRig revision does not match requested authority")
    if expected_baseline_source_manifest_sha256 is not None and report["baseline_source_manifest_sha256"] != _sha(
        expected_baseline_source_manifest_sha256,
        label="expected baseline source manifest SHA-256",
    ):
        raise PhotoIdentityEvidenceError("photoidentity report baseline source manifest binding mismatch")
    if require_sufficient and (
        report.get("source_evidence_sufficient") is not True
        or report.get("reconstruction_permitted") is not True
        or report.get("human_review_render_permitted") is not True
        or report.get("generic_guessing_permitted") is not False
        or report.get("production_activation") is not False
    ):
        raise PhotoIdentityEvidenceError(
            "photoidentity source evidence is insufficient; generic reconstruction/render remains blocked"
        )
    return report
