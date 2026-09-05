from __future__ import annotations

from pathlib import Path


def test_physical_handoff_is_create_only_and_rolls_back_only_new_output() -> None:
    source = (Path(__file__).resolve().parents[1] / "bodyrig" / "high_fidelity_physical_acceptance.py").read_text(encoding="utf-8")
    assert 'if final.exists()' in source
    assert 'physical acceptance output is create-only' in source
    assert 'os.replace(staging, final)' in source
    assert 'if moved and not verified and final.exists()' in source
    assert 'shutil.rmtree(final, ignore_errors=True)' in source
