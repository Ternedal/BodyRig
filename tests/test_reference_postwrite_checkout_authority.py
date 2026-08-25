from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _assert_postwrite_checkout_boundary(path: str, *, core_call: str, output_token: str) -> None:
    source = (ROOT / path).read_text(encoding="utf-8")

    assert "function Assert-CheckoutAuthority" in source
    assert "$initialHead = Assert-CheckoutAuthority -RepoRoot $repoRoot" in source
    assert "-ExpectedHead $initialHead" in source
    assert "status --porcelain" in source
    assert "Remove-Item -LiteralPath" in source
    assert "removed non-authoritative output" in source

    precheck = source.index("$initialHead = Assert-CheckoutAuthority -RepoRoot $repoRoot")
    writer = source.index(core_call)
    postcheck = source.index("-ExpectedHead $initialHead", writer)
    cleanup = source.index("Remove-Item -LiteralPath", postcheck)
    success = source.index("Write-Host \"BodyRig reference", postcheck)

    assert precheck < writer < postcheck < success
    assert postcheck < cleanup
    assert output_token in source


def test_reference_renderer_attestation_rechecks_checkout_after_write() -> None:
    _assert_postwrite_checkout_boundary(
        "record-reference-renderer-acceptance.ps1",
        core_call="& $recordScript @args",
        output_token="Remove-Item -LiteralPath $Output -Force",
    )


def test_reference_release_rechecks_checkout_after_write() -> None:
    _assert_postwrite_checkout_boundary(
        "complete-reference-acceptance.ps1",
        core_call="& $core @args",
        output_token="Remove-Item -LiteralPath $authoritativeOutput -Force",
    )
