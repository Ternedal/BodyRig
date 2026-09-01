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
    assert "build_donor_faces(" in patched
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
