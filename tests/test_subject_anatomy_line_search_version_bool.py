from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

import sith_subject_anatomy_line_search as line_search  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authority_fixture(tmp_path: Path, *, version: object) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    stage = workspace / "sith-input-v1"
    endpoint = tmp_path / "endpoint"

    retained_obj = stage / "smplx" / "000_smplx.obj"
    retained_fit = stage / "smplx" / "000_fit.json"
    reconstruction = stage / "reconstruction.json"
    source_obj = stage / "meshes" / "000_reco.obj"
    endpoint_obj = endpoint / "subject_smplx.obj"
    endpoint_fit = endpoint / "subject_fit.json"

    for path, content in (
        (reconstruction, b"reconstruction\n"),
        (retained_obj, b"retained obj\n"),
        (retained_fit, b"{}\n"),
        (source_obj, b"source obj\n"),
        (endpoint_obj, b"endpoint obj\n"),
        (endpoint_fit, b"{}\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    evidence = {
        "format": "bodyrig-subject-anatomy-refit",
        "version": version,
        "method": line_search.ENDPOINT_METHOD,
        "targetModelFamily": "neutral",
        "reconstructionSha256": _sha256(reconstruction),
        "retainedSmplxObjSha256": _sha256(retained_obj),
        "retainedFitParamsSha256": _sha256(retained_fit),
        "retainedSourceMeshSha256": _sha256(source_obj),
        "derivedSmplxObjSha256": _sha256(endpoint_obj),
        "derivedFitParamsSha256": _sha256(endpoint_fit),
        "comparisonOnly": True,
        "productionReady": False,
    }
    (endpoint / "subject-anatomy-refit.json").write_text(
        json.dumps(evidence, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return workspace, endpoint


def test_endpoint_authority_rejects_boolean_version(tmp_path: Path) -> None:
    workspace, endpoint = _authority_fixture(tmp_path, version=True)

    with pytest.raises(line_search.SubjectAnatomyLineSearchError, match="format is invalid"):
        line_search._endpoint_authority(
            workspace=workspace,
            endpoint_dir=endpoint,
            gender="neutral",
        )


def test_endpoint_authority_preserves_numeric_v1_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, endpoint = _authority_fixture(tmp_path, version=1.0)
    seen: list[Path] = []

    def fake_fit_params(path: Path) -> dict[str, list[float]]:
        seen.append(path)
        return {"scale": [1.0]}

    monkeypatch.setattr(line_search.base, "_fit_params", fake_fit_params)

    retained_fit, endpoint_fit, retained_obj, endpoint_obj, evidence = line_search._endpoint_authority(
        workspace=workspace,
        endpoint_dir=endpoint,
        gender="neutral",
    )

    assert retained_fit == {"scale": [1.0]}
    assert endpoint_fit == {"scale": [1.0]}
    assert retained_obj == workspace / "sith-input-v1" / "smplx" / "000_smplx.obj"
    assert endpoint_obj == endpoint / "subject_smplx.obj"
    assert evidence["version"] == 1.0
    assert seen == [
        workspace / "sith-input-v1" / "smplx" / "000_fit.json",
        endpoint / "subject_fit.json",
    ]
