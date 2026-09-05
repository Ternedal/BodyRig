from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for Person Studio UI regressions")
def test_continuation_ui_behaviour() -> None:
    script = Path(__file__).with_name("high_fidelity_continuation_ui.cjs")
    result = subprocess.run(["node", "--test", str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
