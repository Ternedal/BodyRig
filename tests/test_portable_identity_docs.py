from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_portable_identity_spec_documents_canonical_identity_boundary() -> None:
    text = (ROOT / "docs" / "PORTABLE_IDENTITY.md").read_text(encoding="utf-8")
    required = (
        "bodyid-<24 lowercase hexadecimal characters>",
        "operator alias",
        "path-free source-byte-set digest",
        "Source-byte TOCTOU boundary",
        "identity_content",
        "bodyrig.portable_identity",
        "JSON boolean `true`",
        "Gate A",
    )
    for marker in required:
        assert marker in text


def test_mrbody_spec_distinguishes_alias_from_manifest_identity() -> None:
    text = (ROOT / "docs" / "MRBODY_SPEC.md").read_text(encoding="utf-8")
    assert "does not use the operator's local alias as its portable manifest id" in text
    assert "canonical `bodyid-<24 lowercase hex>`" in text
    assert "exactly one `identity_content` stage" in text
    assert "docs/PORTABLE_IDENTITY.md" in text
