from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FITTER = ROOT / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_donor.py"


def test_donor_appearance_mapping_is_exact_tiled_nearest_source_search() -> None:
    source = FITTER.read_text(encoding="utf-8")

    assert "exact nearest textured source vertex" in source
    assert "for donor_start in range(0, donor_count, donor_chunk):" in source
    assert "for source_start in range(0, int(textured_source.shape[0]), source_tile):" in source
    assert "distances = torch.cdist(donor_tensor.unsqueeze(0), source.unsqueeze(0)).squeeze(0)" in source
    assert "tile_distance, tile_local = torch.min(distances, dim=1)" in source
    assert "improve = tile_distance < local_best" in source
    assert "source_global = valid_index[source_start + tile_local]" in source


def test_donor_mapping_no_longer_uses_inverse_source_to_donor_approximation() -> None:
    source = FITTER.read_text(encoding="utf-8")

    assert "Source -> nearest donor" not in source
    assert "nearest_donor = torch.min" not in source
    assert "missing = [index for index" not in source
