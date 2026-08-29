from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from bodyrig.bridges import file_command_bridge


def test_file_command_bridge_publishes_status_after_child_return(tmp_path):
    request = tmp_path / "request.json"
    stdout = tmp_path / "stdout.json"
    stderr = tmp_path / "stderr.log"
    status = tmp_path / "status.json"
    child = tmp_path / "child.py"
    request.write_text('{"hello":"world"}\n', encoding="utf-8")
    child.write_text(
        "import json,sys\n"
        "payload=json.load(sys.stdin)\n"
        "json.dump({'ok': payload['hello'] == 'world'}, sys.stdout)\n",
        encoding="utf-8",
    )

    rc = file_command_bridge.main(
        [
            "--stdin-file", str(request),
            "--stdout-file", str(stdout),
            "--stderr-file", str(stderr),
            "--status-file", str(status),
            "--",
            sys.executable,
            str(child),
        ]
    )

    assert rc == 0
    assert json.loads(stdout.read_text(encoding="utf-8")) == {"ok": True}
    assert stderr.read_text(encoding="utf-8") == ""
    assert json.loads(status.read_text(encoding="utf-8")) == {
        "format": "bodyrig-file-command-status",
        "version": 1,
        "returncode": 0,
    }


def test_file_command_bridge_does_not_wait_for_descendant_file_handle(tmp_path):
    request = tmp_path / "request.json"
    stdout = tmp_path / "stdout.txt"
    stderr = tmp_path / "stderr.log"
    status = tmp_path / "status.json"
    child = tmp_path / "child.py"
    request.write_text("{}\n", encoding="utf-8")
    child.write_text(
        "import json,subprocess,sys\n"
        "json.load(sys.stdin)\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4)'])\n"
        "sys.stdout.write('parent-exited')\n"
        "sys.stdout.flush()\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    rc = file_command_bridge.main(
        [
            "--stdin-file", str(request),
            "--stdout-file", str(stdout),
            "--stderr-file", str(stderr),
            "--status-file", str(status),
            "--",
            sys.executable,
            str(child),
        ]
    )
    elapsed = time.monotonic() - started

    assert rc == 0
    assert stdout.read_text(encoding="utf-8") == "parent-exited"
    assert json.loads(status.read_text(encoding="utf-8"))["returncode"] == 0
    assert elapsed < 2.5


def test_file_command_bridge_status_records_target_failure(tmp_path):
    request = tmp_path / "request.json"
    stdout = tmp_path / "stdout.txt"
    stderr = tmp_path / "stderr.log"
    status = tmp_path / "status.json"
    request.write_text("{}\n", encoding="utf-8")

    rc = file_command_bridge.main(
        [
            "--stdin-file", str(request),
            "--stdout-file", str(stdout),
            "--stderr-file", str(stderr),
            "--status-file", str(status),
            "--",
            sys.executable,
            "-c",
            "import sys; print('boom', file=sys.stderr); raise SystemExit(7)",
        ]
    )

    assert rc == 7
    assert "boom" in stderr.read_text(encoding="utf-8")
    assert json.loads(status.read_text(encoding="utf-8"))["returncode"] == 7
