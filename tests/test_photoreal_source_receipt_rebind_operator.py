from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "rebind-photoreal-v2-source-receipt.ps1").read_text(encoding="utf-8")


def test_rebind_operator_skips_content_hash_and_rebuilds_probe() -> None:
    assert "bodyrig.photoreal_source_receipt_rebind_cli" in SCRIPT
    assert "bodyrig.photoreal_spatial_metadata_probe_cli" in SCRIPT
    assert "bodyrig.photoreal_source_verify_cli" not in SCRIPT
    assert "Source rehash:        SKIPPED EXPLICITLY" in SCRIPT
    assert "source-receipt-rebind-proof.json" in SCRIPT
    assert "production" in SCRIPT.lower()
