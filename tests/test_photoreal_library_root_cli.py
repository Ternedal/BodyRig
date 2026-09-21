from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_photoreal_link_cli as m4_cli
import bodyrig.digital_twin_photoreal_m5_link_cli as m5_cli


PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
M4_LINK_ID = "dtphoto-" + "1" * 32
M5_LINK_ID = "dtphotom5-" + "2" * 32


def test_m4_cli_threads_explicit_library_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    seen: dict[str, Path] = {}

    def write(root, **kwargs):
        seen["write_root"] = Path(root)
        return {
            "link_id": M4_LINK_ID,
            "person_id": PERSON_ID,
            "person_revision": PERSON_REVISION,
            "composition_authority_id": "dtcomp-" + "3" * 32,
            "photoreal_binding_id": "photoperson-" + "4" * 32,
            "visual_authority": "photoreal-v2-p3",
        }

    def directory(root, **kwargs):
        seen["dir_root"] = Path(root)
        return Path(root) / "m4"

    monkeypatch.setattr(m4_cli, "write_photoreal_link", write)
    monkeypatch.setattr(m4_cli, "photoreal_link_dir", directory)

    code = m4_cli.main(
        [
            "--composition-authority-dir",
            "composition",
            "--photoreal-person-binding",
            "binding.json",
            "--p3-physical-review",
            "p3.json",
            "--bodyrig-revision",
            "a" * 40,
            "--library-root",
            str(library),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert seen["write_root"] == library.resolve()
    assert seen["dir_root"] == library.resolve()
    assert payload["library_root"] == str(library.resolve())


def test_m5_cli_threads_explicit_library_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    seen: dict[str, Path] = {}

    def write(root, **kwargs):
        seen["write_root"] = Path(root)
        return {
            "link_id": M5_LINK_ID,
            "person_id": PERSON_ID,
            "person_revision": PERSON_REVISION,
            "m4_photoreal_link_id": M4_LINK_ID,
            "visual_authority": "photoreal-v2-p3",
        }

    def directory(root, **kwargs):
        seen["dir_root"] = Path(root)
        return Path(root) / "m5"

    monkeypatch.setattr(m5_cli, "write_photoreal_m5_link", write)
    monkeypatch.setattr(m5_cli, "photoreal_m5_link_dir", directory)

    code = m5_cli.main(
        [
            "--composition-authority-dir",
            "composition",
            "--acceptance-dir",
            "acceptance",
            "--m4-photoreal-link-dir",
            "m4-link",
            "--bodyrig-revision",
            "a" * 40,
            "--library-root",
            str(library),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert seen["write_root"] == library.resolve()
    assert seen["dir_root"] == library.resolve()
    assert payload["library_root"] == str(library.resolve())
