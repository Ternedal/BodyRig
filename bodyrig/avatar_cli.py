from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .avatar import AvatarError
from .fitters import fitter_names, get_fitter
from .identity import VisualIdentityError, bind_visual_identity_to_proof
from .package import MRBodyError, build_package
from .proof import ProofError, load_recovery_proof, read_canonical_json


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
        proof = load_recovery_proof(proof_path)
        fitter = get_fitter(args.fitter)

        identity: dict[str, Any] | None = None
        if args.identity_profile:
            identity_path = Path(args.identity_profile).expanduser().resolve()
            identity = bind_visual_identity_to_proof(
                read_canonical_json(identity_path, label="visual identity profile"),
                proof,
            )
            if not fitter.capabilities.visual_identity:
                raise AvatarError(f"fitter {fitter.name} does not support visual identity input")

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
    except (OSError, ValueError, ProofError, VisualIdentityError, AvatarError, MRBodyError) as exc:
        print(f"BodyRig avatar fitting: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
