from pathlib import Path

from bodyrig import preflight_cli
from bodyrig.bridges.hmr2_config import (
    FOUR_D_HUMANS_REVISION,
    NMR_REMOTE,
    NMR_REVISION,
    PHALP_REVISION,
    PHALP_TRACKER_BLOB_SHA1,
)
from bodyrig.preflight_cli import SMPL_FILENAME


def test_preflight_pins_concrete_upstream_identities():
    assert len(FOUR_D_HUMANS_REVISION) == 40
    assert len(PHALP_REVISION) == 40
    assert len(PHALP_TRACKER_BLOB_SHA1) == 40
    assert len(NMR_REVISION) == 40
    assert NMR_REMOTE == "https://github.com/shubham-goel/NMR.git"
    assert SMPL_FILENAME.endswith(".pkl")


def _fixture(tmp_path: Path):
    python = tmp_path / "python.exe"
    python.write_text("fixture", encoding="utf-8")
    four_d = tmp_path / "4D-Humans"
    four_d.mkdir()
    (four_d / "track.py").write_text("# fixture\n", encoding="utf-8")
    data = four_d / "data"
    data.mkdir()
    (data / SMPL_FILENAME).write_text("fixture", encoding="utf-8")
    phalp = tmp_path / "PHALP"
    (phalp / "phalp").mkdir(parents=True)
    return python, four_d, phalp


def _valid_probe(phalp: Path) -> dict:
    return {
        "python": "3.10.0",
        "import_torch": True,
        "import_cv2": True,
        "import_joblib": True,
        "import_hmr2": True,
        "import_phalp": True,
        "import_neural_renderer": True,
        "cuda_available": False,
        "cuda_device": None,
        "phalp_root": str((phalp / "phalp").resolve()),
        "phalp_tracker_match": True,
        "phalp_tracker_hashes": [PHALP_TRACKER_BLOB_SHA1],
        "nmr_authority_match": True,
        "nmr_url": NMR_REMOTE,
        "nmr_commit": NMR_REVISION,
    }


def test_preflight_accepts_exact_clean_phalp_checkout(tmp_path, monkeypatch):
    python, four_d, phalp = _fixture(tmp_path)

    monkeypatch.setattr(
        preflight_cli,
        "_repo_head",
        lambda repo, label: FOUR_D_HUMANS_REVISION if label == "4D-Humans" else PHALP_REVISION,
    )
    monkeypatch.setattr(preflight_cli, "_repo_clean", lambda repo, label: True)
    monkeypatch.setattr(preflight_cli, "_external_probe", lambda executable: _valid_probe(phalp))

    assert (
        preflight_cli.main(
            [
                "--python",
                str(python),
                "--repo",
                str(four_d),
                "--phalp-repo",
                str(phalp),
                "--allow-cpu",
            ]
        )
        == 0
    )


def test_preflight_rejects_phalp_head_drift(tmp_path, monkeypatch):
    python, four_d, phalp = _fixture(tmp_path)

    monkeypatch.setattr(
        preflight_cli,
        "_repo_head",
        lambda repo, label: FOUR_D_HUMANS_REVISION if label == "4D-Humans" else "0" * 40,
    )
    monkeypatch.setattr(preflight_cli, "_repo_clean", lambda repo, label: True)
    monkeypatch.setattr(preflight_cli, "_external_probe", lambda executable: _valid_probe(phalp))

    assert (
        preflight_cli.main(
            [
                "--python",
                str(python),
                "--repo",
                str(four_d),
                "--phalp-repo",
                str(phalp),
                "--allow-cpu",
            ]
        )
        == 1
    )


def test_preflight_rejects_phalp_import_from_other_checkout(tmp_path, monkeypatch):
    python, four_d, phalp = _fixture(tmp_path)
    other = tmp_path / "other-PHALP" / "phalp"
    other.mkdir(parents=True)

    monkeypatch.setattr(
        preflight_cli,
        "_repo_head",
        lambda repo, label: FOUR_D_HUMANS_REVISION if label == "4D-Humans" else PHALP_REVISION,
    )
    monkeypatch.setattr(preflight_cli, "_repo_clean", lambda repo, label: True)
    probe = _valid_probe(phalp)
    probe["phalp_root"] = str(other.resolve())
    monkeypatch.setattr(preflight_cli, "_external_probe", lambda executable: probe)

    assert (
        preflight_cli.main(
            [
                "--python",
                str(python),
                "--repo",
                str(four_d),
                "--phalp-repo",
                str(phalp),
                "--allow-cpu",
            ]
        )
        == 1
    )
