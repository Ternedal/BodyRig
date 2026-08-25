from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_gate_a_rechecks_exact_clean_checkout_before_and_after_acceptance_write() -> None:
    source = (REPO / "accept-physical-clone.ps1").read_text(encoding="utf-8")

    assert "function Assert-CheckoutAuthority" in source
    assert "$headLines = @(& git -C $RepoRoot rev-parse HEAD 2>&1)" in source
    assert "$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()" not in source

    initial = source.index("$head = Assert-CheckoutAuthority -RepoRoot $repoRoot")
    output_creation = source.index("New-Item -ItemType Directory -Path $OutputDir")
    runtime_hash = source.index("$runtimeHash = Sha256 $runtimeManifestPath")
    prewrite = source.index("Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head", runtime_hash)
    report = source.index("$report = [ordered]@{")
    move = source.index("Move-Item -LiteralPath $temp -Destination $reportPath")
    postwrite = source.index("Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head", move)
    success = source.index('Write-Host "BodyRig high-fidelity Gate A: PASS"')

    assert initial < output_creation < runtime_hash < prewrite < report < move < postwrite < success
    assert "BodyRig checkout authority changed before Gate A acceptance write; removed non-authoritative output" in source
    assert "BodyRig checkout authority changed after Gate A acceptance write; removed non-authoritative output" in source
    assert source.count("Remove-Item -LiteralPath $OutputDir -Recurse -Force") >= 2
