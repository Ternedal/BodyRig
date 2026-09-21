from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .digital_twin_photoreal_m5_link import (
    DigitalTwinPhotorealM5LinkError,
    photoreal_m5_link_dir,
    write_photoreal_m5_link,
)
from .storage import person_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind complete canonical M5 Windows/Quest realization evidence to one "
            "exact M4 Photoreal link without activating production."
        )
    )
    parser.add_argument("--composition-authority-dir", type=Path, required=True)
    parser.add_argument("--acceptance-dir", type=Path, required=True)
    parser.add_argument("--m4-photoreal-link-dir", type=Path, required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
        authority = write_photoreal_m5_link(
            person_library(),
            composition_authority_dir_path=args.composition_authority_dir,
            acceptance_dir_path=args.acceptance_dir,
            photoreal_link_authority_dir_path=args.m4_photoreal_link_dir,
            bodyrig_revision=args.bodyrig_revision,
        )
        directory = photoreal_m5_link_dir(
            person_library(),
            person_id=str(authority["person_id"]),
            person_revision=str(authority["person_revision"]),
            link_id=str(authority["link_id"]),
        )
    except (DigitalTwinPhotorealM5LinkError, OSError, ValueError) as exc:
        print(f"BodyRig Photoreal M5 link: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "link_id": authority["link_id"],
                "person_id": authority["person_id"],
                "person_revision": authority["person_revision"],
                "m4_photoreal_link_id": authority["m4_photoreal_link_id"],
                "visual_authority": authority["visual_authority"],
                "photoreal_m5_ready": True,
                "m6_photoreal_release_eligible": True,
                "production_activation": False,
                "authority": str(directory / "authority.json"),\n                "library_root": str(library),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
