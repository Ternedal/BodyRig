from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bodyrig.identity_capture import IdentityCaptureError, run_identity_capture


def test_identity_capture_nonzero_exit_surfaces_adapter_log_tail(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        "import sys\n"
        "print('capture-detail: no usable frame', file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    proof = {
        "source_count": 1,
        "track_id": "s00-t1",
        "observed_frames": 60,
    }

    with pytest.raises(IdentityCaptureError, match="capture-detail: no usable frame"):
        run_identity_capture(
            [sys.executable, str(adapter)],
            sources=[source],
            proof=proof,
            workspace=workspace,
            adapter="fixture",
            revision="1",
            timeout_seconds=10,
        )

    assert not workspace.exists()
