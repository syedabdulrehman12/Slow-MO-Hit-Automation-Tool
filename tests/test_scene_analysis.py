import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from slowmo_qa.scene_analysis import SceneAnalyzer


class SceneAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        for category in ("player", "enemies", "projectiles"):
            (self.root / category).mkdir()

        self.player_template = np.zeros((12, 12, 3), dtype=np.uint8)
        cv2.rectangle(self.player_template, (1, 1), (10, 10), (20, 220, 40), 2)
        cv2.line(self.player_template, (2, 9), (9, 2), (250, 250, 250), 1)
        self.enemy_template = np.zeros((12, 12, 3), dtype=np.uint8)
        cv2.rectangle(self.enemy_template, (1, 1), (10, 10), (20, 30, 220), 2)
        cv2.circle(self.enemy_template, (6, 6), 3, (250, 250, 250), 1)
        self.projectile_template = np.zeros((8, 8, 3), dtype=np.uint8)
        cv2.line(self.projectile_template, (0, 0), (7, 7), (220, 220, 20), 2)
        cv2.line(self.projectile_template, (0, 7), (7, 0), (20, 220, 220), 1)

        cv2.imwrite(str(self.root / "player" / "hero.png"), self.player_template)
        cv2.imwrite(str(self.root / "enemies" / "slime.png"), self.enemy_template)
        cv2.imwrite(
            str(self.root / "projectiles" / "dart.png"),
            self.projectile_template,
        )
        self.analyzer = SceneAnalyzer(self.root, threshold=0.95)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_frame(self, name, projectile_offset=(0, 0)):
        frame = np.zeros((100, 140, 3), dtype=np.uint8)
        frame[72:84, 20:32] = self.player_template
        frame[50:62, 100:112] = self.enemy_template
        px, py = 60 + projectile_offset[0], 35 + projectile_offset[1]
        frame[py:py + 8, px:px + 8] = self.projectile_template
        path = self.root / name
        cv2.imwrite(str(path), frame)
        return path

    def test_classifies_scene_objects_and_recommends_projectile_target(self):
        frame = self._write_frame("frame.png")

        analysis = self.analyzer.analyze(frame, timestamp=1.0)

        self.assertEqual(analysis.frame_size, (140, 100))
        self.assertEqual(
            {(obj.category, obj.label) for obj in analysis.objects},
            {("player", "hero"), ("enemies", "slime"), ("projectiles", "dart")},
        )
        self.assertEqual(analysis.target.category, "projectiles")
        self.assertEqual(
            analysis.recommended_swipe,
            (analysis.objects[0].center, analysis.target.center)
            if analysis.objects[0].category == "player"
            else (next(o.center for o in analysis.objects if o.category == "player"),
                  analysis.target.center),
        )

    def test_tracks_projectile_motion_between_frames(self):
        first = self._write_frame("first.png")
        second = self._write_frame("second.png", projectile_offset=(4, 3))

        self.analyzer.analyze(first, timestamp=1.0)
        analysis = self.analyzer.analyze(second, timestamp=2.0)
        projectile = next(
            obj for obj in analysis.objects if obj.category == "projectiles")

        self.assertEqual(projectile.velocity, (4.0, 3.0))

    def test_analyzer_is_inactive_until_labeled_templates_exist(self):
        analyzer = SceneAnalyzer(self.root / "missing")

        self.assertFalse(analyzer.available)


if __name__ == "__main__":
    unittest.main()
