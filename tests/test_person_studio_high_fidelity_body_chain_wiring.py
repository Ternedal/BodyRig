from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")

CHAIN = [
    "/ui/high_fidelity_preview.js",
    "/ui/high_fidelity_component_review.js",
    "/ui/high_fidelity_hair_deformation_review.js",
    "/ui/high_fidelity_hair_promotion.js",
    "/ui/high_fidelity_continuation.js",
]

def test_person_studio_loads_complete_high_fidelity_body_chain_in_order() -> None:
    positions = []
    for script in CHAIN:
        marker = f'<script src="{script}" defer></script>'
        assert marker in HTML
        positions.append(HTML.index(marker))
    assert positions == sorted(positions)

def test_high_fidelity_chain_uses_existing_body_workspace_mounts() -> None:
    expectations = {
        "high_fidelity_preview.js": 'card.id = "highFidelityPreviewCard"',
        "high_fidelity_component_review.js": 'card.id = "highFidelityComponentReviewCard"',
        "high_fidelity_hair_deformation_review.js": 'card.id = "highFidelityHairDeformationReviewCard"',
        "high_fidelity_hair_promotion.js": 'card.id = "highFidelityHairPromotionCard"',
        "high_fidelity_continuation.js": 'card.id = "highFidelityContinuationCard"',
    }
    for filename, expected in expectations.items():
        source = (ROOT / "bodyrig" / "ui" / filename).read_text(encoding="utf-8")
        assert expected in source
        assert 'const tab = $("tab-body");' in source

def test_wiring_is_script_only_and_does_not_add_inline_high_fidelity_routes() -> None:
    script_block = "\n".join(
        f'<script src="{script}" defer></script>' for script in CHAIN
    )
    for line in script_block.splitlines():
        assert line in HTML
    assert "/api/v1/high-fidelity-preview-jobs/" not in HTML
    assert "/body/high-fidelity-preview" not in HTML
