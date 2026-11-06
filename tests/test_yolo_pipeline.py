import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from slowmo_qa.label_scene_dataset import DatasetLabeler
from slowmo_qa.scene_analysis import SceneAnalyzer
from slowmo_qa.train_detector import prepare_yolo_dataset


class YoloDatasetTests(unittest.TestCase):
    def test_labeler_saves_yolo_normalized_boxes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            images_dir = root / "images"
            images_dir.mkdir()
            image_path = images_dir / "frame.png"
            cv2.imwrite(str(image_path), np.zeros((100, 200, 3), dtype=np.uint8))
            labeler = DatasetLabeler(images_dir)
            labeler.boxes = [(1, 20, 10, 100, 90)]

            labeler._save()

            label = (root / "labels" / "frame.txt").read_text().strip()
            self.assertEqual(label, "1 0.300000 0.500000 0.400000 0.800000")

    def test_trainer_splits_labeled_images_and_writes_class_map(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            images_dir = root / "images"
            labels_dir = root / "labels"
            images_dir.mkdir()
            labels_dir.mkdir()
            class_ids = {"one": 0, "two": 1, "three": 2, "four": 1}
            for name in (*class_ids, "unlabeled"):
                image_path = images_dir / f"{name}.png"
                cv2.imwrite(
                    str(image_path), np.zeros((10, 10, 3), dtype=np.uint8))
                if name in class_ids:
                    (labels_dir / f"{name}.txt").write_text(
                        f"{class_ids[name]} 0.5 0.5 0.2 0.2\n",
                        encoding="utf-8",
                    )

            config_path = prepare_yolo_dataset(
                images_dir, labels_dir, root / "training")

            self.assertTrue(config_path.is_file())
            config = config_path.read_text(encoding="utf-8")
            self.assertIn("0: player", config)
            self.assertIn("1: enemy", config)
            self.assertIn("2: projectile", config)
            self.assertEqual(
                len(list((root / "training" / "images" / "train").glob("*.png")))
                + len(list((root / "training" / "images" / "val").glob("*.png"))),
                4,
            )

    def test_yolo_model_predictions_become_scene_objects(self):
        class FakeBox:
            cls = np.array([1])
            xyxy = np.array([[10.0, 20.0, 50.0, 70.0]])
            conf = np.array([0.91])

        model = Mock()
        model.names = {0: "player", 1: "enemy", 2: "projectile"}
        model.predict.return_value = [types.SimpleNamespace(boxes=[FakeBox()])]

        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "model.pt"
            model_path.touch()
            fake_ultralytics = types.SimpleNamespace(YOLO=Mock(return_value=model))
            with patch.dict("sys.modules", {"ultralytics": fake_ultralytics}):
                analyzer = SceneAnalyzer(
                    Path(temp_dir) / "templates", model_path=model_path)
                detections = analyzer._detect(
                    np.zeros((100, 100, 3), dtype=np.uint8))

        self.assertTrue(analyzer.available)
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].category, "enemies")
        self.assertEqual(detections[0].box, (10, 20, 40, 50))
        self.assertEqual(detections[0].center, (30, 45))
        self.assertEqual(detections[0].score, 0.91)


if __name__ == "__main__":
    unittest.main()
