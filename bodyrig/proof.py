from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .package import validate_bodyprint


class ProofError(ValueError):
    pass


def read_canonical_json(path: str | Path, *, label: str) -> Any:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ProofError(f"{label} not found: {resolved}")
    try:
        return json.loads(
            resolved.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProofError(f"{label} is not valid canonical JSON: {resolved}") from exc


def validate_recovery_proof(value: Any) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "source_count",
        "adapter",
        "revision",
        "track_id",
        "observed_frames",
        "bodyprint",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ProofError("recovery proof fields must match v1 exactly")
    if value["format"] != "bodyrig-recovery-proof" or value["version"] != 1:
        raise ProofError("unsupported recovery proof format/version")

    count = value["source_count"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise ProofError("source_count must be 1..10")
    for field, maximum in (("adapter", 80), ("revision", 160), ("track_id", 160)):
        item = value[field]
        if not isinstance(item, str) or not item or len(item) > maximum:
            raise ProofError(f"invalid {field}")
    observed = value["observed_frames"]
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 2:
        raise ProofError("observed_frames must be >= 2")

    bodyprint = validate_bodyprint(value["bodyprint"])

    def walk(item: Any) -> None:
        if isinstance(item, bool) or item is None or isinstance(item, str):
            return
        if isinstance(item, (int, float)):
            if not math.isfinite(float(item)):
                raise ProofError("recovery proof contains non-finite number")
            return
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
            return
        if isinstance(item, list):
            for child in item:
                walk(child)

    walk(bodyprint)
    return value


def load_recovery_proof(path: str | Path) -> dict[str, Any]:
    return validate_recovery_proof(read_canonical_json(path, label="recovery proof"))
