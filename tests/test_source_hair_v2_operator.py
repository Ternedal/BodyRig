from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "extract-retained-hair.ps1"
BRIDGE = ROOT / "bodyrig" / "bridges" / "sith_source_hair_extract_v2.py"
BINDING = ROOT / "bodyrig" / "source_hair_body_binding.py"


def test_operator_routes_to_v2_selector_and_rejects_legacy_method() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert 'sith_source_hair_extract_v2.py' in wrapper
    assert '[string]$evidence.method -ne "retained-sith-connected-head-shell-v2"' in wrapper
    assert '"strict-shell", "short-hair-fallback"' in wrapper
    assert 'Write-Host "Selector:' in wrapper


def test_v2_receipt_persists_selector_thresholds_and_spatial_metrics() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    for marker in (
        'METHOD = "retained-sith-connected-head-shell-v2"',
        '"selectorThresholds"',
        '"selectionMetrics"',
        '"minimumFootprintSpanBodyRatio"',
        '"minimumVerticalSpanBodyRatio"',
        '"short-hair-fallback"',
    ):
        assert marker in source


def test_downstream_binding_accepts_only_v2_selector_authority() -> None:
    source = BINDING.read_text(encoding="utf-8")
    assert 'CANDIDATE_METHOD = "retained-sith-connected-head-shell-v2"' in source
    assert '"strict-shell"' in source
    assert '"short-hair-fallback"' in source
    assert 'source hair candidate footprint is below the v2 review floor' in source
    assert 'source hair candidate vertical span is below the v2 review floor' in source
