from __future__ import annotations

from pathlib import Path
from typing import Any

from .photoidentity_authority import validate_authoritative_bundle
from .photoidentity_evidence import PhotoIdentityEvidenceError
from .photoidentity_multiperformer_detail_aggregate import (
    PhotoIdentityMultiDetailAggregateError,
    validate_multiperformer_detail_aggregation,
)
from . import json_io


class PhotoIdentityPriorError(RuntimeError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    return json_io.read_json_object(
        path,
        error=PhotoIdentityPriorError,
        unreadable=f"{label} is unreadable JSON",
        not_object=f"{label} must be a JSON object",
    )


def resolve_pre_nail_bundle(sweep_root: Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any], str]:
    sweep_root = sweep_root.expanduser().resolve()
    base_observations = sweep_root / "human-parsing-evidence" / "photoidentity-observations.json"
    base_report = sweep_root / "human-parsing-evidence" / "photoidentity-evidence.json"
    try:
        base = validate_authoritative_bundle(base_report, base_observations, require_sufficient=False)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityPriorError(f"base human-parsing photoidentity evidence is invalid: {exc}") from exc
    base_value = _read_json(base_observations, label="Base human-parsing photoidentity observations")

    try:
        aggregate = validate_multiperformer_detail_aggregation(sweep_root)
    except PhotoIdentityMultiDetailAggregateError as exc:
        raise PhotoIdentityPriorError(f"multi-performer detail prior is invalid: {exc}") from exc
    if aggregate is None:
        return base_observations, base_report, base_value, base, "human-parsing"

    observations_path = Path(aggregate["observations_path"]).resolve()
    report_path = Path(aggregate["report_path"]).resolve()
    observations = _read_json(observations_path, label="Multi-performer detail photoidentity observations")
    report = dict(aggregate["report"])
    if (
        str(report.get("performer_id") or "") != str(base["performer_id"])
        or str(report.get("bodyrig_revision") or "") != str(base["bodyrig_revision"])
        or str(report.get("baseline_source_manifest_sha256") or "") != str(base["baseline_source_manifest_sha256"])
    ):
        raise PhotoIdentityPriorError("multi-performer detail prior changed base performer/revision/source authority")
    return observations_path, report_path, observations, report, "multiperformer-detail"
