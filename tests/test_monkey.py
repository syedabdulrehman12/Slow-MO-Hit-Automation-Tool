import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from slowmo_qa.monkey import (
    CIRCLE_SEGMENTS,
    CIRCLE_SWIPE_PROBABILITY,
    DEFAULT_PLAY_AREA,
    MAX_INPUTS_PER_ADB_CALL,
    Monkey,
    MonkeyConfig,
    SWIPE_DURATION_MAX_MS,
    SWIPE_DURATION_MIN_MS,
)
from slowmo_qa.scene_analysis import SceneAnalysis, SceneObject


class MonkeyRandomPointTests(unittest.TestCase):
    def setUp(self):
        self.device = Mock()
        self.device.screen_size.return_value = (1080, 2340)
        cfg = Mock()
        cfg.package = "com.gdm.slowmo"
        self.monkey = Monkey(
            cfg=cfg,
            mcfg=MonkeyConfig(),
            device=self.device,
            run_dir=Path("."),
            logger=Mock(),
        )
        self.monkey._analyze_scene_if_due = Mock()

    def test_default_play_area_includes_full_screen(self):
        self.assertEqual(
            DEFAULT_PLAY_AREA,
            {"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0},
        )

    def test_random_points_cover_all_three_top_screen_areas(self):
        self.monkey.rng = random.Random(42)
        points = [self.monkey._random_point() for _ in range(1000)]
        top_points = [(x, y) for x, y in points
                      if y < self.monkey._h * 0.15]

        self.assertTrue(any(x < self.monkey._w / 3 for x, _ in top_points))
        self.assertTrue(any(
            self.monkey._w / 3 <= x < self.monkey._w * 2 / 3
            for x, _ in top_points
        ))
        self.assertTrue(any(x >= self.monkey._w * 2 / 3 for x, _ in top_points))

    def test_random_points_never_exceed_screen_pixel_bounds(self):
        self.monkey.rng = random.Random(7)

        for _ in range(1000):
            x, y = self.monkey._random_point()
            self.assertGreaterEqual(x, 0)
            self.assertLess(x, self.monkey._w)
            self.assertGreaterEqual(y, 0)
            self.assertLess(y, self.monkey._h)

    def test_top_right_taps_are_sampled_below_status_bar(self):
        self.monkey.rng = random.Random(42)
        points = [self.monkey._random_tap_point() for _ in range(1000)]
        top_right = [
            (x, y) for x, y in points
            if x >= self.monkey._w * 2 / 3
            and y < self.monkey._h * 0.18
        ]

        self.assertTrue(top_right)
        self.assertTrue(all(y >= self.monkey._h * 0.05 for _, y in top_right))

    def test_random_taps_cover_right_side_across_screen_height(self):
        self.monkey.rng = random.Random(5)
        points = [self.monkey._random_tap_point() for _ in range(1000)]
        right_side = [(x, y) for x, y in points if x >= self.monkey._w / 2]
        center_taps = [
            (x, y) for x, y in points
            if self.monkey._w * 0.3 <= x <= self.monkey._w * 0.7
            and self.monkey._h * 0.3 <= y <= self.monkey._h * 0.7
        ]

        self.assertGreater(len(right_side), 400)
        self.assertGreater(len(center_taps), 400)
        self.assertTrue(any(x < self.monkey._w / 2 for x, _ in points))
        self.assertTrue(any(y < self.monkey._h / 3 for _, y in points))
        self.assertTrue(any(y >= self.monkey._h * 2 / 3 for _, y in points))

    def test_directional_swipes_cover_requested_paths(self):
        expected_patterns = (
            "left-to-right",
            "right-to-left",
            "top-to-bottom",
            "bottom-to-top",
            "top-left-to-top-right",
            "top-left-to-bottom-right",
            "top-right-to-bottom-left",
            "bottom-left-to-bottom-right",
            "bottom-center-left-to-center-right",
        )
        for pattern in expected_patterns:
            with self.subTest(pattern=pattern), patch.object(
                self.monkey.rng, "choice", return_value=pattern
            ):
                (x1, y1), (x2, y2), actual_pattern = (
                    self.monkey._random_directional_swipe())

                self.assertEqual(actual_pattern, pattern)
                self.assertGreaterEqual(x1, self.monkey._w * 0.08)
                self.assertLessEqual(x1, self.monkey._w * 0.92)
                self.assertGreaterEqual(x2, self.monkey._w * 0.08)
                self.assertLessEqual(x2, self.monkey._w * 0.92)
                self.assertGreaterEqual(y1, self.monkey._h * 0.15)
                self.assertLessEqual(y1, self.monkey._h * 0.92)
                self.assertGreaterEqual(y2, self.monkey._h * 0.15)
                self.assertLessEqual(y2, self.monkey._h * 0.92)
                if pattern in (
                    "left-to-right",
                    "top-left-to-top-right",
                    "bottom-left-to-bottom-right",
                    "top-left-to-bottom-right",
                    "bottom-center-left-to-center-right",
                ):
                    self.assertLess(x1, x2)
                if pattern == "right-to-left":
                    self.assertGreater(x1, x2)
                if pattern in ("top-to-bottom", "top-left-to-bottom-right",
                               "top-right-to-bottom-left"):
                    self.assertLess(y1, y2)
                if pattern == "bottom-to-top":
                    self.assertGreater(y1, y2)
                if pattern == "top-left-to-top-right":
                    self.assertLess(y1, self.monkey._h * 0.30)
                if pattern == "bottom-left-to-bottom-right":
                    self.assertGreater(y1, self.monkey._h * 0.80)
                if pattern == "bottom-center-left-to-center-right":
                    self.assertLess(x1, self.monkey._w * 0.5)
                    self.assertGreater(y1, self.monkey._h * 0.80)
                    self.assertGreater(x2, self.monkey._w * 0.5)
                    self.assertGreater(y1, y2)

    def test_swipe_starts_avoid_android_pull_down_edge(self):
        self.monkey.rng = random.Random(7)

        for _ in range(1000):
            _, y = self.monkey._random_swipe_start_point()
            self.assertGreaterEqual(y, self.monkey._h * 0.15)

    def test_monkey_defaults_to_more_swipes_than_taps(self):
        config = MonkeyConfig()

        self.assertEqual(config.inputs_per_burst, 120)
        self.assertEqual(config.tap_probability, 0.4)
        self.assertEqual(config.swipe_probability, 0.6)
        self.assertEqual(SWIPE_DURATION_MIN_MS, 120)
        self.assertEqual(SWIPE_DURATION_MAX_MS, 180)
        self.assertEqual(CIRCLE_SWIPE_PROBABILITY, 0.12)

    def test_tap_only_probability_never_generates_swipes(self):
        self.monkey.mcfg.inputs_per_burst = 200
        self.monkey.mcfg.tap_probability = 1.0
        self.monkey.mcfg.swipe_probability = 0.0
        self.monkey.rng = random.Random(42)

        self.monkey._run_burst(0)

        self.assertEqual(self.monkey.report.random_taps, 200)
        self.assertEqual(self.monkey.report.random_swipes, 0)
        self.assertEqual(
            self.device.send_game_inputs.call_count,
            math.ceil(200 / MAX_INPUTS_PER_ADB_CALL),
        )
        sent_inputs = [
            gesture
            for call in self.device.send_game_inputs.call_args_list
            for gesture in call.args[1]
        ]
        self.assertEqual(len(sent_inputs), 200)
        self.assertTrue(all(gesture[0] == "tap" for gesture in sent_inputs))
        self.assertTrue(all(
            len(call.args[1]) <= MAX_INPUTS_PER_ADB_CALL
            for call in self.device.send_game_inputs.call_args_list
        ))

    def test_burst_generates_more_swipes_than_taps_including_left_up(self):
        self.monkey.mcfg.inputs_per_burst = 1000
        self.monkey.rng = random.Random(29)
        _shot, actions = self.monkey._run_burst(0)

        taps = sum(action.startswith("tap ") for action in actions)
        swipes = sum(
            action.startswith((
                "swipe ", "circular swipe ", "left-to-right ",
                "right-to-left ", "top-to-bottom ", "bottom-to-top ",
                "top-left-to-top-right ", "top-left-to-bottom-right ",
                "top-right-to-bottom-left ",
                "bottom-left-to-bottom-right ",
                "bottom-center-left-to-center-right ",
            ))
            for action in actions
        )
        self.assertGreater(swipes, taps)
        self.assertGreater(taps, 350)
        self.assertLess(taps, 450)
        self.assertEqual(self.monkey.report.random_taps, taps)
        self.assertEqual(
            self.monkey.report.random_swipes,
            sum(self.monkey.report.swipe_patterns.values()),
        )
        self.assertTrue(all(
            self.monkey.report.swipe_patterns.get(pattern, 0) > 0
            for pattern in (
                "left-to-right", "right-to-left", "top-to-bottom",
                "bottom-to-top", "top-left-to-top-right",
                "top-left-to-bottom-right", "top-right-to-bottom-left",
                "bottom-left-to-bottom-right",
                "bottom-center-left-to-center-right", "circle",
            )
        ))

        sent_inputs = [
            gesture
            for call in self.device.send_game_inputs.call_args_list
            for gesture in call.args[1]
        ]
        swipe_durations = [
            gesture[1][-1] for gesture in sent_inputs
            if gesture[0] == "swipe"
        ]
        self.assertTrue(swipe_durations)
        self.assertTrue(all(
            SWIPE_DURATION_MIN_MS <= duration <= SWIPE_DURATION_MAX_MS
            for duration in swipe_durations
        ))

    def test_circle_swipe_points_form_closed_loop_below_top_edge(self):
        self.monkey.rng = random.Random(12)

        points = self.monkey._random_circle_points()

        self.assertEqual(len(points), CIRCLE_SEGMENTS + 1)
        self.assertEqual(points[0], points[-1])
        self.assertTrue(all(
            y >= self.monkey._h * 0.15 for _, y in points
        ))
        self.assertTrue(all(
            0 <= x < self.monkey._w and 0 <= y < self.monkey._h
            for x, y in points
        ))
        self.assertGreater(min(x for x, _ in points), 0)
        self.assertLess(max(x for x, _ in points), self.monkey._w - 1)
        self.assertGreaterEqual(
            min(y for _, y in points), self.monkey._h * 0.15
        )
        self.assertLess(max(y for _, y in points), self.monkey._h - 1)
        radius = math.hypot(
            points[0][0] - points[CIRCLE_SEGMENTS // 2][0],
            points[0][1] - points[CIRCLE_SEGMENTS // 2][1],
        ) / 2
        self.assertGreaterEqual(radius, min(self.monkey._w, self.monkey._h) * 0.07)

    def test_circle_swipe_emits_eight_swipe_segments(self):
        self.monkey.mcfg.inputs_per_burst = 1
        self.monkey.rng = Mock()
        self.monkey.rng.random.side_effect = [0.75, 0.01]
        self.monkey.rng.uniform.side_effect = [0.1, 0.5, 0.5]
        self.monkey.rng.randint.return_value = 100
        _shot, actions = self.monkey._run_burst(0)

        sent_inputs = [
            gesture
            for call in self.device.send_game_inputs.call_args_list
            for gesture in call.args[1]
        ]
        self.assertEqual(
            sum(gesture[0] == "swipe" for gesture in sent_inputs),
            CIRCLE_SEGMENTS,
        )
        self.assertEqual(self.monkey.report.random_swipes, CIRCLE_SEGMENTS)
        self.assertEqual(
            self.monkey.report.swipe_patterns["circle"], CIRCLE_SEGMENTS)
        self.assertEqual(len(actions), 1)
        self.assertIn("circular swipe pattern", actions[0])

    def test_default_mode_checks_game_window_for_each_input(self):
        self.monkey.mcfg.inputs_per_burst = 70
        self.monkey.rng = random.Random(8)

        self.monkey._run_burst(0)
        sent_inputs = [
            gesture
            for call in self.device.send_game_inputs.call_args_list
            for gesture in call.args[1]
        ]
        self.assertGreater(self.device.send_game_inputs.call_count, 1)
        self.assertEqual(len(sent_inputs), self.monkey.report.inputs_sent)
        self.assertGreaterEqual(self.monkey.report.inputs_sent, 70)
        self.assertTrue(all(
            call.args[0] == "com.gdm.slowmo"
            and len(call.args[1]) <= MAX_INPUTS_PER_ADB_CALL
            for call in self.device.send_game_inputs.call_args_list
        ))


class MonkeyLiveTargetingTests(unittest.TestCase):
    def test_captures_dataset_frames_without_templates(self):
        device = Mock()
        device.screen_size.return_value = (1080, 2340)
        cfg = Mock()
        cfg.package = "com.gdm.slowmo"
        analysis = SceneAnalysis(
            timestamp=1.0,
            frame_size=(1080, 2340),
            objects=(),
            target=None,
            recommended_swipe=None,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            monkey = Monkey(
                cfg, MonkeyConfig(), device, run_dir, Mock())
            monkey.scene_analyzer = Mock(
                available=False,
                analyze=Mock(return_value=analysis),
            )
            device.screenshot.side_effect = (
                lambda path: Path(path).write_bytes(b"frame"))

            monkey._analyze_scene_if_due()

            image_path = (
                run_dir / "scene_dataset" / "images" / "frame_000001.png")
            self.assertTrue(image_path.is_file())
            self.assertTrue((run_dir / "scene_latest.png").is_file())
            self.assertEqual(monkey.report.scene_frames, 1)
            analyze_call = monkey.scene_analyzer.analyze.call_args
            self.assertEqual(analyze_call.args[0], image_path)
            self.assertIsInstance(analyze_call.args[1], float)

    def test_scene_target_is_sent_as_a_bounded_game_swipe(self):
        device = Mock()
        device.screen_size.return_value = (1080, 2340)
        cfg = Mock()
        cfg.package = "com.gdm.slowmo"
        player = SceneObject(
            "player", "hero", (100, 1800, 50, 50), (125, 1825), 0.99)
        projectile = SceneObject(
            "projectiles", "dart", (500, 900, 30, 30), (515, 915), 0.98)
        analysis = SceneAnalysis(
            timestamp=1.0,
            frame_size=(1080, 2340),
            objects=(player, projectile),
            target=projectile,
            recommended_swipe=(player.center, projectile.center),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            monkey = Monkey(
                cfg, MonkeyConfig(), device, Path(temp_dir), Mock())
            monkey.scene_analyzer = Mock(
                available=True,
                analyze=Mock(return_value=analysis),
            )
            device.screenshot.side_effect = (
                lambda path: Path(path).write_bytes(b"test"))

            monkey._analyze_scene_if_due()

        device.send_game_inputs.assert_called_once_with(
            "com.gdm.slowmo",
            [("swipe", (125, 1825, 515, 915, 150))],
        )
        self.assertEqual(monkey.report.targeted_swipes, 1)
        self.assertEqual(monkey.report.scene_frames, 1)


if __name__ == "__main__":
    unittest.main()
