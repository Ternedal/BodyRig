from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .digital_twin_composition import (
    DigitalTwinCompositionError,
    composition_dir,
    write_composition_authority,
)
from .storage import body_library, person_library


def _read_json(path: str, label: str) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DigitalTwinCompositionError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise DigitalTwinCompositionError(f"{label} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compose one create-only full-digital-twin Person Revision authority from exact body, VoiceRig, "
            "personality/audition, finalized M2/M3 presentation and source-observed Motor State v2 embodiment."
        )
    )
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--person-revision", required=True)
    parser.add_argument("--body-release-status", required=True)
    parser.add_argument("--hands-release-id", required=True)
    parser.add_argument("--wardrobe-release-id", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
        body_release = _read_json(args.body_release_status, "Person body-release status")
        receipt = write_composition_authority(
            person_library(),
            body_library(),
            person_id=args.person_id,
            person_revision=args.person_revision,
            body_release_status=body_release,
            hands_release_id=args.hands_release_id,
            wardrobe_release_id=args.wardrobe_release_id,
            bodyrig_revision=args.bodyrig_revision,
        )
        root = composition_dir(
            person_library(),
            str(receipt["person_id"]),
            str(receipt["person_revision"]),
            str(receipt["composition_id"]),
        )
    except (DigitalTwinCompositionError, OSError, ValueError) as exc:
        print(f"BodyRig digital-twin M4 composition: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "ok": True,
        "composition_id": receipt["composition_id"],
        "person_id": receipt["person_id"],
        "person_revision": receipt["person_revision"],
        "body_id": receipt["body_id"],
        "hands_release_id": receipt["hands_release_id"],
        "wardrobe_release_id": receipt["wardrobe_release_id"],
        "authority": str(root / "authority.json"),
        "motion_authority": True,
        "expression_authority": True,
        "voice_timing_authority": True,
        "presentation_authority": True,
        "production_activation": False,
    }, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
