from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .avatar import AvatarError
from .fitters import fitter_names, get_fitter
from .identity import VisualIdentityError, validate_visual_identity
from .package import MRBodyError, build_package, validate_bodyprint


class ProofError(ValueError):
    pass


def _proof(value: Any) -> dict[str, Any]:
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


def _read_json(path: Path, *, label: str) -> Any:
    if not path.is_file():
        raise ProofError(f"{label} not found: {path}")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProofError(f"{label} is not valid canonical JSON: {path}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fit a portable VRM 1.0 avatar from a BodyRig recovery proof and build .mrbody."
    )
    parser.add_argument("proof", help="bodyrig-recovery-proof.json")
    parser.add_argument("--body-id", required=True, help="Path-safe BodyRig id")
    parser.add_argument("--name", required=True, help="Display name for the avatar")
    parser.add_argument("--out", required=True, help="Output .mrbody path")
    parser.add_argument(
        "--fitter",
        default="procedural-vrm1",
        help=f"Avatar fitter id (available: {', '.join(fitter_names())})",
    )
    parser.add_argument(
        "--identity-profile",
        default="",
        help="Optional build-only bodyrig-visual-identity v1 profile for identity-aware fitters",
    )
    args = parser.parse_args(argv)

    proof_path = Path(args.proof).expanduser().resolve()
    try:
        proof = _proof(_read_json(proof_path, label="recovery proof"))
        fitter = get_fitter(args.fitter)

        identity: dict[str, Any] | None = None
        if args.identity_profile:
            identity_path = Path(args.identity_profile).expanduser().resolve()
            identity = validate_visual_identity(_read_json(identity_path, label="visual identity profile"))
            if identity["source_count"] != proof["source_count"]:
                raise VisualIdentityError(
                    "visual identity source_count does not match recovery proof"
                )
            if identity["subject_track_id"] != proof["track_id"]:
                raise VisualIdentityError(
                    "visual identity subject_track_id does not match recovery proof track_id"
                )
            if not fitter.capabilities.visual_identity:
                raise AvatarError(
                    f"fitter {fitter.name} does not support visual identity input"
                )

        fitted = fitter.fit(proof["bodyprint"], name=args.name, identity=identity)
        pipeline = [
            {
                "stage": "body-recovery",
                "adapter": proof["adapter"],
                "revision": proof["revision"],
            }
        ]
        if identity is not None:
            pipeline.append(
                {
                    "stage": "visual-identity-capture",
                    "adapter": identity["adapter"],
                    "revision": identity["revision"],
                }
            )
        pipeline.append(
            {
                "stage": "avatar-fitting",
                "adapter": fitted.adapter,
                "revision": fitted.revision,
            }
        )
        provenance = {
            "format": "modelrig-body-provenance",
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": {
                "kind": "user-supplied-local-media",
                "count": proof["source_count"],
            },
            "synthetic_avatar": True,
            "pipeline": pipeline,
        }
        output = Path(args.out).expanduser().resolve()
        build_package(
            output,
            body_id=args.body_id,
            name=args.name,
            avatar_vrm=fitted.avatar_vrm,
            bodyprint=proof["bodyprint"],
            provenance=provenance,
            thumbnail_png=fitted.thumbnail_png,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ProofError,
        VisualIdentityError,
        AvatarError,
        MRBodyError,
    ) as exc:
        print(f"BodyRig avatar fitting: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
