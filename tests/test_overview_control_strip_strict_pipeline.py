from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "bodyrig" / "ui" / "overview_control_strip.js").read_text(encoding="utf-8")

def test_overview_pipeline_only_activates_for_complete_badge() -> None:
    assert 'setChip("overviewControlPipeline",pipeline||"Ukendt",/^Komplet$/i.test(pipeline));' in JS
    assert '!/ukendt|0\\/6|mangler|blocked|blokeret/i.test(pipeline)' not in JS
