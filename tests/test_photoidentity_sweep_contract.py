from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sweep_expands_source_discovery_without_changing_ten_source_reconstruction_contract() -> None:
    source = (ROOT / "bodyrig" / "photoidentity_sweep.py").read_text(encoding="utf-8")
    assert "MAX_SWEEP_SOURCES = 100" in source
    assert "MAX_BATCH_SOURCES = 10" in source
    assert "ranked_all[:max_sources]" in source
    assert "range(0, len(decodable), batch_size)" in source
    assert "build_source_manifest(" in source
    assert "len(performer_ids) != 1" in source
    assert "_projection_safe_source" in source
    assert "_filter_decodable_sources" in source


def test_sweep_reuses_existing_observation_analyzer_in_bounded_batches_and_never_renders() -> None:
    source = (ROOT / "bodyrig" / "photoidentity_sweep.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "run_external_analyzer(" in source
    assert "--bodyrig-stash-manifest" in source
    assert "source_paths_persisted" not in source  # public evidence writer owns this boundary
    assert "run-fidelity-windows-render-probe" not in lowered
    assert "reference-renderer" not in lowered
    assert "unity" not in lowered
    assert "quest" not in lowered
    assert '"generic_guessing_permitted": False' in source
    assert '"production_activation": False' in source


def test_collection_operator_is_clean_checkout_bound_and_non_rendering() -> None:
    source = (ROOT / "collect-photoidentity-evidence.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "git -c $reporoot rev-parse head" in lowered
    assert "git -c $reporoot status --porcelain" in lowered
    assert "exact clean bodyrig checkout" in lowered
    assert "bodyrig.photoidentity_sweep" in source
    assert "photoidentity-evidence.json" in source
    assert "Generic guessing permitted: FALSE" in source
    assert "run-fidelity-windows-render-probe" not in lowered
    assert "run-reference-windows-renderer-probe" not in lowered
    assert "production_activation" not in lowered


def test_collection_operator_reuses_and_repreflights_exact_pinned_sith_openpose_authority() -> None:
    source = (ROOT / "collect-photoidentity-evidence.ps1").read_text(encoding="utf-8")
    assert "bodyrig-sith-fitter-config.json" in source
    assert 'Need-CommandArgument -Command $fitterCommand -Name "--distribution"' in source
    assert 'Need-CommandArgument -Command $fitterCommand -Name "--sith-repo"' in source
    assert 'Need-CommandArgument -Command $fitterCommand -Name "--sith-python"' in source
    assert 'Need-CommandArgument -Command $fitterCommand -Name "--openpose"' in source
    assert 'Need-CommandArgument -Command $fitterCommand -Name "--wsl-exe"' in source
    assert "bodyrig.sith_preflight" in source
    assert "--openpose-repo" in source
    assert "bodyrig.photoidentity_detail_enrich" in source
    assert '"detail-evidence\\photoidentity-evidence.json"' in source
    assert "pinned OpenPose BODY_25 + face + hands" in source


def test_collection_operator_can_fail_closed_when_called_as_a_gate() -> None:
    source = (ROOT / "collect-photoidentity-evidence.ps1").read_text(encoding="utf-8")
    assert "[switch]$RequireSufficient" in source
    assert "BodyRig photoidentity evidence gate: INSUFFICIENT EVIDENCE" in source
    assert "if ($RequireSufficient) { exit 2 }" in source
