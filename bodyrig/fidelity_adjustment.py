from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

from .bodyprint_adjustment import BodyprintAdjustmentEvidenceError, build_adjustment_request

FORMAT = "bodyrig-fidelity-adjustment-plan"
VERSION = 1
SEMANTICS = "visual-fidelity-not-identity-verification"


class FidelityAdjustmentError(ValueError):
    pass


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _direction(value: Any, *, field: str) -> str:
    if value not in {"wider", "narrower", "hold"}:
        raise FidelityAdjustmentError(f"{field} is invalid")
    return str(value)


def build_fidelity_adjustment_plan(evaluation: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(evaluation, Mapping):
        raise FidelityAdjustmentError("fidelity evaluation must be an object")
    if evaluation.get("format") != "bodyrig-fidelity-evaluation" or evaluation.get("version") != 1:
        raise FidelityAdjustmentError("unsupported fidelity evaluation format/version")
    if evaluation.get("semantics") != SEMANTICS:
        raise FidelityAdjustmentError("fidelity evaluation semantics mismatch")
    measurement = evaluation.get("measurement")
    if not isinstance(measurement, Mapping):
        raise FidelityAdjustmentError("fidelity evaluation measurement is missing")
    scores = measurement.get("scores")
    if not isinstance(scores, Mapping):
        raise FidelityAdjustmentError("fidelity evaluation scores are missing")
    hint = evaluation.get("shape_hint")
    if hint is None:
        return {
            "format": FORMAT,
            "version": VERSION,
            "evaluation_sha256": _canonical_sha256(dict(evaluation)),
            "applicable": False,
            "feedback": "",
            "adjustment_request": None,
            "semantics": SEMANTICS,
        }
    if not isinstance(hint, Mapping) or set(hint) != {
        "shoulder_direction",
        "hip_direction",
        "shoulder_profile_delta",
        "hip_profile_delta",
    }:
        raise FidelityAdjustmentError("shape_hint fields must match evaluator v1 exactly")

    shoulder = _direction(hint.get("shoulder_direction"), field="shape_hint.shoulder_direction")
    hip = _direction(hint.get("hip_direction"), field="shape_hint.hip_direction")
    phrases: list[str] = []
    if shoulder == "wider":
        phrases.append("shoulders should be wider")
    elif shoulder == "narrower":
        phrases.append("shoulders should be narrower")
    if hip == "wider":
        phrases.append("hips should be wider")
    elif hip == "narrower":
        phrases.append("hips should be narrower")

    if not phrases:
        request = None
        feedback = ""
    else:
        feedback = "; ".join(phrases)
        try:
            request = build_adjustment_request(feedback)
        except BodyprintAdjustmentEvidenceError as exc:
            raise FidelityAdjustmentError(str(exc)) from exc
        allowed_fields = {"shape.shoulder_to_height", "shape.hip_to_height"}
        if any(item["field"] not in allowed_fields for item in request["changes"]):
            raise FidelityAdjustmentError("fidelity shape plan generated a non-silhouette adjustment")

    return {
        "format": FORMAT,
        "version": VERSION,
        "evaluation_sha256": _canonical_sha256(dict(evaluation)),
        "applicable": request is not None,
        "feedback": feedback,
        "adjustment_request": request,
        "semantics": SEMANTICS,
    }


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FidelityAdjustmentError(f"fidelity adjustment output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError as exc:
            raise FidelityAdjustmentError(f"fidelity adjustment output already exists: {path}") from exc
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create a bounded BodyRig shape request from a visual-fidelity evaluator hint.")
    parser.add_argument("evaluation")
    parser.add_argument("--out", required=True, help="Create-only fidelity adjustment plan JSON")
    parser.add_argument("--request-out", default="", help="Optional create-only raw BodyPrint adjustment request for the next clone")
    args = parser.parse_args(argv)

    try:
        source = Path(args.evaluation).expanduser().resolve()
        try:
            evaluation = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FidelityAdjustmentError("fidelity evaluation is invalid JSON") from exc
        plan = build_fidelity_adjustment_plan(evaluation)
        _write_create_only(Path(args.out).expanduser().resolve(), plan)
        if args.request_out:
            if not plan["applicable"]:
                raise FidelityAdjustmentError("no bounded silhouette adjustment is applicable")
            _write_create_only(Path(args.request_out).expanduser().resolve(), plan["adjustment_request"])
    except (FidelityAdjustmentError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity adjustment: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(plan, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
