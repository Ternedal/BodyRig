from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .digital_twin_photoreal_link import (
    DigitalTwinPhotorealLinkError,
    photoreal_link_dir,
    write_photoreal_link,
)
from .storage import person_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind one exact M4 digital-twin composition authority to one exact "
            "accepted Photoreal V2 Person/P3 authority without activating production."
        )
    )
    parser.add_argument("--composition-authority-dir", type=Path, required=True)
    parser.add_argument("--photoreal-person-binding", type=Path, required=True)
    parser.add_argument("--p3-physical-review", type=Path, required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
        authority = write_photoreal_link(
            person_library(),
            composition_authority_dir_path=args.composition_authority_dir,
            photoreal_person_binding_path=args.photoreal_person_binding,
            p3_physical_runtime_review_path=args.p3_physical_review,
            bodyrig_revision=args.bodyrig_revision,
        )
        directory = photoreal_link_dir(
            person_library(),
            person_id=str(authority["person_id"]),
            person_revision=str(authority["person_revision"]),
            link_id=str(authority["link_id"]),
        )
    except (DigitalTwinPhotorealLinkError, OSError, ValueError) as exc:
        print(f"BodyRig M4 Photoreal link: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "link_id": authority["link_id"],
                "person_id": authority["person_id"],
                "person_revision": authority["person_revision"],
                "composition_authority_id": authority["composition_authority_id"],
                "photoreal_binding_id": authority["photoreal_binding_id"],
                "visual_authority": authority["visual_authority"],
                "m5_photoreal_integration_eligible": True,
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
