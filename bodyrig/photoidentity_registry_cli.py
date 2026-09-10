from __future__ import annotations

import argparse
import json
import sys

from .photoidentity_registry import (
    PhotoIdentityRegistryError,
    register_body_job_photoidentity_evidence,
    require_body_job_photoidentity_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register or validate exact source-sufficiency authority for one BodyRig body-build."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register")
    register.add_argument("body_job_id")
    register.add_argument("report")
    register.add_argument("--observations", default=None)

    require = sub.add_parser("require")
    require.add_argument("person_id")
    require.add_argument("body_job_id")

    args = parser.parse_args(argv)
    try:
        if args.command == "register":
            result = register_body_job_photoidentity_evidence(
                args.body_job_id,
                report_path=args.report,
                observation_path=args.observations,
            )
        else:
            report = require_body_job_photoidentity_evidence(args.person_id, args.body_job_id)
            result = {
                "ok": True,
                "person_id": args.person_id,
                "body_job_id": args.body_job_id,
                "performer_id": report["performer_id"],
                "bodyrig_revision": report["bodyrig_revision"],
                "source_evidence_sufficient": report["source_evidence_sufficient"],
                "human_review_render_permitted": report["human_review_render_permitted"],
                "generic_guessing_permitted": report["generic_guessing_permitted"],
                "production_activation": report["production_activation"],
            }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        return 0
    except (OSError, ValueError, PhotoIdentityRegistryError) as exc:
        print(f"BodyRig photoidentity registry: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
