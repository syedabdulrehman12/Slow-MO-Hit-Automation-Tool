import unittest
from types import SimpleNamespace
from unittest.mock import patch

from slowmo_qa.device import AdbError, Device


class WakeAndDismissSwipeLockTests(unittest.TestCase):
    def setUp(self):
        self.device = Device()

    @patch("slowmo_qa.device.time.sleep")
    def test_wakes_without_swiping_when_lock_screen_is_not_showing(self, _sleep):
        with patch.object(
            self.device,
            "shell",
            side_effect=["", "mShowingLockscreen=false"],
        ) as shell, patch.object(self.device, "swipe_device") as swipe:
            self.assertFalse(self.device.wake_and_dismiss_swipe_lock())

        shell.assert_any_call("input", "keyevent", "KEYCODE_WAKEUP")
        swipe.assert_not_called()

    @patch("slowmo_qa.device.time.sleep")
    def test_dismisses_swipe_only_lock(self, _sleep):
        with patch.object(
            self.device,
            "shell",
            side_effect=[
                "",
                "mShowingLockscreen=true",
                "mShowingLockscreen=false",
            ],
        ), patch.object(self.device, "screen_size", return_value=(1000, 2000)), \
                patch.object(self.device, "swipe_device") as swipe:
            self.assertTrue(self.device.wake_and_dismiss_swipe_lock())

        swipe.assert_called_once_with(500, 1600, 500, 400, duration_ms=350)

    @patch("slowmo_qa.device.time.sleep")
    def test_uses_window_keyguard_state_when_policy_field_is_missing(self, _sleep):
        with patch.object(
            self.device,
            "shell",
            side_effect=[
                "",
                "policy output without lock state",
                "isKeyguardShowing=false",
            ],
        ) as shell, patch.object(self.device, "swipe") as swipe:
            self.assertFalse(self.device.wake_and_dismiss_swipe_lock())

        self.assertIn(
            ("dumpsys", "window"),
            [call.args for call in shell.call_args_list],
        )
        swipe.assert_not_called()

    @patch("slowmo_qa.device.time.sleep")
    @patch("slowmo_qa.device.time.monotonic", side_effect=[0, 4])
    def test_fails_when_lock_screen_remains(self, _monotonic, _sleep):
        with patch.object(
            self.device,
            "shell",
            side_effect=["", "mShowingLockscreen=true", "mShowingLockscreen=true"],
        ), patch.object(self.device, "screen_size", return_value=(1000, 2000)), \
                patch.object(self.device, "swipe_device"):
            with self.assertRaisesRegex(AdbError, "will not enter or bypass"):
                self.device.wake_and_dismiss_swipe_lock()


class GameInputBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.device = Device()
        self.focused_game_window = (
            "mCurrentFocus=Window{abc u0 com.gdm.slowmo/"
            "com.unity3d.player.UnityPlayerActivity}\n"
            "Window #0 Window{abc u0 com.gdm.slowmo/"
            "com.unity3d.player.UnityPlayerActivity}:\n"
            "  Frames: parent=[0,0][1000,2000] "
            "frame=[10,20][990,1980]\n"
        )

    def test_tap_is_sent_inside_focused_game_window(self):
        with patch.object(
            self.device, "shell",
            side_effect=[
                self.focused_game_window,
                self.focused_game_window,
                "",
            ],
        ) as shell:
            self.device.tap("com.gdm.slowmo", 500, 1000)

        self.assertEqual(shell.call_count, 3)
        self.assertEqual(shell.call_args_list[-1].args, ("sh",))
        script = shell.call_args_list[-1].kwargs["input_text"]
        self.assertIn("input tap 500 1000", script)
        self.assertIn("mCurrentFocus=Window{", script)

    def test_swipe_is_sent_when_both_endpoints_are_inside_game_window(self):
        with patch.object(
            self.device, "shell",
            side_effect=[
                self.focused_game_window,
                self.focused_game_window,
                "",
            ],
        ) as shell:
            self.device.swipe("com.gdm.slowmo", 500, 1000, 500, 500, 250)

        self.assertIn(
            "input swipe 500 1000 500 500 250",
            shell.call_args_list[-1].kwargs["input_text"],
        )

    def test_batch_checks_focus_once_then_sends_each_input_in_one_adb_call(self):
        with patch.object(
            self.device, "shell",
            side_effect=[
                self.focused_game_window,
                self.focused_game_window,
                "",
            ],
        ) as shell:
            self.device.send_game_inputs("com.gdm.slowmo", [
                ("tap", (500, 1000)),
                ("swipe", (500, 1000, 500, 500, 250)),
            ])

        self.assertEqual(shell.call_count, 3)
        self.assertEqual(shell.call_args_list[-1].args, ("sh",))
        script = shell.call_args_list[-1].kwargs["input_text"]
        self.assertEqual(script.count("dumpsys window"), 1)
        self.assertIn("input tap 500 1000", script)
        self.assertIn("input swipe 500 1000 500 500 250", script)
        self.assertLess(
            script.index("dumpsys window"),
            script.index("input tap 500 1000"),
        )
        self.assertLess(
            script.index("dumpsys window"),
            script.index("input swipe 500 1000 500 500 250"),
        )

    def test_large_input_batch_is_sent_via_stdin_not_process_arguments(self):
        gestures = [("tap", (500, 1000))] * 480
        with patch.object(
            self.device, "shell",
            side_effect=[
                self.focused_game_window,
                self.focused_game_window,
                "",
            ],
        ) as shell:
            self.device.send_game_inputs("com.gdm.slowmo", gestures)

        command_call = shell.call_args_list[-1]
        self.assertEqual(command_call.args, ("sh",))
        self.assertEqual(
            command_call.kwargs["input_text"].count("input tap 500 1000"),
            480,
        )
        self.assertNotIn("input_text", command_call.args)

    def test_shell_forwards_script_to_subprocess_stdin(self):
        with patch(
            "slowmo_qa.device.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ) as run:
            self.device.shell("sh", input_text="echo ready\n", timeout=120)

        self.assertEqual(run.call_args.args[0], ["adb", "shell", "sh"])
        self.assertEqual(run.call_args.kwargs["input"], "echo ready\n")

    def test_tap_is_refused_when_another_app_is_focused(self):
        output = self.focused_game_window.replace(
            "com.gdm.slowmo", "com.android.settings")
        with patch.object(self.device, "shell", return_value=output) as shell:
            with self.assertRaisesRegex(AdbError, "focused package"):
                self.device.tap("com.gdm.slowmo", 500, 1000)

        self.assertEqual(shell.call_count, 1)
        self.assertEqual(shell.call_args.args, ("dumpsys", "window"))

    def test_tap_is_refused_when_focused_window_bounds_are_missing(self):
        output = self.focused_game_window.split("Window #0")[0]
        with patch.object(self.device, "shell", side_effect=[
            output, output,
        ]) as shell:
            with self.assertRaisesRegex(AdbError, "window bounds"):
                self.device.tap("com.gdm.slowmo", 500, 1000)

        self.assertEqual(shell.call_count, 2)
        self.assertEqual(shell.call_args.args, ("dumpsys", "window", "windows"))

    def test_tap_is_refused_outside_the_game_window(self):
        with patch.object(
            self.device, "shell",
            side_effect=[self.focused_game_window, self.focused_game_window],
        ) as shell:
            with self.assertRaisesRegex(AdbError, "outside"):
                self.device.tap("com.gdm.slowmo", 5, 10)

        self.assertEqual(shell.call_count, 2)
        self.assertEqual(shell.call_args.args, ("dumpsys", "window", "windows"))

    def test_swipe_is_refused_if_either_endpoint_is_outside_the_game_window(self):
        with patch.object(
            self.device, "shell",
            side_effect=[self.focused_game_window, self.focused_game_window],
        ) as shell:
            with self.assertRaisesRegex(AdbError, "outside"):
                self.device.swipe(
                    "com.gdm.slowmo", 500, 1000, 500, 10)

        self.assertEqual(shell.call_count, 2)
        self.assertEqual(shell.call_args.args, ("dumpsys", "window", "windows"))


if __name__ == "__main__":
    unittest.main()
