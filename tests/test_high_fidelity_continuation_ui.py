from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for Person Studio UI regressions")
def test_continuation_ui_behaviour() -> None:
    script = Path(__file__).with_name("high_fidelity_continuation_ui.cjs")
    # The Windows production-OS CI job runs the full Python suite under heavier
    # process startup/load than Linux. Keep Linux fail-fast while allowing one
    # slow Windows Node test-runner startup without turning a passing UI suite
    # into a flaky repository-authority failure.
    timeout_seconds = 90 if sys.platform == "win32" else 30
    result = subprocess.run(
        ["node", "--test", str(script)],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    assert result.returncode == 0, result.stdout + result.stderr
