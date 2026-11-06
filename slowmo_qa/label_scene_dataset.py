"""Interactively label captured gameplay screenshots for YOLO training."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2


CLASS_NAMES = ("player", "enemy", "projectile")
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_DISPLAY_SIZE = (1200, 900)


class DatasetLabeler:
    def __init__(self, images_dir: Path):
        if not images_dir.is_dir():
            raise NotADirectoryError(f"Image directory not found: {images_dir}")
        self.images_dir = images_dir
        self.labels_dir = images_dir.parent / "labels"
        self.images = sorted(
            path for path in images_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        if not self.images:
            raise ValueError(f"No images found under {images_dir}")
        self.index = 0
        self.boxes: list[tuple[int, int, int, int, int]] = []
        self.drag_start: tuple[int, int] | None = None
        self.drag_end: tuple[int, int] | None = None
        self.frame = None
        self.scale = 1.0
        self.window = "SlowmoQA dataset labeler"
        self._load_current()

    def _label_path(self) -> Path:
        return self.labels_dir / f"{self.images[self.index].stem}.txt"

    def _load_current(self) -> None:
        self.frame = cv2.imread(str(self.images[self.index]))
        if self.frame is None:
            raise ValueError(f"Could not read image: {self.images[self.index]}")
        height, width = self.frame.shape[:2]
        max_width, max_height = MAX_DISPLAY_SIZE
        self.scale = min(1.0, max_width / width, max_height / height)
        self.boxes = self._read_labels(self._label_path(), width, height)
        self.drag_start = None
        self.drag_end = None

    @staticmethod
    def _read_labels(
        label_path: Path, width: int, height: int,
    ) -> list[tuple[int, int, int, int, int]]:
        if not label_path.is_file():
            return []
        boxes = []
        for line_number, line in enumerate(
            label_path.read_text(encoding="utf-8").splitlines(), start=1,
        ):
            fields = line.split()
            if len(fields) != 5:
                raise ValueError(
                    f"Invalid label at {label_path}:{line_number}"
                )
            class_id = int(fields[0])
            if class_id < 0 or class_id >= len(CLASS_NAMES):
                raise ValueError(
                    f"Unknown class id at {label_path}:{line_number}"
                )
            center_x, center_y, box_width, box_height = map(float, fields[1:])
            x1 = round((center_x - box_width / 2) * width)
            y1 = round((center_y - box_height / 2) * height)
            x2 = round((center_x + box_width / 2) * width)
            y2 = round((center_y + box_height / 2) * height)
            boxes.append((class_id, x1, y1, x2, y2))
        return boxes

    def _to_image_point(self, point: tuple[int, int]) -> tuple[int, int]:
        height, width = self.frame.shape[:2]
        x = min(max(round(point[0] / self.scale), 0), width - 1)
        y = min(max(round(point[1] / self.scale), 0), height - 1)
        return x, y

    def _mouse(self, event, x, y, _flags, _param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drag_start = self._to_image_point((x, y))
            self.drag_end = self.drag_start
        elif event == cv2.EVENT_MOUSEMOVE and self.drag_start is not None:
            self.drag_end = self._to_image_point((x, y))
        elif event == cv2.EVENT_LBUTTONUP and self.drag_start is not None:
            self.drag_end = self._to_image_point((x, y))

    def _save(self) -> None:
        height, width = self.frame.shape[:2]
        self.labels_dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for class_id, x1, y1, x2, y2 in self.boxes:
            left, right = sorted((min(max(x1, 0), width), min(max(x2, 0), width)))
            top, bottom = sorted((min(max(y1, 0), height), min(max(y2, 0), height)))
            if left == right or top == bottom:
                continue
            center_x = (left + right) / (2 * width)
            center_y = (top + bottom) / (2 * height)
            box_width = (right - left) / width
            box_height = (bottom - top) / height
            lines.append(
                f"{class_id} {center_x:.6f} {center_y:.6f} "
                f"{box_width:.6f} {box_height:.6f}"
            )
        self._label_path().write_text(
            "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )

    def _draw(self):
        height, width = self.frame.shape[:2]
        display = cv2.resize(
            self.frame,
            (round(width * self.scale), round(height * self.scale)),
        )
        for class_id, x1, y1, x2, y2 in self.boxes:
            color = ((255, 200, 0), (0, 220, 0), (0, 120, 255))[class_id]
            start = (round(x1 * self.scale), round(y1 * self.scale))
            end = (round(x2 * self.scale), round(y2 * self.scale))
            cv2.rectangle(display, start, end, color, 2)
            cv2.putText(
                display, CLASS_NAMES[class_id], (start[0], max(18, start[1] - 5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
            )
        if self.drag_start is not None and self.drag_end is not None:
            start = (
                round(self.drag_start[0] * self.scale),
                round(self.drag_start[1] * self.scale),
            )
            end = (
                round(self.drag_end[0] * self.scale),
                round(self.drag_end[1] * self.scale),
            )
            cv2.rectangle(display, start, end, (255, 255, 255), 1)

        instructions = (
            f"{self.index + 1}/{len(self.images)}  "
            f"{self.images[self.index].name}  boxes:{len(self.boxes)}"
        )
        cv2.putText(
            display, instructions, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
            0.55, (20, 20, 20), 3,
        )
        cv2.putText(
            display, instructions, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
            0.55, (255, 255, 255), 1,
        )
        controls = (
            "Drag box, then 1 player / 2 enemy / 3 projectile | "
            "U undo | N save+next | K skip | B back | Q quit"
        )
        cv2.putText(
            display, controls, (10, 48), cv2.FONT_HERSHEY_SIMPLEX,
            0.45, (255, 255, 255), 1,
        )
        return display

    def run(self) -> None:
        cv2.namedWindow(self.window, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.window, self._mouse)
        try:
            while True:
                cv2.imshow(self.window, self._draw())
                key = cv2.waitKey(20) & 0xFF
                if key == ord("q"):
                    self._save()
                    break
                if key == ord("u"):
                    if self.boxes:
                        self.boxes.pop()
                elif key == ord("s"):
                    self._save()
                elif key in (ord("n"), 32, ord("b")):
                    self._save()
                    offset = -1 if key == ord("b") else 1
                    next_index = self.index + offset
                    if 0 <= next_index < len(self.images):
                        self.index = next_index
                        self._load_current()
                elif key == ord("k"):
                    next_index = self.index + 1
                    if next_index < len(self.images):
                        self.index = next_index
                        self._load_current()
                elif key in (ord("1"), ord("2"), ord("3")):
                    if self.drag_start is None or self.drag_end is None:
                        continue
                    x1, x2 = sorted((self.drag_start[0], self.drag_end[0]))
                    y1, y2 = sorted((self.drag_start[1], self.drag_end[1]))
                    if x2 > x1 and y2 > y1:
                        self.boxes.append(
                            (key - ord("1"), x1, y1, x2, y2))
                    self.drag_start = None
                    self.drag_end = None
        finally:
            cv2.destroyWindow(self.window)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draw boxes around players, enemies, and projectiles."
    )
    parser.add_argument(
        "images_dir",
        type=Path,
        help="Folder containing captured screenshots",
    )
    args = parser.parse_args()
    DatasetLabeler(args.images_dir).run()


if __name__ == "__main__":
    main()
