import json
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

    def test_failure_cleans_temporary_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "clip.mp4"
            source.write_bytes(b"fixture")
            output = root / "frames"

            def fake_run(argv, timeout):
                if argv[0] == "ffprobe":
                    return CompletedProcess(argv, 0, json.dumps({
                        "streams": [{"codec_name": "h264"}], "format": {"duration": "2"}}), "")
                raise RuntimeError("decoder failed")

            with patch("tools.video_sample_fast._run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    sample_video(source, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".twin-sample-*")), [])


if __name__ == "__main__":
    unittest.main()
