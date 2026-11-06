"""Configuration loading and validation."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

ACTION_TYPES = {
     ..., "monkey",
    "wait", "screenshot", "tap", "swipe", "back",
    "assert_process", "dump_ui", "assert_screen",
    "tap_text", "wait_for_text", "wait_for_template",
    "assert_pixel", "swipe_normalized", "sleep_until",
    "record_logcat_marker", "assert_no_crash",
}


@dataclass
class Action:
    name: str
    type: str
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default=None):
        return self.raw.get(key, default)


@dataclass
class Config:
    package: str
    activity: str
    device_serial: str
    screenshot_after_launch_seconds: float
    action_delay_seconds: float
    screen_size: list[int]
    coordinates_are_normalized: bool
    poco_enabled: bool
    airtest_enabled: bool
    artifact_dir: str
    auto_dismiss_swipe_lock: bool

    @property
    def artifact_path(self) -> Path:
        p = ROOT / self.artifact_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    def to_pixels(self, point: list[float], actual_size: tuple[int, int]) -> tuple[int, int]:
        """Convert configured coordinates to device pixels."""
        if self.coordinates_are_normalized:
            w, h = actual_size
            return int(round(point[0] * w)), int(round(point[1] * h))
        return int(round(point[0])), int(round(point[1]))


def load_config(path: str | Path = ROOT / "config.json") -> Config:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Config(**{k: data[k] for k in Config.__dataclass_fields__})


def load_actions(path: str | Path = ROOT / "actions.json") -> list[Action]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    actions: list[Action] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"actions[{i}] is not an object")
        if "type" not in item:
            raise ValueError(f"actions[{i}] missing 'type'")
        if item["type"] not in ACTION_TYPES:
            raise ValueError(
                f"actions[{i}] unknown type {item['type']!r}. "
                f"Allowed: {sorted(ACTION_TYPES)}"
            )
        actions.append(Action(name=item.get("name", f"action[{i}]"),
                              type=item["type"], raw=item))
    return actions