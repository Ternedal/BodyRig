from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


def _load_wrapper(repo: Path):
    path = repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_gender.py"
    spec = importlib.util.spec_from_file_location("bodyrig_sith_gender_wrapper_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gender_wrapper_patches_only_gender_on_donor_topology_bridge() -> None:
    repo = Path(__file__).resolve().parents[1]
    wrapper = _load_wrapper(repo)
    source_path = repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_donor.py"
    source = source_path.read_text(encoding="utf-8")

    patched = wrapper._patch_source(source, "female")

    assert "gender='female'," in patched
    assert "failed to load the licensed SMPL-X female model" in patched
    assert "rest_positions = v_shaped[0]" in patched
    assert "full_weights = model.lbs_weights" in patched
    assert "donor_faces_raw = _donor_faces(model)" in patched
    assert "build_surface_projected_donor_uvs(" in patched
    assert "texcoords=projected_texcoords" in patched
    assert "repair_source_shell" not in patched
    ast.parse(patched)


def test_gender_wrapper_rejects_drifted_donor_source_markers() -> None:
    repo = Path(__file__).resolve().parents[1]
    wrapper = _load_wrapper(repo)
    source = (repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_donor.py").read_text(encoding="utf-8")
    drifted = source.replace('gender="male",', 'gender="neutral",', 1)

    try:
        wrapper._patch_source(drifted, "female")
    except RuntimeError as exc:
        assert "SMPL-X gender patch" in str(exc)
    else:
        raise AssertionError("wrapper accepted a drifted donor-topology bridge")


def test_reconstruction_gender_authority_selects_only_strict_reproducer() -> None:
    repo = Path(__file__).resolve().parents[1]
    wrapper = _load_wrapper(repo)

    authority = wrapper._select_reconstruction_gender(
        {
            "female": (0.0002, 0.00005),
            "male": (0.031, 0.011),
            "neutral": (0.018, 0.007),
        }
    )

    assert authority == "female"


def test_reconstruction_gender_authority_rejects_cli_override() -> None:
    repo = Path(__file__).resolve().parents[1]
    wrapper = _load_wrapper(repo)

    try:
        wrapper._select_reconstruction_gender(
            {
                "female": (0.0002, 0.00005),
                "male": (0.031, 0.011),
                "neutral": (0.018, 0.007),
            },
            asserted_gender="male",
        )
    except RuntimeError as exc:
        assert "conflicts with retained reconstruction authority" in str(exc)
    else:
        raise AssertionError("CLI gender assertion overrode retained reconstruction authority")


def test_reconstruction_gender_authority_rejects_ambiguous_geometry() -> None:
    repo = Path(__file__).resolve().parents[1]
    wrapper = _load_wrapper(repo)

    try:
        wrapper._select_reconstruction_gender(
            {
                "female": (0.0002, 0.00005),
                "neutral": (0.0003, 0.00008),
            }
        )
    except RuntimeError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous SMPL-X reconstruction authority was accepted")


def test_reconstruction_gender_authority_rejects_no_matching_model() -> None:
    repo = Path(__file__).resolve().parents[1]
    wrapper = _load_wrapper(repo)

    try:
        wrapper._select_reconstruction_gender(
            {
                "female": (0.021, 0.009),
                "male": (0.019, 0.008),
                "neutral": (0.017, 0.006),
            }
        )
    except RuntimeError as exc:
        assert "does not uniquely reproduce" in str(exc)
    else:
        raise AssertionError("non-reproducing SMPL-X model family was accepted")
