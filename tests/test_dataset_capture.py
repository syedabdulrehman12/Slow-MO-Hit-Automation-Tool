import json
import tempfile
import unittest
from pathlib import Path

from slowmo_qa.dataset_capture import SceneDatasetCapture


class SceneDatasetCaptureTests(unittest.TestCase):
    def test_saves_frame_and_unlabeled_manifest_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            capture = SceneDatasetCapture(Path(temp_dir))

            def save_screenshot(path):
                path.write_bytes(b"frame")
                return path

            image_path = capture.capture(save_screenshot, timestamp=12.5)

            self.assertEqual(image_path.read_bytes(), b"frame")
            entry = json.loads(capture.manifest_path.read_text().strip())
            self.assertEqual(entry["image"], "images/frame_000001.png")
            self.assertEqual(entry["timestamp_monotonic"], 12.5)
            self.assertEqual(entry["label_status"], "unlabeled")
            self.assertEqual(capture.frames_captured, 1)

    def test_stops_capturing_at_frame_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            capture = SceneDatasetCapture(Path(temp_dir), max_frames=1)

            def save_screenshot(path):
                path.write_bytes(b"frame")
                return path

            capture.capture(save_screenshot, timestamp=1.0)

            self.assertTrue(capture.full)
            with self.assertRaisesRegex(RuntimeError, "1-frame limit"):
                capture.capture(save_screenshot, timestamp=2.0)

    def test_rejects_non_positive_frame_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "at least 1"):
                SceneDatasetCapture(Path(temp_dir), max_frames=0)


if __name__ == "__main__":
    unittest.main()
