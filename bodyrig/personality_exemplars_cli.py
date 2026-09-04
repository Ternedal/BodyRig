from __future__ import annotations

import argparse
import json
import sys

from .personality_exemplars import (
    MAX_EXEMPLARS,
    PersonalityExemplarError,
    build_exemplar_candidates,
    write_create_only,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract reviewable style exemplar candidates from UTF-8 TXT/SRT/VTT transcripts. "
            "The output is style evidence only and never personality/biography authority."
        )
    )
    parser.add_argument("sources", nargs="+", help="Transcript files (TXT/SRT/VTT or compatible UTF-8 text)")
    parser.add_argument("--suggested-limit", type=int, default=MAX_EXEMPLARS)
    parser.add_argument("--out", required=True, help="Create-only JSON candidate report")
    args = parser.parse_args(argv)

    try:
        value = build_exemplar_candidates(args.sources, suggested_limit=args.suggested_limit)
        write_create_only(args.out, value)
    except PersonalityExemplarError as exc:
        print(f"BodyRig personality exemplars: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
