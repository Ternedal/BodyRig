from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .fidelity_review_bundle import KNOWN_BAD_PACKAGE_SHA256
from .fidelity_review_receipt import FidelityReviewReceiptError, seal_review_bundle, verify_review_bundle


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _evidence(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityReviewReceiptError(f"source A/B evidence is invalid JSON: {path}") from exc
    if not isinstance(value, dict) or value.get("format") != "bodyrig-fidelity-ab-evidence" or value.get("version") != 1:
        raise FidelityReviewReceiptError("source A/B evidence format/version is invalid")
    invariants = value.get("invariants")
    if not isinstance(invariants, dict) or invariants.get("clean_appearance_ab") is not True:
        raise FidelityReviewReceiptError("source A/B evidence is not a clean appearance-only comparison")
    left = value.get("left")
    right = value.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise FidelityReviewReceiptError("source A/B evidence is missing package-side authority")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seal or verify exact bytes shown in the BodyRig physical fidelity review bundle.")
    parser.add_argument("command", choices=("seal", "verify"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).expanduser().resolve()
        evidence_path = Path(args.evidence).expanduser().resolve()
        evidence = _evidence(evidence_path)
        evidence_sha = _sha256_file(evidence_path)
        kwargs = {
            "historical_package_sha256": KNOWN_BAD_PACKAGE_SHA256,
            "pr40_package_sha256": str(evidence["left"]["package_sha256"]),
            "pr41_package_sha256": str(evidence["right"]["package_sha256"]),
            "evidence_sha256": evidence_sha,
        }
        if args.command == "seal":
            receipt = seal_review_bundle(root, **kwargs)
        else:
            receipt = root / "review-bundle-receipt.json"
        value = verify_review_bundle(
            root,
            expected_historical_package_sha256=kwargs["historical_package_sha256"],
            expected_pr40_package_sha256=kwargs["pr40_package_sha256"],
            expected_pr41_package_sha256=kwargs["pr41_package_sha256"],
            expected_evidence_sha256=kwargs["evidence_sha256"],
        )
        print(json.dumps({"ok": True, "receipt": str(receipt), "authority": value}, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    except (FidelityReviewReceiptError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity review receipt: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
