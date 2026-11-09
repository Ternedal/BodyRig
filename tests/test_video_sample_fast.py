import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess

from tools.video_sample_fast import sample_timestamps, sample_video


class FastVideoSamplingTests(unittest.TestCase):
    def test_timestamps_are_bounded_and_centered(self):
        self.assertEqual(sample_timestamps(10, 2), [2.5, 7.5])
        self.assertEqual(len(sample_timestamps(1000, 64)), 64)
        self.assertEqual(len(sample_timestamps(0.5, 12)), 1)

    def test_invalid_inputs(self):
        for duration in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                sample_timestamps(duration, 4)
        for count in (0, 65):
            with self.assertRaises(ValueError):
                sample_timestamps(10, count)

    def test_invalid_frame_bounds_fail_before_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "clip.mp4"
            source.write_bytes(b"fixture")
            for count in (0, -1, 65, 1.5, True, None):
                with self.subTest(count=count):
                    with patch("tools.video_sample_fast._run") as runner:
                        with self.assertRaises(ValueError):
                            sample_video(source, root / "frames", max_frames=count)
                        runner.assert_not_called()
                    self.assertFalse((root / "frames").exists())

    def test_sample_and_atomic_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "clip.mp4"
            source.write_bytes(b"fixture")
            output = root / "frames"
            calls = []

            def fake_run(argv, timeout):
                calls.append(argv)
                if argv[0] == "ffprobe":
                    return CompletedProcess(argv, 0, json.dumps({
                        "streams": [{"codec_name": "h264", "width": 640, "height": 360}],
                        "format": {"duration": "4.0"}}), "")
                Path(argv[-1]).write_bytes(b"jpeg")
                return CompletedProcess(argv, 0, "", "")

            with patch("tools.video_sample_fast._run", side_effect=fake_run):
                result = sample_video(source, output, max_frames=2)
            self.assertEqual(result["state"], "FRAMES_READY")
            self.assertEqual([f["timestamp_ms"] for f in result["frames"]], [1000, 3000])
            self.assertEqual(len(list(output.glob("frame-*.jpg"))), 2)
            self.assertEqual(json.loads((output / "manifest.json").read_text())["frames"], result["frames"])
            self.assertEqual(len(calls), 3)
            with self.assertRaises(FileExistsError):
                sample_video(source, output)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "FFmpeg binaries not installed")
    def test_real_ffmpeg_video_end_to_end(self):
        """Exercise actual decode and seek, not just a mocked command runner."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "synthetic.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10",
                            "-t", "3", "-c:v", "mpeg4", "-y", str(source)],
                           check=True, timeout=45)
            result = sample_video(source, root / "sampled", max_frames=3)
            self.assertEqual(result["state"], "FRAMES_READY")
            self.assertEqual(len(result["frames"]), 3)
            self.assertEqual(result["width"], 160)
            self.assertEqual(result["height"], 90)
            self.assertEqual(len({f["timestamp_ms"] for f in result["frames"]}), 3)
            self.assertTrue(all((root / "sampled" / f["file"]).stat().st_size > 0
                                for f in result["frames"]))

    def test_rejects_linked_source_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            real = root / "real"
            real.mkdir()
            (real / "clip.mp4").write_bytes(b"fixture")
            linked = root / "linked"
            try:
                linked.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks not available")
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                sample_video(linked / "clip.mp4", root / "out")

    def test_rejects_linked_output_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "clip.mp4"
            source.write_bytes(b"fixture")
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            try:
                linked.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks not available")
            with self.assertRaisesRegex(ValueError, "symlinks"):
                sample_video(source, linked / "out")

    def test_failure_cleans_temporary_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "clip.mp4"
            source.write_bytes(b"fixture")
            output = root / "frames"

            def fake_run(argv, timeout):
                if argv[0] == "ffprobe":
                    return CompletedProcess(argv, 0, json.dumps({
                        "streams": [{"codec_name": "h264", "width": 640, "height": 360}], "format": {"duration": "2"}}), "")
                raise RuntimeError("decoder failed")

            with patch("tools.video_sample_fast._run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    sample_video(source, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".twin-sample-*")), [])


if __name__ == "__main__":
    unittest.main()
