from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import bodyrig.photoidentity_fine_identity_review_manifest as subject
from bodyrig.photoidentity_fine_identity_attestation import REQUIRED_DOMAINS


def test_builder_requires_complete_domain_coverage(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    anatomy = sweep / "anatomy-attested-evidence"
    anatomy.mkdir(parents=True)
    revision = "a" * 40
    (anatomy / "photoidentity-observations.json").write_text(
        json.dumps({"performer_id": "42", "bodyrig_revision": revision, "source_files_scanned": len(REQUIRED_DOMAINS) * 2}), encoding="utf-8"
    )
    (anatomy / "photoidentity-evidence.json").write_text(
        json.dumps({"performer_id": "42", "bodyrig_revision": revision}), encoding="utf-8"
    )
    marker = tmp_path / "markers.json"
    marker.write_text('{"markers":[]}\n', encoding="utf-8")
    csv_path = tmp_path / "evidence.csv"
    fields = ["reference","domain","scene_id","region","source_ordinal","review_image_path","source_quality"]
    rows = []
    sources = {}
    ordinal = 0
    for domain in REQUIRED_DOMAINS:
        for index in (1, 2):
            ordinal += 1
            media = tmp_path / f"{domain}-{index}.mp4"
            image = tmp_path / f"{domain}-{index}.png"
            media.write_bytes(f"media-{domain}-{index}".encode())
            image.write_bytes(f"image-{domain}-{index}".encode())
            sources[ordinal] = {"scene_id": f"{domain}-scene-{index}", "path": str(media)}
            rows.append({
                "reference": f"{domain}-{index}",
                "domain": domain,
                "scene_id": f"{domain}-scene-{index}",
                "region": domain,
                "source_ordinal": str(ordinal),
                "review_image_path": str(image),
                "source_quality": "0.91",
            })
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    subject._private_source_bindings = lambda sweep_root, expected_count: (sources, "a" * 64)
    output = tmp_path / "private.json"
    result = subject.build_private_review_manifest(
        sweep_root=sweep,
        evidence_csv=csv_path,
        marker_inventory=marker,
        output=output,
    )
    assert output.is_file()
    assert len(result["entries"]) == len(REQUIRED_DOMAINS) * 2
    assert all("source_media_path" in row for row in result["entries"])
