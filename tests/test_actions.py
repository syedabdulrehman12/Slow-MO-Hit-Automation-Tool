import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from slowmo_qa.actions import ActionError, Executor
from slowmo_qa.config import Action


class AssertScreenTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temp_dir.name)
        self.executor = Executor(
            cfg=Mock(),
            device=Mock(),
            run_dir=self.run_dir,
            logger=Mock(),
            delay=0,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_passes_when_configured_screenshots_change_enough(self):
        before = self.run_dir / "before.png"
        after = self.run_dir / "after.png"
        before.touch()
        after.touch()
        action = Action(
            name="Screen reacted to tap",
            type="assert_screen",
            raw={
                "before_file": before.name,
                "after_file": after.name,
                "min_diff_ratio": 0.05,
            },
        )

        with patch(
            "slowmo_qa.actions.vision.pixel_diff_ratio",
            return_value=0.10,
        ) as diff:
            result = self.executor._assert_screen(action)

        diff.assert_called_once_with(before, after)
        self.assertEqual(result.status, "ok")
        self.assertIn("minimum 0.05", result.detail)

    def test_fails_when_configured_screenshots_do_not_change_enough(self):
        before = self.run_dir / "before.png"
        after = self.run_dir / "after.png"
        before.touch()
        after.touch()
        action = Action(
            name="Screen reacted to tap",
            type="assert_screen",
            raw={
                "before_file": before.name,
                "after_file": after.name,
                "min_diff_ratio": 0.05,
            },
        )

        with patch(
            "slowmo_qa.actions.vision.pixel_diff_ratio",
            return_value=0.01,
        ):
            result = self.executor._assert_screen(action)

        self.assertEqual(result.status, "fail")

    def test_fails_clearly_when_a_configured_screenshot_is_missing(self):
        action = Action(
            name="Screen reacted to tap",
            type="assert_screen",
            raw={
                "before_file": "missing-before.png",
                "after_file": "missing-after.png",
            },
        )

        with self.assertRaisesRegex(ActionError, "image not found"):
            self.executor._assert_screen(action)

    @patch("slowmo_qa.actions.time.sleep")
    def test_long_wait_logs_progress(self, sleep):
        action = Action(
            name="Wait for gameplay",
            type="wait",
            raw={"seconds": 11},
        )

        result = self.executor._wait(action)

        self.assertEqual(result.status, "ok")
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [5.0, 5.0, 1.0],
        )
        self.executor.log.info.assert_has_calls([
            call("%s: %.0f seconds remaining", "Wait for gameplay", 6.0),
            call("%s: %.0f seconds remaining", "Wait for gameplay", 1.0),
        ])
