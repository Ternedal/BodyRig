from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .digital_twin_photoreal_release import (
    DigitalTwinPhotorealReleaseError,
    photoreal_release_dir,
    write_photoreal_release,
)
from .storage import person_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Finalize an activating Photoreal digital-twin release only after the "
            "canonical M6 release and exact Photoreal M5 authority both validate."
        )
    )
    parser.add_argument("--canonical-m6-release-dir", type=Path, required=True)
    parser.add_argument("--composition-authority-dir", type=Path, required=True)
    parser.add_argument("--acceptance-dir", type=Path, required=True)
    parser.add_argument("--photoreal-m5-link-dir", type=Path, required=True)
    parser.add_argument("--m4-photoreal-link-dir", type=Path, required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--library-root", type=Path, default=None)
    args = parser.parse_args(argv)
    library = (
        args.library_root.expanduser().resolve()
        if args.library_root is not None
        else person_library()
    )

    try:
        authority = write_photoreal_release(
            library,
            canonical_m6_release_dir_path=args.canonical_m6_release_dir,
            composition_authority_dir_path=args.composition_authority_dir,
            acceptance_dir_path=args.acceptance_dir,
            photoreal_m5_link_authority_dir_path=args.photoreal_m5_link_dir,
            m4_photoreal_link_authority_dir_path=args.m4_photoreal_link_dir,
            bodyrig_revision=args.bodyrig_revision,
        )
        directory = photoreal_release_dir(
            library,
            person_id=str(authority["person_id"]),
            person_revision=str(authority["person_revision"]),
            release_id=str(authority["release_id"]),
        )
    except (DigitalTwinPhotorealReleaseError, OSError, ValueError) as exc:
        print(f"BodyRig Photoreal M6 release: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "release_id": authority["release_id"],
                "person_id": authority["person_id"],
                "person_revision": authority["person_revision"],
                "canonical_m6_release_id": authority["canonical_m6_release_id"],
                "photoreal_m5_link_id": authority["photoreal_m5_link_id"],
                "visual_authority": authority["visual_authority"],
                "canonical_digital_twin_ready": True,
                "photoreal_digital_twin_ready": True,
                "production_activation": True,
                "authority": str(directory / "authority.json"),
                "library_root": str(library),
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
