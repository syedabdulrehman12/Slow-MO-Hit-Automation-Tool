"""Action executor. One dispatch table; every action produces a StepResult."""
from __future__ import annotations
import datetime as _dt
import time
from pathlib import Path
from typing import Callable

from .assertions import assert_process_alive, wait_for_process
from .config import Action, Config
from .device import Device
from .evidence import StepResult
from . import ui, vision


class ActionError(RuntimeError):
    pass


class Executor:
    def __init__(self, cfg: Config, device: Device, run_dir: Path,
                 logger, delay: float | None = None):
        self.cfg = cfg
        self.device = device
        self.run_dir = run_dir
        self.log = logger
        self.delay = cfg.action_delay_seconds if delay is None else delay
        self._handlers: dict[str, Callable[[Action], StepResult]] = {
            "monkey": self._monkey,
            "wait": self._wait,
            "screenshot": self._screenshot,
            "tap": self._tap,
            "swipe": self._swipe,
            "swipe_normalized": self._swipe,
            "back": self._back,
            "assert_process": self._assert_process,
            "assert_no_crash": self._assert_no_crash,
            "dump_ui": self._dump_ui,
            "assert_screen": self._assert_screen,
            "wait_for_template": self._wait_for_template,
            "wait_for_text": self._wait_for_text,
            "tap_text": self._tap_text,
            "assert_pixel": self._assert_pixel,
        }
        

    def execute(self, action: Action) -> StepResult:
        handler = self._handlers.get(action.type)
        if handler is None:
            return StepResult(action.name, action.type, "fail",
                              detail=f"no handler for {action.type}")
        start = time.time()
        started_at = _dt.datetime.now().isoformat(timespec="seconds")
        try:
            result = handler(action)
        except Exception as exc:  # noqa: BLE001 - we surface everything
            result = StepResult(action.name, action.type, "fail",
                                detail=f"{type(exc).__name__}: {exc}")
        result.started_at = started_at
        result.duration_s = round(time.time() - start, 3)
        self.log.info("%-30s %-7s %s %s", action.name, result.status.upper(),
                      f"{result.duration_s:.2f}s", result.detail)
        if self.delay:
            time.sleep(self.delay)
        return result
    def _monkey(self, a: Action) -> StepResult:
        from .monkey import Monkey, MonkeyConfig
        duration = float(a.get("duration_s", 120))
        bursts = int(a.get("inputs_per_burst", 120))
        stuck = int(a.get("identical_bursts_before_stuck", 8))
        mcfg = MonkeyConfig(
            duration_s=duration,
            inputs_per_burst=bursts,
            tap_probability=float(a.get("tap_probability", 0.40)),
            swipe_probability=float(a.get("swipe_probability", 0.60)),
            identical_bursts_before_stuck=stuck,
        )
        monkey = Monkey(self.cfg, mcfg, self.device, self.run_dir, self.log)
        report = monkey.run()
        step = monkey.to_step_result()
        # Attach per-burst detail so results.json is self-explanatory.
        step.detail += (f"; screenshots={len(report.screenshots)}; "
                        f"stuck={report.stuck_detected}")
        return step

    # -- helpers ---------------------------------------------------------
    def _pixels(self, point) -> tuple[int, int]:
        return self.cfg.to_pixels(point, self.device.screen_size())

    def _shot(self, name: str) -> Path:
        path = self.run_dir / name
        self.device.screenshot(path)
        return path

    # -- handlers --------------------------------------------------------
    def _wait(self, a: Action) -> StepResult:
        secs = float(a.get("seconds", 1.0))
        remaining = secs
        while remaining > 0:
            interval = min(5.0, remaining)
            time.sleep(interval)
            remaining = round(remaining - interval, 6)
            if remaining > 0:
                self.log.info(
                    "%s: %.0f seconds remaining", a.name, remaining)
        return StepResult(a.name, a.type, "ok", detail=f"slept {secs}s")

    def _screenshot(self, a: Action) -> StepResult:
        fname = a.get("file") or f"{a.name.replace(' ', '_')}.png"
        path = self._shot(fname)
        return StepResult(a.name, a.type, "ok", artifact=str(path))

    def _tap(self, a: Action) -> StepResult:
        pt = a.get("point")
        if not pt:
            raise ActionError("tap requires 'point'")
        x, y = self._pixels(pt)
        self.device.tap(self.cfg.package, x, y)
        return StepResult(a.name, a.type, "ok", detail=f"tap ({x},{y})")

    def _swipe(self, a: Action) -> StepResult:
        start, end = a.get("start"), a.get("end")
        if not start or not end:
            raise ActionError("swipe requires 'start' and 'end'")
        x1, y1 = self._pixels(start)
        x2, y2 = self._pixels(end)
        dur = int(a.get("duration_ms", 300))
        self.device.swipe(self.cfg.package, x1, y1, x2, y2, dur)
        return StepResult(a.name, a.type, "ok",
                          detail=f"swipe ({x1},{y1})->({x2},{y2}) {dur}ms")

    def _back(self, a: Action) -> StepResult:
        self.device.back()
        return StepResult(a.name, a.type, "ok")

    def _assert_process(self, a: Action) -> StepResult:
        timeout = float(a.get("timeout_s", 0))
        if timeout:
            ok = wait_for_process(self.device, self.cfg.package, timeout)
        else:
            ok = assert_process_alive(self.device, self.cfg.package)
        return StepResult(a.name, a.type, "ok" if ok else "fail",
                          detail="process alive" if ok else "process missing")

    def _assert_no_crash(self, a: Action) -> StepResult:
        from .logcat import scan_for_crash
        log = self.run_dir / f"logcat_{int(time.time())}.txt"
        self.device.logcat_dump(log)
        hits = scan_for_crash(log, self.cfg.package)
        return StepResult(a.name, a.type, "fail" if hits else "ok",
                          detail="; ".join(hits[:3]) if hits else "no crash pattern",
                          artifact=str(log))

    def _dump_ui(self, a: Action) -> StepResult:
        fname = a.get("file") or "ui_hierarchy.xml"
        path = self.device.dump_ui(self.run_dir / fname)
        return StepResult(a.name, a.type, "ok", artifact=str(path))

    def _assert_screen(self, a: Action) -> StepResult:
        before_file, after_file = a.get("before_file"), a.get("after_file")
        if before_file or after_file:
            if not before_file or not after_file:
                raise ActionError(
                    "assert_screen requires both 'before_file' and 'after_file'")
            before = self.run_dir / before_file
            after = self.run_dir / after_file
            if not before.is_file() or not after.is_file():
                raise ActionError(
                    f"assert_screen image not found: {before} or {after}")
        else:
            before = self._shot(f"pre_{a.name.replace(' ', '_')}.png")
            time.sleep(float(a.get("settle_s", 0.5)))
            after = self._shot(f"post_{a.name.replace(' ', '_')}.png")
        ratio = vision.pixel_diff_ratio(before, after)
        min_ratio = a.get("min_diff_ratio")
        if min_ratio is not None:
            min_ratio = float(min_ratio)
            ok = ratio >= min_ratio
            return StepResult(
                a.name, a.type, "ok" if ok else "fail",
                detail=f"diff_ratio={ratio:.4f} (minimum {min_ratio})",
            )
        max_ratio = float(a.get("max_diff_ratio", 0.01))
        ok = ratio <= max_ratio
        return StepResult(a.name, a.type, "ok" if ok else "fail",
                          detail=f"diff_ratio={ratio:.4f} (limit {max_ratio})")

    def _wait_for_template(self, a: Action) -> StepResult:
        template = Path(a.get("template"))
        if not template.is_absolute():
            template = self.cfg.artifact_path.parent / template
        if not template.exists():
            raise ActionError(f"template not found: {template}")
        timeout = float(a.get("timeout_s", 10))
        poll = float(a.get("poll_s", 0.5))
        threshold = float(a.get("threshold", 0.85))
        deadline = time.time() + timeout
        while time.time() < deadline:
            shot = self._shot("_wait_for_template.png")
            hit = vision.find_template(shot, template, threshold)
            if hit:
                x, y, w, h, score = hit
                return StepResult(a.name, a.type, "ok",
                                  detail=f"found at ({x},{y}) score={score:.3f}")
            time.sleep(poll)
        return StepResult(a.name, a.type, "fail",
                          detail=f"template not found within {timeout}s")

    def _wait_for_text(self, a: Action) -> StepResult:
        text = a.get("text")
        if not text:
            raise ActionError("wait_for_text requires 'text'")
        timeout = float(a.get("timeout_s", 10))
        poll = float(a.get("poll_s", 0.5))
        deadline = time.time() + timeout
        while time.time() < deadline:
            xml = self.run_dir / "_wait_for_text.xml"
            self.device.dump_ui(xml)
            if ui.find_by_text(xml, text, exact=bool(a.get("exact", False))):
                return StepResult(a.name, a.type, "ok", detail=f"found {text!r}")
            time.sleep(poll)
        return StepResult(a.name, a.type, "fail",
                          detail=f"text {text!r} not found in {timeout}s")

    def _tap_text(self, a: Action) -> StepResult:
        text = a.get("text")
        if not text:
            raise ActionError("tap_text requires 'text'")
        xml = self.run_dir / "_tap_text.xml"
        self.device.dump_ui(xml)
        node = ui.find_by_text(xml, text, exact=bool(a.get("exact", False)))
        if not node:
            return StepResult(a.name, a.type, "fail",
                              detail=f"text {text!r} not on screen")
        x, y = ui.center_of(node["bounds"])
        self.device.tap(self.cfg.package, x, y)
        return StepResult(a.name, a.type, "ok", detail=f"tapped {text!r} at ({x},{y})")

    def _assert_pixel(self, a: Action) -> StepResult:
        rect = a.get("rect")  # [x, y, w, h] in pixels
        if not rect or len(rect) != 4:
            raise ActionError("assert_pixel requires rect=[x,y,w,h]")
        expected = a.get("expected_bgr")
        tol = float(a.get("tol", 20))
        shot = self._shot(f"_{a.name.replace(' ', '_')}.png")
        mean = vision.region_mean(shot, tuple(rect))
        if expected is None:
            return StepResult(a.name, a.type, "ok",
                              detail=f"mean={mean}", artifact=str(shot))
        ok = all(abs(m - e) <= tol for m, e in zip(mean, expected))
        return StepResult(a.name, a.type, "ok" if ok else "fail",
                          detail=f"mean={mean} expected={tuple(expected)}")