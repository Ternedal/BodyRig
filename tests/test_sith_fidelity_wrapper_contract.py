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


def test_gender_wrapper_injects_fidelity_repair_into_reviewed_bridge() -> None:
    repo = Path(__file__).resolve().parents[1]
    wrapper = _load_wrapper(repo)
    source_path = repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_adjusted.py"
    source = source_path.read_text(encoding="utf-8")

    patched = wrapper._patch_source(source, "female")

    assert "gender='female'," in patched
    assert "from sith_mesh_fidelity import MeshFidelityError, repair_source_shell" in patched
    assert "donor_rest_positions = v_shaped[0, selected_nearest]" in patched
    assert "rest_positions, faces, shell_metrics = repair_source_shell(" in patched
    assert '"source_shell_cross_region_faces_removed"' in patched
    assert '"source_shell_head_vertices_preserved"' in patched
    ast.parse(patched)


def test_gender_wrapper_rejects_drifted_source_markers() -> None:
    repo = Path(__file__).resolve().parents[1]
    wrapper = _load_wrapper(repo)
    source = (repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_adjusted.py").read_text(encoding="utf-8")
    drifted = source.replace('gender="male",', 'gender="neutral",', 1)

    try:
        wrapper._patch_source(drifted, "female")
    except RuntimeError as exc:
        assert "SMPL-X gender patch" in str(exc)
    else:
        raise AssertionError("wrapper accepted a drifted reviewed bridge")
