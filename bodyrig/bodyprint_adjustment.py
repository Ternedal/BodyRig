from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .body_feedback import ProposedBodyChange, propose_bodyprint_changes
from .bridges.bodyprint_shape_adjust import (
    BodyprintAdjustmentError,
    validate_adjustment_payload,
)
from .package import MRBodyError, validate_bodyprint
from .proof import ProofError, load_recovery_proof, read_canonical_json

EVIDENCE_FORMAT = "bodyrig-bodyprint-adjustment-evidence"
EVIDENCE_VERSION = 1


class BodyprintAdjustmentEvidenceError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise BodyprintAdjustmentEvidenceError(f"file not found: {resolved}")
    return _sha256_bytes(resolved.read_bytes())


def feedback_sha256(feedback: str) -> str:
    if not isinstance(feedback, str) or not feedback.strip() or len(feedback) > 8000:
        raise BodyprintAdjustmentEvidenceError("feedback must contain 1..8000 characters")
    normalized = " ".join(feedback.strip().split())
    return _sha256_bytes(normalized.encode("utf-8"))


def build_adjustment_request(
    feedback: str,
    *,
    changes: Sequence[Mapping[str, Any]] | Sequence[ProposedBodyChange] | None = None,
) -> dict[str, Any]:
    """Build the reviewable bounded request before recovery evidence exists.

    Explicit changes are allowed only as an exact subset of the deterministic
    proposal produced from the same feedback. Person Studio may therefore let
    an operator review/deselect proposed edits, while a direct API caller cannot
    smuggle in a different field, delta or reason under reviewed feedback.
    """

    generated = [item.to_json() for item in propose_bodyprint_changes(feedback)]
    selected: Sequence[Mapping[str, Any] | ProposedBodyChange]
    selected = generated if changes is None else changes
    serialized: list[dict[str, Any]] = []
    for item in selected:
        if isinstance(item, ProposedBodyChange):
            serialized.append(item.to_json())
        elif isinstance(item, Mapping):
            serialized.append(dict(item))
        else:
            raise BodyprintAdjustmentEvidenceError("adjustment changes must be objects")
    payload = {
        "format": "bodyrig-bodyprint-adjustment",
        "version": 1,
        "feedback_sha256": feedback_sha256(feedback),
        "changes": serialized,
    }
    try:
        validated = validate_adjustment_payload(payload)
        generated_validated = validate_adjustment_payload(
            {
                "format": "bodyrig-bodyprint-adjustment",
                "version": 1,
                "feedback_sha256": feedback_sha256(feedback),
                "changes": generated,
            }
        )
    except BodyprintAdjustmentError as exc:
        raise BodyprintAdjustmentEvidenceError(str(exc)) from exc

    if changes is not None:
        generated_by_field = {
            item["field"]: item for item in generated_validated["changes"]
        }
        for item in validated["changes"]:
            expected = generated_by_field.get(item["field"])
            if expected != item:
                raise BodyprintAdjustmentEvidenceError(
                    "explicit adjustment changes must be an exact subset of the proposal generated from the same feedback"
                )
    return validated


def validate_adjustment_evidence(value: Any) -> dict[str, Any]:
    expected = {"format", "version", "recovery_proof_sha256", "adjustment"}
    if not isinstance(value, dict) or set(value) != expected:
        raise BodyprintAdjustmentEvidenceError("BodyPrint adjustment evidence fields must match v1 exactly")
    if value.get("format") != EVIDENCE_FORMAT or value.get("version") != EVIDENCE_VERSION:
        raise BodyprintAdjustmentEvidenceError("unsupported BodyPrint adjustment evidence format/version")
    proof_hash = value.get("recovery_proof_sha256")
    if (
        not isinstance(proof_hash, str)
        or len(proof_hash) != 64
        or any(ch not in "0123456789abcdef" for ch in proof_hash)
    ):
        raise BodyprintAdjustmentEvidenceError("recovery_proof_sha256 must be lowercase SHA-256")
    try:
        adjustment = validate_adjustment_payload(value.get("adjustment"))
    except BodyprintAdjustmentError as exc:
        raise BodyprintAdjustmentEvidenceError(str(exc)) from exc
    return {
        "format": EVIDENCE_FORMAT,
        "version": EVIDENCE_VERSION,
        "recovery_proof_sha256": proof_hash,
        "adjustment": adjustment,
    }


def bind_request_to_proof(
    request: Mapping[str, Any],
    *,
    proof_path: str | Path,
) -> dict[str, Any]:
    try:
        adjustment = validate_adjustment_payload(dict(request))
        load_recovery_proof(proof_path)
    except (BodyprintAdjustmentError, ProofError, OSError) as exc:
        raise BodyprintAdjustmentEvidenceError(str(exc)) from exc
    return validate_adjustment_evidence(
        {
            "format": EVIDENCE_FORMAT,
            "version": EVIDENCE_VERSION,
            "recovery_proof_sha256": _sha256_file(proof_path),
            "adjustment": adjustment,
        }
    )


def load_adjustment_evidence(
    path: str | Path,
    *,
    proof_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        value = read_canonical_json(path, label="BodyPrint adjustment evidence")
    except ProofError as exc:
        raise BodyprintAdjustmentEvidenceError(str(exc)) from exc
    evidence = validate_adjustment_evidence(value)
    if proof_path is not None:
        try:
            load_recovery_proof(proof_path)
        except ProofError as exc:
            raise BodyprintAdjustmentEvidenceError(str(exc)) from exc
        if evidence["recovery_proof_sha256"] != _sha256_file(proof_path):
            raise BodyprintAdjustmentEvidenceError(
                "BodyPrint adjustment evidence is bound to a different recovery proof"
            )
    return evidence


def apply_adjustment_to_bodyprint(
    bodyprint: Mapping[str, Any],
    evidence_or_request: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply only the bounded semantic deltas to a validated BodyPrint.

    Raw recovery evidence is never modified. The returned value is a new object
    used by the fitter and the derivative .mrbody package.
    """

    try:
        source = validate_bodyprint(copy.deepcopy(dict(bodyprint)))
    except MRBodyError as exc:
        raise BodyprintAdjustmentEvidenceError(str(exc)) from exc

    if evidence_or_request.get("format") == EVIDENCE_FORMAT:
        adjustment = validate_adjustment_evidence(dict(evidence_or_request))["adjustment"]
    else:
        try:
            adjustment = validate_adjustment_payload(dict(evidence_or_request))
        except BodyprintAdjustmentError as exc:
            raise BodyprintAdjustmentEvidenceError(str(exc)) from exc

    result = copy.deepcopy(source)
    for item in adjustment["changes"]:
        section, key = str(item["field"]).split(".", 1)
        section_value = result.setdefault(section, {})
        if not isinstance(section_value, dict):
            raise BodyprintAdjustmentEvidenceError(f"BodyPrint section {section} is not an object")
        if key in section_value:
            base = section_value[key]
            if isinstance(base, bool) or not isinstance(base, (int, float)):
                raise BodyprintAdjustmentEvidenceError(f"BodyPrint field {item['field']} is not numeric")
            base_value = float(base)
        elif item["field"] == "shape.height_scale":
            base_value = 1.0
        else:
            raise BodyprintAdjustmentEvidenceError(
                f"BodyPrint field {item['field']} is not present in the source-derived proof"
            )
        section_value[key] = base_value + float(item["delta"])

    try:
        return validate_bodyprint(result)
    except MRBodyError as exc:
        raise BodyprintAdjustmentEvidenceError(
            f"BodyPrint adjustment leaves the v1 contract: {exc}"
        ) from exc


def effective_bodyprint_from_files(
    *,
    proof_path: str | Path,
    adjustment_path: str | Path,
) -> dict[str, Any]:
    try:
        proof = load_recovery_proof(proof_path)
    except ProofError as exc:
        raise BodyprintAdjustmentEvidenceError(str(exc)) from exc
    evidence = load_adjustment_evidence(adjustment_path, proof_path=proof_path)
    return apply_adjustment_to_bodyprint(proof["bodyprint"], evidence)


def adjustment_evidence_sha256(path: str | Path) -> str:
    evidence = load_adjustment_evidence(path)
    del evidence
    return _sha256_file(path)


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise BodyprintAdjustmentEvidenceError(f"output already exists: {path}")
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temp: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        os.close(fd)
        temp = Path(name)
        temp.write_text(data, encoding="utf-8", newline="\n")
        with path.open("x", encoding="utf-8", newline="\n") as target:
            target.write(temp.read_text(encoding="utf-8"))
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind/apply reviewed BodyRig BodyPrint adjustments.")
    sub = parser.add_subparsers(dest="command", required=True)

    bind = sub.add_parser("bind", help="Bind a reviewed adjustment request to exact recovery proof bytes")
    bind.add_argument("request")
    bind.add_argument("proof")
    bind.add_argument("--out", required=True)

    effective = sub.add_parser("effective", help="Materialize the effective BodyPrint without mutating recovery proof")
    effective.add_argument("proof")
    effective.add_argument("adjustment")
    effective.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "bind":
            request = read_canonical_json(args.request, label="BodyPrint adjustment request")
            evidence = bind_request_to_proof(request, proof_path=args.proof)
            _write_create_only(Path(args.out), evidence)
            print(Path(args.out).expanduser().resolve())
            return 0
        if args.command == "effective":
            bodyprint = effective_bodyprint_from_files(
                proof_path=args.proof,
                adjustment_path=args.adjustment,
            )
            _write_create_only(Path(args.out), bodyprint)
            print(Path(args.out).expanduser().resolve())
            return 0
    except (BodyprintAdjustmentEvidenceError, ProofError, OSError, ValueError) as exc:
        print(f"BodyRig BodyPrint adjustment: FAIL: {exc}", file=os.sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
