"""Capture unlabeled gameplay frames for later object-detection training."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


DEFAULT_MAX_DATASET_FRAMES = 600


class SceneDatasetCapture:
    def __init__(
        self,
        run_dir: Path,
        max_frames: int = DEFAULT_MAX_DATASET_FRAMES,
    ):
        if max_frames < 1:
            raise ValueError("max_frames must be at least 1")
        self.root = run_dir / "scene_dataset"
        self.images_dir = self.root / "images"
        self.manifest_path = self.root / "manifest.jsonl"
        self.max_frames = max_frames
        self.frames_captured = 0

    @property
    def full(self) -> bool:
        return self.frames_captured >= self.max_frames

    def capture(
        self,
        screenshot: Callable[[Path], Path],
        timestamp: float,
    ) -> Path:
        if self.full:
            raise RuntimeError(
                f"Scene dataset reached its {self.max_frames}-frame limit"
            )

        self.images_dir.mkdir(parents=True, exist_ok=True)
        frame_name = f"frame_{self.frames_captured + 1:06d}.png"
        image_path = self.images_dir / frame_name
        screenshot(image_path)
        if not image_path.is_file():
            raise FileNotFoundError(
                f"Screenshot was not created: {image_path}"
            )

        entry = {
            "image": f"images/{frame_name}",
            "timestamp_monotonic": timestamp,
            "label_status": "unlabeled",
        }
        with self.manifest_path.open("a", encoding="utf-8") as manifest:
            manifest.write(json.dumps(entry) + "\n")
        self.frames_captured += 1
        return image_path
