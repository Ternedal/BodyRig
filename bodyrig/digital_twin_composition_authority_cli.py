from __future__ import annotations

import argparse
import json
import sys

from .digital_twin_composition_authority import (
    DigitalTwinCompositionAuthorityError,
    composition_authority_dir,
    write_composition_authority,
)
from .storage import person_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Finalize exact M4 digital-twin composition authority without activating production."
    )
    parser.add_argument("--assembly-receipt", required=True)
    parser.add_argument("--body-release-status", required=True)
    parser.add_argument("--hands-nails-authority", required=True)
    parser.add_argument("--wardrobe-authority", required=True)
    parser.add_argument("--body-package", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = write_composition_authority(
            person_library(),
            assembly_receipt_path=args.assembly_receipt,
            body_release_status_path=args.body_release_status,
            hands_nails_authority_path=args.hands_nails_authority,
            wardrobe_authority_path=args.wardrobe_authority,
            body_package_path=args.body_package,
            bodyrig_revision=args.bodyrig_revision,
        )
        root = composition_authority_dir(
            person_library(),
            str(receipt["person_id"]),
            str(receipt["person_revision"]),
            str(receipt["authority_id"]),
        )
    except (DigitalTwinCompositionAuthorityError, OSError, ValueError) as exc:
        print(f"BodyRig M4 digital-twin composition authority: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "authority_id": receipt["authority_id"],
                "person_id": receipt["person_id"],
                "person_revision": receipt["person_revision"],
                "authority": str(root / "authority.json"),
                "embodiment_probe": str(root / "embodiment-probe.json"),
                "production_activation": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
