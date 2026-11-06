"""Thin, testable wrapper around adb.exe."""
from __future__ import annotations
import re
import shlex
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path


class AdbError(RuntimeError):
    pass


GameInput = tuple[str, tuple[int, ...]]


class Device:
    def __init__(self, serial: str = "", adb: str = "adb"):
        self.serial = serial.strip()
        self.adb = adb
        self._size: tuple[int, int] | None = None

    # -- plumbing ---------------------------------------------------------
    def _base(self) -> list[str]:
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def run(
        self, *args: str, timeout: int = 30,
        input_text: str | None = None,
    ) -> str:
        proc = subprocess.run(
            self._base() + list(args),
            capture_output=True,
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise AdbError(
                f"adb {' '.join(args)} failed ({proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout

    def shell(
        self, *args: str, timeout: int = 30,
        input_text: str | None = None,
    ) -> str:
        return self.run(
            "shell", *args, timeout=timeout, input_text=input_text)

    # -- state ------------------------------------------------------------
    def require_online(self) -> None:
        proc = subprocess.run(
            self._base() + ["get-state"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if proc.returncode != 0 or proc.stdout.strip() != "device":
            raise AdbError(
                f"Device {self.serial or '(default)'} not authorized/online: "
                f"{proc.stderr.strip() or proc.stdout.strip()}")

    def is_package_installed(self, package: str) -> bool:
        return bool(self.shell("pm", "path", package).strip())

    def screen_size(self) -> tuple[int, int]:
        if self._size:
            return self._size
        out = self.shell("wm", "size")
        m = re.search(r"(\d+)\s*x\s*(\d+)", out)
        if not m:
            raise AdbError(f"Could not parse screen size from: {out!r}")
        self._size = (int(m.group(1)), int(m.group(2)))
        return self._size

    def current_activity(self) -> str:
        out = self.shell("dumpsys", "activity", "activities")
        m = re.search(r"mResumedActivity:.*?([\w.]+/[\w.$]+)", out)
        return m.group(1) if m else ""

    # -- input ------------------------------------------------------------
    def wake_and_dismiss_swipe_lock(self) -> bool:
        self.shell("input", "keyevent", "KEYCODE_WAKEUP")
        time.sleep(0.5)

        def lockscreen_showing() -> bool:
            policy = self.shell("dumpsys", "window", "policy")
            match = re.search(r"\bmShowingLockscreen=(true|false)\b", policy, re.I)
            if match:
                return match.group(1).lower() == "true"

            window = self.shell("dumpsys", "window")
            match = re.search(r"\bisKeyguardShowing=(true|false)\b", window, re.I)
            if match:
                return match.group(1).lower() == "true"

            raise AdbError(
                "Could not determine lock-screen state from `dumpsys window "
                "policy` or `dumpsys window`; check Android compatibility or "
                "disable auto_dismiss_swipe_lock.")

        if not lockscreen_showing():
            return False

        width, height = self.screen_size()
        self.swipe_device(width // 2, int(height * 0.8),
                          width // 2, int(height * 0.2), duration_ms=350)

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            time.sleep(0.25)
            if not lockscreen_showing():
                return True

        raise AdbError(
            "The lock screen is still showing after a swipe. SlowmoQA only "
            "dismisses swipe-only locks and will not enter or bypass a PIN, "
            "password, pattern, or biometric lock. Use a dedicated QA device "
            "or emulator configured without a secure lock, then retry.")

    def _focused_window_bounds(self, package: str) -> tuple[int, int, int, int]:
        focus_output = self.shell("dumpsys", "window")
        focus = re.search(
            r"\bmCurrentFocus=Window\{([^}]+)\}", focus_output)
        if not focus:
            raise AdbError("Could not determine the currently focused Android window")

        focused_window = focus.group(1)
        identity = re.search(r"\bu\d+\s+([\w.]+)/", focused_window)
        if not identity or identity.group(1) != package:
            actual_package = identity.group(1) if identity else "unknown"
            raise AdbError(
                f"Refusing game input: focused package is {actual_package!r}, "
                f"not {package!r}")

        output = self.shell("dumpsys", "window", "windows")
        headers = list(re.finditer(
            r"(?m)^\s*Window #\d+ Window\{([^}]+)\}:",
            output,
        ))
        for index, header in enumerate(headers):
            window = header.group(1)
            if window != focused_window:
                continue

            end = (
                headers[index + 1].start()
                if index + 1 < len(headers)
                else len(output)
            )
            block = output[header.end():end]
            frame = re.search(
                r"(?:\bmFrame=|\bframe=)"
                r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]",
                block,
            )
            if frame:
                bounds = tuple(map(int, frame.groups()))
                x1, y1, x2, y2 = bounds
                if x1 < x2 and y1 < y2:
                    return bounds
                break

        raise AdbError(
            f"Could not determine the focused game window bounds for {package!r}")

    def _require_game_point(
        self, package: str, point: tuple[int, int],
        bounds: tuple[int, int, int, int],
    ) -> None:
        x, y = point
        x1, y1, x2, y2 = bounds
        if not x1 <= x < x2 or not y1 <= y < y2:
            raise AdbError(
                f"Refusing game input at ({x},{y}): point is outside "
                f"the focused {package!r} window {bounds}")

    def tap(self, package: str, x: int, y: int) -> None:
        self.send_game_inputs(package, [("tap", (x, y))])

    def swipe(self, package: str, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300) -> None:
        self.send_game_inputs(
            package, [("swipe", (x1, y1, x2, y2, duration_ms))])

    def send_game_inputs(
        self, package: str, gestures: Sequence[GameInput],
    ) -> None:
        if not gestures:
            return

        bounds = self._focused_window_bounds(package)
        focus_pattern = shlex.quote(f" {package}/")
        script = [
            "set -e",
            "if ! dumpsys window "
            "| grep -F 'mCurrentFocus=Window{' "
            f"| grep -F {focus_pattern} >/dev/null; then",
            "  echo 'Refusing game input: game window lost focus' >&2",
            "  exit 73",
            "fi",
        ]
        for kind, points in gestures:
            if kind == "tap" and len(points) == 2:
                x, y = points
                self._require_game_point(package, (x, y), bounds)
                command = f"input tap {x} {y}"
            elif kind == "swipe" and len(points) == 5:
                x1, y1, x2, y2, duration_ms = points
                self._require_game_point(package, (x1, y1), bounds)
                self._require_game_point(package, (x2, y2), bounds)
                command = (
                    f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
            else:
                raise ValueError(f"Unsupported game input: {kind!r}")

            script.append(command)

        self.shell(
            "sh", timeout=30, input_text="\n".join(script) + "\n")

    def swipe_device(self, x1: int, y1: int, x2: int, y2: int,
                     duration_ms: int = 300) -> None:
        """Send a device-level swipe for the explicit lock-screen preflight."""
        self.shell("input", "swipe", str(x1), str(y1), str(x2), str(y2),
                   str(duration_ms))

    def back(self) -> None:
        self.shell("input", "keyevent", "4")

    # -- app lifecycle ----------------------------------------------------
    def launch(self, package: str, activity: str = "") -> None:
        if activity:
            self.shell("am", "start", "-n", f"{package}/{activity}")
        else:
            self.shell("monkey", "-p", package, "-c",
                       "android.intent.category.LAUNCHER", "1")

    def stop(self, package: str) -> None:
        self.shell("am", "force-stop", package)

    def pid_of(self, package: str) -> int | None:
        out = self.shell("pidof", package).strip()
        return int(out) if out.isdigit() else None

    # -- evidence ---------------------------------------------------------
    def screenshot(self, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = "/sdcard/_slowmoqa_shot.png"
        self.shell("screencap", "-p", tmp)
        self.run("pull", tmp, str(dest))
        self.shell("rm", "-f", tmp)
        return dest

    def logcat_dump(self, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            self._base() + ["shell", "logcat", "-d", "-v", "threadtime"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        out = proc.stdout or ""
        dest.write_text(out, encoding="utf-8", errors="replace")
        return dest

    def dump_ui(self, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = "/sdcard/_slowmoqa_ui.xml"
        self.shell("uiautomator", "dump", tmp)
        self.run("pull", tmp, str(dest))
        self.shell("rm", "-f", tmp)
        return dest