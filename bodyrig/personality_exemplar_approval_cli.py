from __future__ import annotations

import argparse
import json
import sys

from .personality_exemplar_approval import (
    PersonalityExemplarApprovalError,
    build_approval,
    load_candidate_report,
    verify_approval,
    write_create_only,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create an explicit human approval receipt for transcript style exemplars. "
            "Indexes are zero-based and remain bound to the exact candidate report."
        )
    )
    parser.add_argument("report", help="bodyrig-personality-exemplar-candidates JSON report")
    parser.add_argument(
        "--index",
        type=int,
        action="append",
        required=True,
        help="Zero-based candidate index to approve. Repeat for up to 12 utterances.",
    )
    parser.add_argument(
        "--confirm-speaker-identity",
        action="store_true",
        help="Explicitly confirm that every selected utterance belongs to the intended person.",
    )
    parser.add_argument(
        "--approve-style-use",
        action="store_true",
        help="Explicitly approve every selected utterance for style-only use.",
    )
    parser.add_argument("--out", required=True, help="Create-only approval receipt JSON")
    args = parser.parse_args(argv)

    try:
        report = load_candidate_report(args.report)
        approval = build_approval(
            report,
            selected_candidate_indexes=args.index,
            speaker_identity_confirmed=args.confirm_speaker_identity,
            style_use_approved=args.approve_style_use,
        )
        verify_approval(report, approval)
        write_create_only(args.out, approval)
    except PersonalityExemplarApprovalError as exc:
        print(f"BodyRig personality exemplar approval: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(approval, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
