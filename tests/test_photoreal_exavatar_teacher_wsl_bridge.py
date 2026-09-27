from __future__ import annotations

import io
from pathlib import Path

from bodyrig import photoreal_exavatar_teacher_wsl_bridge as bridge


def test_bridge_writes_unicode_child_output_without_cp1252_failure(monkeypatch) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(bridge.sys, "stdout", stream)

    value = "teacher progress: 한국어 ✓ Δ"
    bridge._write_child_output(value)
    stream.flush()

    assert raw.getvalue().decode("utf-8") == value


def test_bridge_fallback_output_is_encoding_safe_without_binary_buffer(monkeypatch) -> None:
    class TextOnly:
        encoding = "cp1252"

        def __init__(self) -> None:
            self.value = ""
            self.flushed = False

        def write(self, value: str) -> None:
            self.value += value

        def flush(self) -> None:
            self.flushed = True

    stream = TextOnly()
    monkeypatch.setattr(bridge.sys, "stdout", stream)

    bridge._write_child_output("teacher progress: 한국어 ✓")

    assert "teacher progress:" in stream.value
    assert stream.flushed is True


def test_bridge_transports_missing_output_leaf_via_existing_parent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = tmp_path / "request.json"
    request.write_text("{}\n", encoding="utf-8")
    adapter = tmp_path / "adapter.py"
    adapter.write_text("print('adapter')\n", encoding="utf-8")
    output = tmp_path / "output"
    bridge_path = Path(bridge.__file__).resolve()
    revision = bridge.build_teacher_transport_revision(
        bridge_path=bridge_path,
        adapter_path=adapter,
    )

    calls: list[str] = []

    def converter(value: str) -> str:
        calls.append(value)
        resolved = Path(value).resolve()
        if resolved == request.resolve():
            return "/mnt/c/request.json"
        if resolved == adapter.resolve():
            return "/mnt/c/adapter.py"
        if resolved == tmp_path.resolve():
            return "/mnt/c/work"
        raise AssertionError(f"unexpected converter input: {resolved}")

    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = ""

    def fake_run(invocation, **kwargs):
        captured["invocation"] = list(invocation)
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(bridge, "make_wsl_path_converter", lambda _exe, _distribution: converter)
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    code = bridge.main(
        [
            "--distribution",
            "Ubuntu-22.04",
            "--wsl-exe",
            "wsl.exe",
            "--linux-python",
            "/opt/bodyrig-exavatar/bin/python",
            "--workspace-root",
            "/opt/bodyrig-exavatar/workspaces/bodyrig-42",
            "--runtime-preflight",
            "/opt/bodyrig-exavatar/workspaces/bodyrig-42/runtime-preflight.json",
            "--adapter-script",
            str(adapter),
            "--bodyrig-request",
            str(request),
            "--bodyrig-output",
            str(output),
            "--bodyrig-adapter",
            "exavatar-benchmark",
            "--bodyrig-revision",
            revision,
            "--bodyrig-upstream-commit",
            "d45268730c779fae4118f1a361cf9ff639bc4d1e",
        ]
    )

    assert code == 0
    invocation = captured["invocation"]
    index = invocation.index("--bodyrig-output")
    assert invocation[index + 1] == "/mnt/c/work/output"
    assert str(output.resolve()) not in calls
    assert str(tmp_path.resolve()) in calls
