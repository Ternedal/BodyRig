from __future__ import annotations

import argparse
import json
import sys

from .digital_twin_release import DigitalTwinReleaseError, release_dir, write_release
from .storage import person_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Finalize the canonical activating M6 full digital-twin release from exact M4/M5 physical authority."
    )
    parser.add_argument("--composition-authority-dir", required=True)
    parser.add_argument("--acceptance-dir", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)
    try:
        authority = write_release(
            person_library(),
            composition_authority_dir=args.composition_authority_dir,
            acceptance_dir=args.acceptance_dir,
            bodyrig_revision=args.bodyrig_revision,
        )
        directory = release_dir(
            person_library(),
            person_id=str(authority["person_id"]),
            person_revision=str(authority["person_revision"]),
            release_id=str(authority["release_id"]),
        )
    except (DigitalTwinReleaseError, OSError, ValueError) as exc:
        print(f"BodyRig M6 digital-twin final release: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "release_id": authority["release_id"],
                "person_id": authority["person_id"],
                "person_revision": authority["person_revision"],
                "authority": str(directory / "authority.json"),
                "digital_twin_ready": True,
                "production_activation": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
