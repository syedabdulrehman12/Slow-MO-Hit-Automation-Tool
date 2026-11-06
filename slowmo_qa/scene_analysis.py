"""YOLO/template scene detection and short-term object tracking."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2

from .vision import load_bgr


SCENE_CATEGORIES = ("player", "enemies", "projectiles")
SCENE_TEMPLATE_DIR = Path("slowmo_qa/templates/scene")
SCENE_MODEL_PATH = Path(__file__).resolve().parent / "models" / "game_detector.pt"
MATCH_THRESHOLD = 0.88
MAX_MATCHES_PER_TEMPLATE = 12
YOLO_CLASS_CATEGORIES = {
    "player": "player",
    "enemy": "enemies",
    "projectile": "projectiles",
}


@dataclass(frozen=True)
class SceneObject:
    category: str
    label: str
    box: tuple[int, int, int, int]
    center: tuple[int, int]
    score: float
    velocity: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class SceneAnalysis:
    timestamp: float
    frame_size: tuple[int, int]
    objects: tuple[SceneObject, ...]
    target: SceneObject | None
    recommended_swipe: tuple[tuple[int, int], tuple[int, int]] | None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "frame_size": self.frame_size,
            "objects": [asdict(obj) for obj in self.objects],
            "target": asdict(self.target) if self.target else None,
            "recommended_swipe": self.recommended_swipe,
        }


class SceneAnalyzer:
    def __init__(
        self,
        template_dir: Path = SCENE_TEMPLATE_DIR,
        threshold: float = MATCH_THRESHOLD,
        *,
        model_path: Path = SCENE_MODEL_PATH,
    ):
        self.template_dir = template_dir
        self.threshold = threshold
        self.model = None
        self.templates: dict[str, list[tuple[str, object]]] = {
            category: [] for category in SCENE_CATEGORIES
        }
        self._previous: tuple[float, list[SceneObject]] | None = None
        if model_path.is_file():
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError(
                    "A trained YOLO model exists, but ultralytics is not "
                    "installed. Install requirements.txt to enable detection."
                ) from exc
            self.model = YOLO(str(model_path))
        for category in SCENE_CATEGORIES:
            directory = template_dir / category
            if directory.is_dir():
                for path in sorted((*directory.glob("*.png"), *directory.glob("*.jpg"))):
                    self.templates[category].append((path.stem, load_bgr(path)))

    @property
    def available(self) -> bool:
        return self.model is not None or any(self.templates.values())

    def _detect(self, frame) -> list[SceneObject]:
        if self.model is not None:
            return self._detect_yolo(frame)

        detections: list[SceneObject] = []
        height, width = frame.shape[:2]
        for category, templates in self.templates.items():
            for label, template in templates:
                th, tw = template.shape[:2]
                if th > height or tw > width:
                    continue
                scores = cv2.matchTemplate(
                    frame, template, cv2.TM_CCOEFF_NORMED)
                for _ in range(MAX_MATCHES_PER_TEMPLATE):
                    _, score, _, location = cv2.minMaxLoc(scores)
                    if score < self.threshold:
                        break
                    x, y = location
                    detections.append(SceneObject(
                        category=category,
                        label=label,
                        box=(x, y, tw, th),
                        center=(x + tw // 2, y + th // 2),
                        score=float(score),
                    ))
                    x1, y1 = max(0, x - tw // 2), max(0, y - th // 2)
                    x2, y2 = min(width, x + tw + tw // 2), min(
                        height, y + th + th // 2)
                    scores[y1:y2, x1:x2] = -1
        return detections

    def _detect_yolo(self, frame) -> list[SceneObject]:
        results = self.model.predict(source=frame, verbose=False)
        detections: list[SceneObject] = []
        if not results:
            return detections
        for box in results[0].boxes:
            class_id = int(box.cls[0].item())
            class_name = str(self.model.names[class_id])
            category = YOLO_CLASS_CATEGORIES.get(class_name)
            if category is None:
                continue
            x1, y1, x2, y2 = (
                int(round(value)) for value in box.xyxy[0].tolist()
            )
            confidence = float(box.conf[0].item())
            width, height = max(0, x2 - x1), max(0, y2 - y1)
            detections.append(SceneObject(
                category=category,
                label=class_name,
                box=(x1, y1, width, height),
                center=(x1 + width // 2, y1 + height // 2),
                score=confidence,
            ))
        return detections

    def _with_velocities(
        self, detections: list[SceneObject], timestamp: float,
    ) -> list[SceneObject]:
        if self._previous is None:
            self._previous = (timestamp, detections)
            return detections
        previous_time, previous = self._previous
        elapsed = timestamp - previous_time
        if elapsed <= 0:
            self._previous = (timestamp, detections)
            return detections

        updated: list[SceneObject] = []
        used: set[int] = set()
        for current in detections:
            match_index = None
            match_distance = math.inf
            for index, old in enumerate(previous):
                if index in used or (old.category, old.label) != (
                    current.category, current.label
                ):
                    continue
                distance = math.dist(current.center, old.center)
                if distance < match_distance:
                    match_index, match_distance = index, distance
            if match_index is not None:
                used.add(match_index)
                old = previous[match_index]
                velocity = (
                    (current.center[0] - old.center[0]) / elapsed,
                    (current.center[1] - old.center[1]) / elapsed,
                )
                current = SceneObject(
                    category=current.category,
                    label=current.label,
                    box=current.box,
                    center=current.center,
                    score=current.score,
                    velocity=velocity,
                )
            updated.append(current)
        self._previous = (timestamp, updated)
        return updated

    def analyze(self, image_path: Path, timestamp: float) -> SceneAnalysis:
        frame = load_bgr(image_path)
        height, width = frame.shape[:2]
        objects = self._with_velocities(self._detect(frame), timestamp)
        players = [obj for obj in objects if obj.category == "player"]
        targets = [
            obj for obj in objects
            if obj.category in ("projectiles", "enemies")
        ]
        player = max(players, key=lambda obj: obj.score) if players else None
        target = None
        swipe = None
        if player and targets:
            target = min(
                targets,
                key=lambda obj: (
                    0 if obj.category == "projectiles" else 1,
                    math.dist(player.center, obj.center),
                ),
            )
            swipe = (player.center, target.center)
        return SceneAnalysis(
            timestamp=timestamp,
            frame_size=(width, height),
            objects=tuple(objects),
            target=target,
            recommended_swipe=swipe,
        )
