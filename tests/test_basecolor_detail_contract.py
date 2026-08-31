from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DETAIL = ROOT / "bodyrig" / "bridges" / "sith_basecolor_detail.py"
WRAPPER = ROOT / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_gender.py"


def test_basecolor_detail_is_bounded_source_luminance_not_generation() -> None:
    source = DETAIL.read_text(encoding="utf-8")
    assert "DETAIL_STRENGTH = 0.45" in source
    assert "CHANNEL_DELTA_CAP = 0.035" in source
    assert "detail = luminance - smooth" in source
    assert "np.clip(detail * DETAIL_STRENGTH, -CHANNEL_DELTA_CAP, CHANNEL_DELTA_CAP)" in source
    assert "rgb + delta[:, :, None]" in source
    assert '"source_derived": True' in source
    assert '"generative": False' in source
    assert "source_basecolor_sha256" in source
    assert "refined_basecolor_sha256" in source


def test_basecolor_refinement_preserves_texture_zero_and_requires_prior_pbr() -> None:
    source = DETAIL.read_text(encoding="utf-8")
    assert 'textures[0].get("source") != 0' in source
    assert 'pbr.get("baseColorTexture") != {"index": 0}' in source
    assert '"materialRefinement" not in bodyrig' in source
    assert 'base_image["bufferView"] = len(views) - 1' in source
    assert '"baseColorDetailRefinement"' in source


def test_production_wrapper_applies_detail_after_core_pbr() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    pbr_index = source.index("refined = refine_glb_pbr(")
    derive_index = source.index("detail_png, detail_metrics = derive_basecolor_detail")
    detail_index = source.index("refined = refine_glb_basecolor(")
    assert pbr_index < derive_index < detail_index
    assert "source-derived appearance refinement failed" in source
    assert "BodyRig bounded base-color detail:" in source
