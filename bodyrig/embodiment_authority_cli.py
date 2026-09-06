from __future__ import annotations

import argparse
import json
from pathlib import Path

from .embodiment_authority import EmbodimentAuthorityError, write_authority


def _json_object(path: str, label: str) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EmbodimentAuthorityError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise EmbodimentAuthorityError(f"{label} must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize exact Person embodiment authority from reviewed M4 evidence.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--assembly-receipt", required=True)
    parser.add_argument("--body-release-status", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--motor-state", required=True)
    parser.add_argument("--speech-timing", required=True)
    parser.add_argument("--audition-receipt", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--quality-note", required=True)
    parser.add_argument("--confirm-motion-review", action="store_true")
    parser.add_argument("--confirm-expression-review", action="store_true")
    parser.add_argument("--confirm-voice-timing-review", action="store_true")
    args = parser.parse_args()

    try:
        value = write_authority(
            args.root,
            assembly_receipt_path=args.assembly_receipt,
            body_release_status=_json_object(args.body_release_status, "body release status"),
            package_path=args.package,
            motor_state_path=args.motor_state,
            speech_timing_path=args.speech_timing,
            audition_receipt_path=args.audition_receipt,
            bodyrig_revision=args.bodyrig_revision,
            quality_note=args.quality_note,
            motion_review_passed=args.confirm_motion_review,
            expression_review_passed=args.confirm_expression_review,
            voice_timing_review_passed=args.confirm_voice_timing_review,
        )
    except EmbodimentAuthorityError as exc:
        parser.error(str(exc))
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
