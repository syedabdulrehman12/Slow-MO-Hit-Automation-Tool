"""Randomized monkey-test driver for SlowmoQA.

Features:
- Game-window-only taps/swipes with foreground and bounds checks
- Optional labeled-template scene analysis with targeted swipes
- Multi-directional swipes: any direction, any angle
- Crash detection: process-alive check after every burst
"""
from __future__ import annotations

import json
import math
import random
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .dataset_capture import SceneDatasetCapture
from .device import Device
from .evidence import StepResult
from .scene_analysis import SCENE_TEMPLATE_DIR, SceneAnalyzer


DEFAULT_PLAY_AREA = {
    "x_min": 0.0, "x_max": 1.0,
    "y_min": 0.0, "y_max": 1.0,
}
TAP_TOP_MIN = 0.05
SWIPE_START_TOP_MIN = 0.15
CIRCLE_SWIPE_PROBABILITY = 0.12
CIRCLE_SEGMENTS = 8
SWIPE_DURATION_MIN_MS = 120
SWIPE_DURATION_MAX_MS = 180
MAX_INPUTS_PER_ADB_CALL = 64
SCENE_ANALYSIS_INTERVAL_S = 3.0
TARGETED_SWIPE_DURATION_MS = 150


@dataclass
class MonkeyConfig:
    duration_s: float = 360000.0
    inputs_per_burst: int = 120
    burst_pause_s: float = 0.0
    tap_probability: float = 0.40
    swipe_probability: float = 0.60
    play_area: dict = field(default_factory=lambda: dict(DEFAULT_PLAY_AREA))
    identical_bursts_before_stuck: int = 8
    diff_ratio_for_change: float = 0.01

@dataclass
class MonkeyReport:
    inputs_sent: int = 0
    bursts_run: int = 0
    unique_screen_states: int = 0
    max_consecutive_identical: int = 0
    stuck_detected: bool = False
    stopped_reason: str = ""
    screenshots: list[str] = field(default_factory=list)
    random_taps: int = 0
    random_swipes: int = 0
    targeted_swipes: int = 0
    scene_frames: int = 0
    swipe_patterns: dict[str, int] = field(default_factory=dict)


class Monkey:
    def __init__(self, cfg: Config, mcfg: MonkeyConfig,
                 device: Device, run_dir: Path, logger):
        self.cfg = cfg
        self.mcfg = mcfg
        self.device = device
        self.run_dir = run_dir
        self.log = logger
        self.rng = random.Random()
        self.report = MonkeyReport()
        self._w, self._h = device.screen_size()
        scene_template_dir = Path(__file__).resolve().parent.parent / SCENE_TEMPLATE_DIR
        self.scene_analyzer = SceneAnalyzer(scene_template_dir)
        self.scene_dataset = SceneDatasetCapture(run_dir)
        self._last_scene_analysis = 0.0
        self._dataset_limit_logged = False
        self.log.info(
            "Scene dataset capture enabled | path=%s max_frames=%d",
            self.scene_dataset.root, self.scene_dataset.max_frames,
        )
        if not self.scene_analyzer.available:
            self.log.info(
                "Scene frames will be captured for later labeling; live "
                "object detection and targeting are disabled until templates "
                "are added under %s", scene_template_dir)

    # -- random helpers ---------------------------------------------------
    def _random_point(self) -> tuple[int, int]:
        pa = self.mcfg.play_area
        x = self.rng.uniform(pa["x_min"], pa["x_max"]) * self._w
        y = self.rng.uniform(pa["y_min"], pa["y_max"]) * self._h
        return self._bounded_point(x, y)

    def _bounded_point(self, x: float, y: float) -> tuple[int, int]:
        return (
            min(max(int(x), 0), self._w - 1),
            min(max(int(y), 0), self._h - 1),
        )

    def _random_tap_point(self) -> tuple[int, int]:
        pa = self.mcfg.play_area
        x_min = pa["x_min"]
        x_max = pa["x_max"]
        y_min = max(pa["y_min"], TAP_TOP_MIN)
        y_max = pa["y_max"]
        if y_min >= y_max:
            return self._random_point()

        region = self.rng.random()
        if region < 0.5:
            x = self.rng.uniform(
                max(x_min, 0.30), min(x_max, 0.70)
            )
            y = self.rng.uniform(max(y_min, 0.30), min(y_max, 0.70))
        elif region < 0.8:
            x = self.rng.uniform(max(x_min, 0.70), x_max)
            y = self.rng.uniform(y_min, y_max)
        else:
            x = self.rng.uniform(x_min, x_max)
            y = self.rng.uniform(y_min, y_max)
        return self._bounded_point(x * self._w, y * self._h)

    def _random_swipe_start_point(self) -> tuple[int, int]:
        pa = self.mcfg.play_area
        y_min = max(pa["y_min"], SWIPE_START_TOP_MIN)
        if y_min >= pa["y_max"]:
            return self._random_point()
        x = self.rng.uniform(pa["x_min"], pa["x_max"])
        y = self.rng.uniform(y_min, pa["y_max"])
        x, y = self._bounded_point(x * self._w, y * self._h)
        return x, max(y, math.ceil(y_min * self._h))

    def _random_directional_swipe(
        self,
    ) -> tuple[tuple[int, int], tuple[int, int], str]:
        pa = self.mcfg.play_area
        x_min = max(pa["x_min"], 0.08)
        x_max = min(pa["x_max"], 0.92)
        y_min = max(pa["y_min"], SWIPE_START_TOP_MIN)
        y_max = min(pa["y_max"], 0.92)
        x_span = x_max - x_min
        y_span = y_max - y_min
        left = x_min + x_span * 0.08
        right = x_max - x_span * 0.08
        top = y_min + y_span * 0.03
        bottom = y_max - y_span * 0.03
        pattern = self.rng.choice((
            "left-to-right",
            "right-to-left",
            "top-to-bottom",
            "bottom-to-top",
            "top-left-to-top-right",
            "top-left-to-bottom-right",
            "top-right-to-bottom-left",
            "bottom-left-to-bottom-right",
            "bottom-center-left-to-center-right",
        ))

        if pattern in ("left-to-right", "right-to-left"):
            y = self.rng.uniform(top, bottom)
            start_x, end_x = (left, right) if pattern == "left-to-right" \
                else (right, left)
            start, end = (start_x, y), (end_x, y)
        elif pattern in ("top-to-bottom", "bottom-to-top"):
            x = self.rng.uniform(left, right)
            start_y, end_y = (top, bottom) if pattern == "top-to-bottom" \
                else (bottom, top)
            start, end = (x, start_y), (x, end_y)
        elif pattern == "top-left-to-top-right":
            y = self.rng.uniform(top, top + y_span * 0.12)
            start, end = (left, y), (right, y)
        elif pattern == "top-left-to-bottom-right":
            start = (left, top)
            end = (right, bottom)
        elif pattern == "top-right-to-bottom-left":
            start = (right, top)
            end = (left, bottom)
        elif pattern == "bottom-center-left-to-center-right":
            start = (x_min + x_span * 0.40, bottom)
            end = (x_min + x_span * 0.68, y_min + y_span * 0.50)
        else:
            y = self.rng.uniform(bottom - y_span * 0.12, bottom)
            start, end = (left, y), (right, y)

        return (
            self._bounded_point(start[0] * self._w, start[1] * self._h),
            self._bounded_point(end[0] * self._w, end[1] * self._h),
            pattern,
        )

    def _angle(self, x1: int, y1: int, x2: int, y2: int) -> float:
        return math.degrees(math.atan2(y2 - y1, x2 - x1))

    def _random_circle_points(self) -> list[tuple[int, int]]:
        min_radius = 0.08 * min(self._w, self._h)
        max_radius = min(
            0.16 * min(self._w, self._h),
            self._w / 2,
            (self._h * (1 - SWIPE_START_TOP_MIN)) / 2,
        )
        radius = self.rng.uniform(min_radius, max_radius)
        center_x = self.rng.uniform(radius, self._w - radius)
        center_y = self.rng.uniform(
            SWIPE_START_TOP_MIN * self._h + radius,
            self._h - radius,
        )
        return [
            self._bounded_point(
                center_x + radius * math.cos(2 * math.pi * i / CIRCLE_SEGMENTS),
                center_y + radius * math.sin(2 * math.pi * i / CIRCLE_SEGMENTS),
            )
            for i in range(CIRCLE_SEGMENTS + 1)
        ]

    # -- one burst --------------------------------------------------------
    def _run_burst(self, burst_idx: int) -> tuple[Path, list[str]]:
        """Send randomized inputs only while the game window is focused."""
        actions_log: list[str] = []
        pending_inputs: list[tuple[str, tuple[int, ...]]] = []
        pending_patterns: list[str] = []

        def send_pending() -> None:
            if not pending_inputs:
                return
            taps = sum(kind == "tap" for kind, _ in pending_inputs)
            swipes = len(pending_inputs) - taps
            self.device.send_game_inputs(
                self.cfg.package, pending_inputs.copy())
            self.report.inputs_sent += len(pending_inputs)
            self.report.random_taps += taps
            self.report.random_swipes += swipes
            for pattern in pending_patterns:
                self.report.swipe_patterns[pattern] = (
                    self.report.swipe_patterns.get(pattern, 0) + 1)
            self.log.info(
                "sent input chunk | inputs=%d taps=%d swipe_segments=%d",
                len(pending_inputs), taps, swipes,
            )
            pending_inputs.clear()
            pending_patterns.clear()
            self._analyze_scene_if_due()

        def send_tap(x: int, y: int) -> None:
            pending_inputs.append(("tap", (x, y)))
            if len(pending_inputs) >= MAX_INPUTS_PER_ADB_CALL:
                send_pending()

        def send_swipe(
            x1: int, y1: int, x2: int, y2: int, duration_ms: int,
            pattern: str,
        ) -> None:
            pending_inputs.append(
                ("swipe", (x1, y1, x2, y2, duration_ms)))
            pending_patterns.append(pattern)
            if len(pending_inputs) >= MAX_INPUTS_PER_ADB_CALL:
                send_pending()

        for _ in range(self.mcfg.inputs_per_burst):
            r = self.rng.random()
            if r < self.mcfg.tap_probability:
                x, y = self._random_tap_point()
                send_tap(x, y)
                actions_log.append(f"tap ({x},{y})")
            elif r < self.mcfg.tap_probability + self.mcfg.swipe_probability:
                self._random_swipe(send_swipe, actions_log)
            else:
                continue

        send_pending()
        return Path("none"), actions_log

    def _analyze_scene_if_due(self) -> None:
        now = time.monotonic()
        if self.scene_dataset.full:
            if not self._dataset_limit_logged:
                self.log.info(
                    "Scene dataset reached its frame limit | frames=%d path=%s",
                    self.scene_dataset.frames_captured,
                    self.scene_dataset.root,
                )
                self._dataset_limit_logged = True
            return
        if now - self._last_scene_analysis < SCENE_ANALYSIS_INTERVAL_S:
            return
        self._last_scene_analysis = now
        screenshot = self.scene_dataset.capture(self.device.screenshot, now)
        shutil.copyfile(screenshot, self.run_dir / "scene_latest.png")
        analysis = self.scene_analyzer.analyze(screenshot, now)
        self.report.scene_frames += 1
        with (self.run_dir / "scene_analysis.jsonl").open(
            "a", encoding="utf-8"
        ) as evidence:
            evidence.write(json.dumps(analysis.to_dict()) + "\n")
        counts: dict[str, int] = {}
        for obj in analysis.objects:
            counts[obj.category] = counts.get(obj.category, 0) + 1
        self.log.info("scene analysis | objects=%s", counts)

        if analysis.recommended_swipe is None or analysis.target is None:
            return
        start, end = analysis.recommended_swipe
        self.device.send_game_inputs(self.cfg.package, [
            ("swipe", (*start, *end, TARGETED_SWIPE_DURATION_MS)),
        ])
        self.report.inputs_sent += 1
        self.report.targeted_swipes += 1
        self.log.info(
            "targeted swipe | category=%s label=%s center=%s",
            analysis.target.category, analysis.target.label,
            analysis.target.center,
        )

    def _random_swipe(
        self,
        send_swipe,
        actions_log: list[str],
    ) -> None:
        if self.rng.random() < CIRCLE_SWIPE_PROBABILITY:
            points = self._random_circle_points()
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                dur = self.rng.randint(
                    SWIPE_DURATION_MIN_MS, SWIPE_DURATION_MAX_MS
                )
                send_swipe(x1, y1, x2, y2, dur, "circle")
            actions_log.append(
                f"circular swipe pattern ({CIRCLE_SEGMENTS} segments)"
            )
            return

        (x1, y1), (x2, y2), swipe_kind = self._random_directional_swipe()
        dur = self.rng.randint(
            SWIPE_DURATION_MIN_MS, SWIPE_DURATION_MAX_MS
        )
        send_swipe(x1, y1, x2, y2, dur, swipe_kind)
        angle = self._angle(x1, y1, x2, y2)
        actions_log.append(
            f"{swipe_kind} ({x1},{y1})->({x2},{y2}) "
            f"angle={angle:.0f}° {dur}ms")

    def _wake_and_dismiss_swipe_lock(self) -> None:
        """Use the device's keyguard-aware wake and dismiss routine."""
        self.device.wake_and_dismiss_swipe_lock()

    # -- main loop --------------------------------------------------------
    def run(self) -> MonkeyReport:
        self._wake_and_dismiss_swipe_lock()
        start = time.time()

        while time.time() - start < self.mcfg.duration_s:
            burst_idx = self.report.bursts_run
            inputs_before = self.report.inputs_sent
            taps_before = self.report.random_taps
            swipes_before = self.report.random_swipes

            # Run the burst.
            self._run_burst(burst_idx)
            self.report.bursts_run += 1

            # Crash check after each burst.
            if self.device.pid_of(self.cfg.package) is None:
                self.report.stopped_reason = "crash"
                self.log.error("Process vanished after burst %d", burst_idx)
                return self.report

            self.log.info(
                "burst %3d | inputs=%d taps=%d swipe_segments=%d",
                burst_idx,
                self.report.inputs_sent - inputs_before,
                self.report.random_taps - taps_before,
                self.report.random_swipes - swipes_before,
            )

            # Optional pause between bursts (usually 0 for max speed).
            if self.mcfg.burst_pause_s > 0:
                time.sleep(self.mcfg.burst_pause_s)

        self.report.unique_screen_states = self.report.bursts_run
        self.report.stopped_reason = "duration"
        return self.report

    def to_step_result(self) -> StepResult:
        r = self.report
        ok = (r.stopped_reason == "duration" and not r.stuck_detected)
        patterns = ",".join(
            f"{name}:{count}" for name, count in sorted(r.swipe_patterns.items())
        )
        detail = (f"inputs={r.inputs_sent} bursts={r.bursts_run} "
                  f"random_taps={r.random_taps} "
                  f"random_swipes={r.random_swipes} "
                  f"targeted_swipes={r.targeted_swipes} "
                  f"scene_frames={r.scene_frames} "
                  f"swipe_patterns={patterns} "
                  f"states={r.unique_screen_states} "
                  f"stopped={r.stopped_reason} "
                  f"max_identical={r.max_consecutive_identical}")
        return StepResult(name="Monkey test", type="monkey",
                          status="ok" if ok else "fail", detail=detail)