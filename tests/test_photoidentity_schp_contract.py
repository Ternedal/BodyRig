from __future__ import annotations

from pathlib import Path

from bodyrig import photoidentity_schp_contract as contract


ROOT = Path(__file__).resolve().parents[1]


def test_schp_authority_is_narrow_and_pinned() -> None:
    assert contract.ADAPTER == "schp-atr18-source-observability"
    assert contract.ADAPTER_REVISION == "1"
    assert contract.CAPABILITIES == ("hair-detail", "skin-detail")
    assert contract.MODEL_SHA256 == "4420d8db8c1f266967c89485786b01209f6d405f320fc0f87e8ced49392cefb5"
    assert contract.MODEL_SIZE == 69_141_996
    assert contract.UPSTREAM_REVISION == "eb84c432cc697f494d99662a05f2335eb2f26095"


def test_schp_cannot_claim_anatomy_rear_or_nails() -> None:
    blocked = set(contract.UNSUPPORTED_IDENTITY_DOMAINS)
    assert {
        "body_rear",
        "torso_chest",
        "waist_hips",
        "fingernails_detail",
        "toenails_detail",
    } <= blocked


def test_setup_does_not_vendor_model_bytes_and_requires_hash_verification() -> None:
    source = (ROOT / "setup-photoidentity-schp-windows.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert contract.MODEL_SHA256 in source
    assert "invoke-webrequest" in lowered
    assert "get-filehash" in lowered
    assert "sha256" in lowered
    assert ".onnx" in lowered
    assert "production_activation" not in lowered


def test_collector_uses_schp_as_enrichment_not_renderer_or_reconstruction() -> None:
    source = (ROOT / "collect-photoidentity-evidence.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "photoidentity_schp" in lowered
    assert "hair/skin" in lowered or "hair" in lowered
    assert "run-reference-windows-renderer-probe" not in lowered
    assert "run-fidelity-windows-render-probe" not in lowered
    assert "sith_reconstruct" not in lowered
