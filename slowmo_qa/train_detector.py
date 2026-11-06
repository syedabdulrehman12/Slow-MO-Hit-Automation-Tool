"""Prepare labeled gameplay screenshots and train a YOLO detector."""
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

from .label_scene_dataset import CLASS_NAMES, SUPPORTED_EXTENSIONS


DEFAULT_EPOCHS = 100
DEFAULT_IMAGE_SIZE = 640
DEFAULT_VALIDATION_FRACTION = 0.2
DEFAULT_WEIGHTS = "yolo11n.pt"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "game_detector.pt"


def prepare_yolo_dataset(
    images_dir: Path,
    labels_dir: Path,
    output_dir: Path,
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
    seed: int = 42,
) -> Path:
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between 0 and 1")
    if not images_dir.is_dir():
        raise NotADirectoryError(f"Image directory not found: {images_dir}")
    if not labels_dir.is_dir():
        raise NotADirectoryError(f"Labels directory not found: {labels_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Training output directory is not empty: {output_dir}. "
            "Choose a new --output-dir to avoid mixing datasets."
        )

    labeled_images = sorted(
        image for image in images_dir.iterdir()
        if image.is_file()
        and image.suffix.lower() in SUPPORTED_EXTENSIONS
        and (labels_dir / f"{image.stem}.txt").is_file()
    )
    if len(labeled_images) < 2:
        raise ValueError(
            "Label at least two images (including empty label files for "
            "reviewed frames with no objects) before training"
        )
    represented_classes: set[int] = set()
    for image in labeled_images:
        label_path = labels_dir / f"{image.stem}.txt"
        for line_number, line in enumerate(
            label_path.read_text(encoding="utf-8").splitlines(), start=1,
        ):
            fields = line.split()
            if len(fields) != 5:
                raise ValueError(
                    f"Invalid YOLO label at {label_path}:{line_number}"
                )
            try:
                class_id = int(fields[0])
                coordinates = [float(value) for value in fields[1:]]
            except ValueError as exc:
                raise ValueError(
                    f"Invalid YOLO label at {label_path}:{line_number}"
                ) from exc
            if class_id < 0 or class_id >= len(CLASS_NAMES):
                raise ValueError(
                    f"Unknown class id at {label_path}:{line_number}"
                )
            center_x, center_y, box_width, box_height = coordinates
            if (
                not all(0 <= value <= 1 for value in coordinates)
                or box_width == 0
                or box_height == 0
                or center_x - box_width / 2 < 0
                or center_x + box_width / 2 > 1
                or center_y - box_height / 2 < 0
                or center_y + box_height / 2 > 1
            ):
                raise ValueError(
                    f"Out-of-bounds YOLO box at {label_path}:{line_number}"
                )
            represented_classes.add(class_id)
    missing_classes = [
        name for class_id, name in enumerate(CLASS_NAMES)
        if class_id not in represented_classes
    ]
    if missing_classes:
        raise ValueError(
            "Add labeled examples for every class before training; missing: "
            + ", ".join(missing_classes)
        )

    shuffled = list(labeled_images)
    random.Random(seed).shuffle(shuffled)
    validation_count = max(
        1, min(len(shuffled) - 1, round(len(shuffled) * validation_fraction))
    )
    validation_images = set(shuffled[:validation_count])
    for split in ("train", "val"):
        (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    for image in labeled_images:
        split = "val" if image in validation_images else "train"
        shutil.copy2(image, output_dir / "images" / split / image.name)
        shutil.copy2(
            labels_dir / f"{image.stem}.txt",
            output_dir / "labels" / split / f"{image.stem}.txt",
        )

    config = {
        "path": str(output_dir.resolve()),
        "train": "images/train",
        "val": "images/val",
        "names": {index: name for index, name in enumerate(CLASS_NAMES)},
    }
    config_path = output_dir / "dataset.yaml"
    yaml_lines = [
        f"path: {json.dumps(config['path'])}",
        f"train: {config['train']}",
        f"val: {config['val']}",
        "names:",
        *(f"  {index}: {name}" for index, name in config["names"].items()),
    ]
    config_path.write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    return config_path


def train_detector(
    dataset_yaml: Path,
    weights: str = DEFAULT_WEIGHTS,
    epochs: int = DEFAULT_EPOCHS,
    image_size: int = DEFAULT_IMAGE_SIZE,
    model_path: Path = DEFAULT_MODEL_PATH,
) -> Path:
    if epochs < 1 or image_size < 1:
        raise ValueError("epochs and image_size must be positive")
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "YOLO training requires ultralytics; install requirements.txt first"
        ) from exc

    model = YOLO(weights)
    result = model.train(
        data=str(dataset_yaml),
        epochs=epochs,
        imgsz=image_size,
        project=str(dataset_yaml.parent / "runs"),
        name="slowmoqa",
        exist_ok=True,
    )
    best_weights = Path(result.save_dir) / "weights" / "best.pt"
    if not best_weights.is_file():
        raise FileNotFoundError(
            f"YOLO training did not produce best.pt at {best_weights}"
        )
    model_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best_weights, model_path)
    return model_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train a YOLO detector from labeled game screenshots."
    )
    parser.add_argument("images_dir", type=Path)
    parser.add_argument("labels_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--weights", default=DEFAULT_WEIGHTS)
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--image-size", type=int, default=DEFAULT_IMAGE_SIZE)
    args = parser.parse_args()
    output_dir = args.output_dir or images_dir_default_output(args.images_dir)
    dataset_yaml = prepare_yolo_dataset(
        args.images_dir, args.labels_dir, output_dir,
    )
    model_path = train_detector(
        dataset_yaml,
        weights=args.weights,
        epochs=args.epochs,
        image_size=args.image_size,
    )
    print(f"Trained model saved to: {model_path}")


def images_dir_default_output(images_dir: Path) -> Path:
    return images_dir.parent / "yolo_training"


if __name__ == "__main__":
    main()
