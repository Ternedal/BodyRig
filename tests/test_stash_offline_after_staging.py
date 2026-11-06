"""The offline boundary after local source staging (BodyRig #1377).

Phase 1 needs Stash: selection and staging. Phase 2 must work from the local
snapshot alone. The launcher sets BODYRIG_STASH_OFFLINE=1 and removes the Stash
API key right after staging; these tests prove that a Stash call from phase 2
then fails closed, that processing inputs survive Stash and the share going
away, and that the launcher wires the boundary in the right place.
"""
import json
import os
import re
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bodyrig.stage_stash_sources import stage
from bodyrig.stash_fidelity_reference import StashFidelityReferenceError, _default_fetcher
from bodyrig.stash_source import OFFLINE_ENV, StashClient, StashConfig, StashGraphQLError

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "clone-body-from-stash.ps1"


class _NoNetwork:
    """Fail the test if anything opens a socket."""

    def __enter__(self):
        self._patch = patch.object(socket.socket, "connect", side_effect=AssertionError("network used after staging"))
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


class TestOfflineGuard(unittest.TestCase):
    def test_graphql_fails_closed_when_offline(self):
        calls = []
        client = StashClient(StashConfig(url="http://localhost:9999"),
                             transport=lambda q, v: calls.append(q) or {"version": {"version": "x"}})
        with patch.dict(os.environ, {OFFLINE_ENV: "1"}):
            with self.assertRaisesRegex(StashGraphQLError, "disabled after local source staging"):
                client.version()
        self.assertEqual(calls, [], "the transport must not even be reached")

    def test_real_http_path_never_connects_when_offline(self):
        client = StashClient(StashConfig(url="http://127.0.0.1:9", api_key="secret-key-value"))
        with patch.dict(os.environ, {OFFLINE_ENV: "1"}), _NoNetwork():
            with self.assertRaises(StashGraphQLError) as ctx:
                client.search_performers("anyone")
        self.assertNotIn("secret-key-value", str(ctx.exception))

    def test_reference_image_fetch_fails_closed_when_offline(self):
        client = StashClient(StashConfig(url="http://localhost:9999"))
        fetch = _default_fetcher(client)
        with patch.dict(os.environ, {OFFLINE_ENV: "1"}), _NoNetwork():
            with self.assertRaisesRegex(StashFidelityReferenceError, "disabled after local source staging"):
                fetch("http://localhost:9999/image/1")

    def test_online_behaviour_is_unchanged(self):
        client = StashClient(StashConfig(url="http://localhost:9999"),
                             transport=lambda q, v: {"version": {"version": "v0.27.0"}})
        env = {k: v for k, v in os.environ.items() if k != OFFLINE_ENV}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(client.version(), "v0.27.0")


class TestProcessingInputsAreLocal(unittest.TestCase):
    def test_staged_manifest_survives_stash_and_share_going_away(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            share = base / "share"  # stands in for the Stash media share
            share.mkdir()
            originals = []
            for i in range(3):
                path = share / f"scene-{i}.mp4"
                path.write_bytes(bytes([i]) * 4096)
                originals.append(path)
            manifest = base / "selection.json"
            manifest.write_text(json.dumps({
                "format": "bodyrig-stash-source-manifest", "version": 1,
                "selected": [{"path": str(p), "scene_id": str(i)} for i, p in enumerate(originals)],
            }))
            staged = stage(manifest, base / "out" / "local-source-snapshot")
            for path in originals:
                path.unlink()
            share.rmdir()  # Stash and the share are now gone
            snapshot = staged.parent.resolve()
            with patch.dict(os.environ, {OFFLINE_ENV: "1"}), _NoNetwork():
                selected = json.loads(staged.read_text())["selected"]
                for i, item in enumerate(selected):
                    path = Path(item["path"]).resolve()
                    self.assertIn(snapshot, path.parents, "every processing input must be inside the snapshot")
                    self.assertEqual(path.read_bytes(), bytes([i]) * 4096)
                    self.assertEqual(item["scene_id"], str(i), "non-path metadata is preserved")


class TestLauncherWiring(unittest.TestCase):
    """Static contract for clone-body-from-stash.ps1 (PowerShell is not run here)."""

    def setUp(self):
        self.text = LAUNCHER.read_text(encoding="utf-8")
        self.lines = self.text.splitlines()

    def _line(self, pattern, after=0):
        for number, line in enumerate(self.lines, 1):
            if number > after and re.search(pattern, line):
                return number
        self.fail(f"pattern not found in launcher after line {after}: {pattern}")

    def test_offline_is_set_and_key_removed_right_after_staging(self):
        staging = self._line(r'"bodyrig\.stage_stash_sources",\s*"--manifest"')
        offline = self._line(r"\$env:BODYRIG_STASH_OFFLINE\s*=\s*['\"]1['\"]")
        key_removed = self._line(r"Remove-Item\s+-LiteralPath\s+\(\"Env:\$ApiKeyEnv\"\)")
        # The first observation-analyzer block after staging is where phase 2 starts
        # (an earlier block at the top is only the preflight).
        observation = self._line(r"usingBuiltInObservationAnalyzer\)\s*\{", after=staging)
        self.assertLess(staging, offline)
        self.assertLess(offline, observation, "phase 2 must start offline")
        self.assertLess(staging, key_removed)
        self.assertLess(key_removed, observation)

    def test_api_key_variable_cannot_be_the_offline_guard(self):
        # ChatGPT review 5679976324: -ApiKeyEnv BODYRIG_STASH_OFFLINE would let the key
        # removal drop the guard. It is rejected case-insensitively before Stash selection,
        # and the guard is set after the key removal.
        reject = self._line(r'^if \(\$ApiKeyEnv\.Trim\(\) -ieq "BODYRIG_STASH_OFFLINE"\)')
        selection = self._line(r'"bodyrig\.stash_cli", "select"')
        self.assertLess(reject, selection)
        self.assertRegex(self.lines[reject], r"throw .*reserved for the offline guard")
        staging = self._line(r'"bodyrig\.stage_stash_sources",\s*"--manifest"')
        key_removed = self._line(r"Remove-Item\s+-LiteralPath\s+\(\"Env:\$ApiKeyEnv\"\)", after=staging)
        offline = self._line(r"\$env:BODYRIG_STASH_OFFLINE\s*=\s*['\"]1['\"]", after=staging)
        self.assertLess(key_removed, offline, "the guard is set last, so no removal can undo it")

    def test_stash_selection_happens_only_before_staging(self):
        staging = self._line(r'"bodyrig\.stage_stash_sources",\s*"--manifest"')
        for number, line in enumerate(self.lines, 1):
            if re.search(r"bodyrig\.(stash_cli|stash_performer_profile|stash_fidelity_reference|photoreal_stash_inventory)", line):
                self.assertLess(number, staging, f"Stash module used after staging at line {number}: {line.strip()}")

    def test_environment_is_restored_and_snapshot_removed_in_finally(self):
        finally_at = self._line(r"^\}\s*finally\s*\{")
        after = "\n".join(self.lines[finally_at - 1:])
        self.assertRegex(after, r"BODYRIG_STASH_OFFLINE")
        self.assertRegex(after, r"\$previousApiKey")
        self.assertRegex(after, r"Remove-Item -LiteralPath \$localSnapshot -Recurse -Force")

    def test_stale_snapshot_sweep_runs_before_staging(self):
        # A new OutputDir never has leftovers; the sweep looks at sibling run dirs.
        sweep = self._line(r"^Remove-StaleSnapshotsFromKilledRuns -Root \(Split-Path -Parent \$OutputDir\)")
        staging = self._line(r'"bodyrig\.stage_stash_sources",\s*"--manifest"')
        self.assertLess(sweep, staging)

    def test_success_is_initialised_before_the_cleanup_scope(self):
        # Codex P2 4398060811: finally reads $success under Set-StrictMode.
        init = self._line(r"^\$success = \$false")
        outer_try = self._line(r"^try \{", after=init - 1)
        self.assertLess(init, outer_try)
        self.assertLess(outer_try, self._line(r"^\}\s*finally\s*\{"))

    def test_timing_cannot_block_the_mandatory_cleanup(self):
        finally_at = self._line(r"^\}\s*finally\s*\{")
        tail = "\n".join(self.lines[finally_at - 1:])
        self.assertRegex(tail, r"Could not record staging timing")
        self.assertLess(tail.index("Could not record staging timing"), tail.index("Remove-Item -LiteralPath $localSnapshot"))
        self.assertRegex(tail, r"\$runLock\.Dispose\(\)")

    def test_run_lock_is_held_for_the_whole_run(self):
        lock = self._line(r"\$runLock = \[System\.IO\.File\]::Open\(.*FileShare\]::None\)")
        self.assertLess(lock, self._line(r"^try \{", after=lock))

    def test_timing_is_recorded_without_paths(self):
        self.assertRegex(self.text, r'"--timing-out"')
        self.assertRegex(self.text, r"processing_seconds")
        self.assertRegex(self.text, r"\[switch\]\$DirectSourceBenchmark")


if __name__ == "__main__":
    unittest.main()


class TestStageOnly(unittest.TestCase):
    """-StageOnly: the rig check that takes minutes instead of a multi-day clone."""

    def setUp(self):
        self.lines = LAUNCHER.read_text(encoding="utf-8").splitlines()

    def _first(self, pattern, after=0):
        return next(n for n, line in enumerate(self.lines, 1) if n > after and re.search(pattern, line))

    def test_stage_only_stops_after_staging_and_before_processing(self):
        staging = self._first(r'"bodyrig\.stage_stash_sources",\s*"--manifest"')
        offline = self._first(r"\$env:BODYRIG_STASH_OFFLINE\s*=\s*['\"]1['\"]")
        stage_only = self._first(r"^if \(\$StageOnly\)", after=staging)
        stop = self._first(r"^\s*exit 0\s", after=stage_only)
        observation = self._first(r"usingBuiltInObservationAnalyzer\)\s*\{", after=staging)
        self.assertLess(staging, offline)
        self.assertLess(offline, stage_only, "the stage-only run also exercises the offline switch")
        self.assertLess(stage_only, stop)
        self.assertLess(stop, observation, "nothing expensive runs in a stage-only check")

    def test_stage_only_is_declared_and_recorded(self):
        text = "\n".join(self.lines)
        self.assertRegex(text, r"\[switch\]\$StageOnly")
        self.assertRegex(text, r"stage_only")
        self.assertRegex(text, r"-StageOnly and -DirectSourceBenchmark cannot be combined")



def _extract_function(text, name):
    start = text.index(f"function {name} {{")
    depth, i = 0, text.index("{", start)
    while True:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1


@unittest.skipUnless(__import__("shutil").which("pwsh"), "PowerShell 7 (pwsh) not on PATH")
class TestStaleSweepInPowerShell(unittest.TestCase):
    """Runs the launcher's real sweep function under pwsh (Codex P2 4398060821)."""

    def test_only_a_dead_runs_marked_snapshot_is_removed(self):
        import shutil
        import subprocess
        import sys

        function = _extract_function(LAUNCHER.read_text(encoding="utf-8"), "Remove-StaleSnapshotsFromKilledRuns")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            manifest = root / "m.json"
            manifest.write_text(json.dumps({"format": "bodyrig-stash-source-manifest", "version": 1,
                                            "selected": [{"path": str(source)}]}))

            def run_dir(name, *, snapshot="marked"):
                d = root / name
                d.mkdir()
                (d / "bodyrig-run.lock").write_text("")
                (d / "keep-output.txt").write_text("run output")
                if snapshot == "marked":
                    stage(manifest, d / "local-source-snapshot")
                elif snapshot == "unmarked":
                    (d / "local-source-snapshot").mkdir()
                    (d / "local-source-snapshot" / "user-data.txt").write_text("not ours")
                return d

            dead = run_dir("bodyrig-stash-dead")
            alive = run_dir("bodyrig-stash-alive")
            unmarked = run_dir("bodyrig-stash-unmarked", snapshot="unmarked")
            current = run_dir("bodyrig-stash-current")
            lock = open(alive / "bodyrig-run.lock", "r+b")  # a live run holds its lock
            try:
                if os.name != "nt":
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)  # .NET maps FileShare.None to flock on Unix
                script = (function + "\n$ErrorActionPreference = 'Stop'\n"
                          f"$BodyRigPython = '{sys.executable}'\n"
                          f"Remove-StaleSnapshotsFromKilledRuns -Root '{root}' -Current '{current}'\n")
                env = dict(os.environ, PYTHONPATH=str(ROOT))
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
                                        capture_output=True, text=True, env=env, timeout=120)
            finally:
                lock.close()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((dead / "local-source-snapshot").exists(), "the killed run's snapshot is removed")
            self.assertTrue((dead / "keep-output.txt").exists(), "nothing else of the killed run is touched")
            self.assertTrue((alive / "local-source-snapshot").exists(), "a live run's snapshot is never removed")
            self.assertTrue((unmarked / "local-source-snapshot" / "user-data.txt").exists(), "unmarked data is kept")
            self.assertTrue((current / "local-source-snapshot").exists(), "the current run is skipped")
            self.assertIn("still active", result.stdout)
            self.assertEqual(source.read_bytes(), b"video")


@unittest.skipUnless(__import__("shutil").which("pwsh"), "PowerShell 7 (pwsh) not on PATH")
class TestReservedApiKeyEnvInPowerShell(unittest.TestCase):
    """ChatGPT review 5679976324: the API-key variable may not be the offline guard itself."""

    def test_launcher_rejects_the_guard_name_case_insensitively_before_any_work(self):
        import shutil
        import subprocess

        for name in ("BODYRIG_STASH_OFFLINE", "bodyrig_stash_offline", " Bodyrig_Stash_Offline "):
            with tempfile.TemporaryDirectory() as tmp:
                env = dict(os.environ, STASH_URL="http://127.0.0.1:9")
                # Catch the exception and print its message as one plain line: pwsh's own error
                # view wraps at the terminal width, which splits the message on CI runners.
                def q(value):
                    return "'" + str(value).replace("'", "''") + "'"

                command = (f"try {{ & {q(LAUNCHER)} -PerformerId 1 -ExternalPython python -FourDHumansRepo {q(tmp)} "
                           f"-BodyId check -ApiKeyEnv {q(name)} -StageOnly -OutputDir {q(Path(tmp) / 'out')}; exit 0 }} "
                           "catch { [Console]::Out.WriteLine('ERR: ' + $_.Exception.Message); exit 1 }")
                result = subprocess.run(
                    [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", command],
                    capture_output=True, text=True, env=env, cwd=tmp, timeout=120)
                self.assertNotEqual(result.returncode, 0, name)
                self.assertIn("ERR: -ApiKeyEnv cannot be BODYRIG_STASH_OFFLINE: that variable is reserved for the offline guard.",
                              result.stdout, name + " | " + result.stderr)
                self.assertFalse((Path(tmp) / "out").exists(), "rejected before any output is created")
