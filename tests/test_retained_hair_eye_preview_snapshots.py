from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-retained-hair-eye-preview.ps1"


def test_retained_preview_requires_all_six_review_views_before_publish() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for view in (
        "front-full.png",
        "three-quarter-full.png",
        "side-full.png",
        "face-front.png",
        "face-zoom.png",
        "eyes-closeup.png",
    ):
        assert view in text
    assert 'Need-File -Path (Join-Path $previewDir "snapshots\\$name")' in text
