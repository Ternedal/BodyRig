from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .photoreal_identity_calibration_diagnostic import (
    FORMAT as DIAGNOSTIC_FORMAT,
    VERSION as DIAGNOSTIC_VERSION,
    PhotorealIdentityCalibrationDiagnosticError,
    build_identity_calibration_diagnostic_files,
)
from .stash_source import StashClient, StashSourceError, rank_sources


class PhotorealCalibrationUiError(RuntimeError):
    pass


_REQUIRED_DIAGNOSTIC_FILES = (
    "identity-bank.json",
    "identity-calibration-plan.json",
    "identity-calibration-extractor/output/negative-observations.json",
)
_AUTHORITY = {
    "diagnostic_only": True,
    "identity_matching_authority": False,
    "teacher_training_authorized": False,
    "photoreal_acceptance_authority": False,
    "production_activation": False,
}


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(token)
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealCalibrationUiError(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealCalibrationUiError(
            f"{label} must be a JSON object: {path}"
        )
    return value


def _utc_mtime(path: Path) -> str:
    stamp = path.stat().st_mtime
    return (
        datetime.fromtimestamp(stamp, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _declared_performer_id(run_root: Path) -> str | None:
    declarations: list[str] = []
    specs = (
        ("source-resume-receipt.json", "performer_id"),
        ("identity-bank.json", "performer_id"),
        ("identity-calibration-plan.json", "target_performer_id"),
        ("identity-calibration.json", "target_performer_id"),
        ("p0-status.json", "performer_id"),
    )
    for relative, field in specs:
        path = run_root / relative
        if not path.is_file():
            continue
        try:
            value = _read_json(path, label=relative)
        except PhotorealCalibrationUiError:
            continue
        raw = str(value.get(field) or "").strip()
        if raw:
            declarations.append(raw)
    if not declarations:
        return None
    unique = sorted(set(declarations))
    if len(unique) != 1:
        raise PhotorealCalibrationUiError(
            f"run has conflicting performer declarations: {run_root}"
        )
    return unique[0]


def list_performer_runs(
    data_root: str | os.PathLike[str],
    performer_id: str,
    *,
    limit: int | None = None,
) -> list[Path]:
    performer_id = str(performer_id).strip()
    if not performer_id:
        raise PhotorealCalibrationUiError("performer id is required")
    overnight = (
        Path(data_root).expanduser().resolve()
        / "photoreal-v2"
        / "overnight"
    )
    if not overnight.is_dir() or overnight.is_symlink():
        return []

    candidates: list[Path] = []
    for path in overnight.iterdir():
        if path.is_symlink() or not path.is_dir():
            continue
        if not path.name.startswith(f"performer-{performer_id}-"):
            continue
        candidates.append(path)
    candidates.sort(
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )

    valid: list[Path] = []
    for run_root in candidates:
        try:
            declared = _declared_performer_id(run_root)
        except PhotorealCalibrationUiError:
            continue
        if declared != performer_id:
            continue
        valid.append(run_root)
        if limit is not None and len(valid) >= max(0, int(limit)):
            break
    return valid


def find_latest_performer_run(
    data_root: str | os.PathLike[str],
    performer_id: str,
) -> Path | None:
    runs = list_performer_runs(data_root, performer_id, limit=1)
    return runs[0] if runs else None


def _stage13_summary(
    run_root: Path,
    performer_id: str,
) -> dict[str, Any]:
    path = run_root / "identity-calibration.json"
    if not path.is_file():
        return {
            "state": "not-run",
            "available": False,
            "message": "Stage 13 calibration artifact is not present.",
        }

    value = _read_json(path, label="identity calibration")
    if value.get("format") != "bodyrig-photoreal-identity-calibration":
        raise PhotorealCalibrationUiError(
            "identity calibration format is unsupported"
        )
    if value.get("version") != 1:
        raise PhotorealCalibrationUiError(
            "identity calibration version is unsupported"
        )
    if str(value.get("target_performer_id") or "") != performer_id:
        raise PhotorealCalibrationUiError(
            "identity calibration performer does not match Person binding"
        )

    authorized = value.get("identity_matching_authorized") is True
    blockers = value.get("calibration_blockers")
    if not isinstance(blockers, list):
        blockers = []
    state = "pass" if authorized else "blocked"
    return {
        "state": state,
        "available": True,
        "identity_matching_authorized": authorized,
        "match_threshold_calibrated":
            value.get("match_threshold_calibrated") is True,
        "match_threshold": value.get("match_threshold"),
        "observed_separation_margin":
            value.get("observed_separation_margin"),
        "minimum_required_separation_margin":
            value.get("minimum_required_separation_margin"),
        "positive_reference_count":
            value.get("positive_reference_count"),
        "positive_group_count": value.get("positive_group_count"),
        "negative_observation_count":
            value.get("negative_observation_count"),
        "negative_performer_count":
            value.get("negative_performer_count"),
        "negative_ceiling":
            value.get("negative_to_target_centroid_cosine_max"),
        "positive_floor":
            value.get("positive_leave_group_out_cosine_min"),
        "blockers": [str(item) for item in blockers],
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _diagnostic_summary(
    run_root: Path,
    performer_id: str,
) -> dict[str, Any] | None:
    path = run_root / "identity-calibration-diagnostic.json"
    if not path.is_file():
        return None
    value = _read_json(path, label="identity calibration diagnostic")
    if (
        value.get("format") != DIAGNOSTIC_FORMAT
        or value.get("version") != DIAGNOSTIC_VERSION
    ):
        raise PhotorealCalibrationUiError(
            "identity calibration diagnostic format/version is unsupported"
        )
    if str(value.get("target_performer_id") or "") != performer_id:
        raise PhotorealCalibrationUiError(
            "identity calibration diagnostic performer mismatch"
        )
    return value


def _diagnostic_ready(run_root: Path) -> tuple[bool, list[str]]:
    missing = [
        relative
        for relative in _REQUIRED_DIAGNOSTIC_FILES
        if not (run_root / relative).is_file()
    ]
    return not missing, missing


def _stash_context(
    client: StashClient | None,
    performer_id: str,
) -> dict[str, Any]:
    if client is None:
        return {
            "available": False,
            "reason": "Stash is not configured for the BodyRig service.",
        }
    try:
        version = client.version()
        performer = client.performer(performer_id)
        scenes = client.scenes_for_performer(performer_id, limit=200)
        ranked = rank_sources(
            scenes,
            performer_id=performer_id,
            max_sources=5,
            require_local=True,
        )
    except StashSourceError as exc:
        return {
            "available": False,
            "reason": str(exc),
        }

    single = 0
    multi = 0
    file_count = 0
    four_k_files = 0
    for scene in scenes:
        performers = scene.get("performers") or []
        performer_ids = {
            str(item.get("id"))
            for item in performers
            if isinstance(item, Mapping)
            and item.get("id") is not None
        }
        if len(performer_ids) == 1:
            single += 1
        elif len(performer_ids) > 1:
            multi += 1
        for file_info in scene.get("files") or []:
            if not isinstance(file_info, Mapping):
                continue
            file_count += 1
            try:
                height = int(float(file_info.get("height") or 0))
            except (TypeError, ValueError):
                height = 0
            if height >= 2160:
                four_k_files += 1

    return {
        "available": True,
        "version": version,
        "performer": performer,
        "scene_count_observed": len(scenes),
        "scene_query_limit": 200,
        "scene_count_may_be_truncated": len(scenes) >= 200,
        "single_performer_scene_count": single,
        "multi_performer_scene_count": multi,
        "file_count_observed": file_count,
        "four_k_file_count_observed": four_k_files,
        "top_local_sources": [item.to_json() for item in ranked],
    }


def inspect_person_calibration(
    profile: Mapping[str, Any],
    data_root: str | os.PathLike[str],
    *,
    stash_client: StashClient | None = None,
) -> dict[str, Any]:
    person_id = str(profile.get("person_id") or "")
    display_name = str(profile.get("display_name") or "")
    source = profile.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        return {
            "person_id": person_id,
            "display_name": display_name,
            "state": "unbound",
            "message": "Personen er ikke bundet til en Stash performer.",
            "performer": None,
            "stash": {
                "available": False,
                "reason": "No Stash performer binding.",
            },
            "run": None,
            "authority": dict(_AUTHORITY),
        }

    performer_id = str(source.get("performer_id") or "").strip()
    performer = {
        "id": performer_id,
        "name": str(source.get("performer_name") or ""),
        "disambiguation": str(source.get("disambiguation") or ""),
    }
    if not performer_id:
        raise PhotorealCalibrationUiError(
            "Person Stash performer binding has no performer id"
        )

    stash = _stash_context(stash_client, performer_id)
    run_root = find_latest_performer_run(data_root, performer_id)
    if run_root is None:
        return {
            "person_id": person_id,
            "display_name": display_name,
            "state": "no-run",
            "message": "Ingen lokal Photoreal V2 calibration-run fundet.",
            "performer": performer,
            "stash": stash,
            "run": None,
            "authority": dict(_AUTHORITY),
        }

    ready, missing = _diagnostic_ready(run_root)
    stage13 = _stage13_summary(run_root, performer_id)
    diagnostic = _diagnostic_summary(run_root, performer_id)
    state = (
        "diagnosed"
        if diagnostic is not None
        else str(stage13.get("state") or "run-found")
    )
    return {
        "person_id": person_id,
        "display_name": display_name,
        "state": state,
        "message": (
            "Read-only calibration diagnostic is available."
            if diagnostic is not None
            else "Photoreal calibration run found."
        ),
        "performer": performer,
        "stash": stash,
        "run": {
            "name": run_root.name,
            "path": str(run_root),
            "modified_utc": _utc_mtime(run_root),
            "stage13": stage13,
            "diagnostic": diagnostic,
            "diagnostic_available": diagnostic is not None,
            "diagnostic_ready": ready,
            "diagnostic_missing_artifacts": missing,
            "diagnostic_output_path": str(
                run_root / "identity-calibration-diagnostic.json"
            ),
        },
        "authority": dict(_AUTHORITY),
    }


def run_person_calibration_diagnostic(
    profile: Mapping[str, Any],
    data_root: str | os.PathLike[str],
    *,
    stash_client: StashClient | None = None,
) -> dict[str, Any]:
    source = profile.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        raise PhotorealCalibrationUiError(
            "Personen er ikke bundet til en Stash performer"
        )
    performer_id = str(source.get("performer_id") or "").strip()
    if not performer_id:
        raise PhotorealCalibrationUiError(
            "Person Stash performer binding has no performer id"
        )
    run_root = find_latest_performer_run(data_root, performer_id)
    if run_root is None:
        raise PhotorealCalibrationUiError(
            "Ingen lokal Photoreal V2 calibration-run fundet"
        )

    ready, missing = _diagnostic_ready(run_root)
    if not ready:
        raise PhotorealCalibrationUiError(
            "Calibration diagnostic mangler artifacts: "
            + ", ".join(missing)
        )

    output = run_root / "identity-calibration-diagnostic.json"
    if not output.exists():
        try:
            build_identity_calibration_diagnostic_files(
                run_root / "identity-bank.json",
                run_root / "identity-calibration-plan.json",
                run_root
                / "identity-calibration-extractor"
                / "output"
                / "negative-observations.json",
                output,
                top_matches=10,
            )
        except PhotorealIdentityCalibrationDiagnosticError as exc:
            raise PhotorealCalibrationUiError(str(exc)) from exc

    return inspect_person_calibration(
        profile,
        data_root,
        stash_client=stash_client,
    )
