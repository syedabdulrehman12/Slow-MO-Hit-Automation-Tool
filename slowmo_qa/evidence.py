"""Run folder, screenshots, results.json."""
from __future__ import annotations
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class StepResult:
    name: str
    type: str
    status: str                    # "ok" | "fail" | "skip"
    started_at: str = ""
    duration_s: float = 0.0
    detail: str = ""
    artifact: str = ""


@dataclass
class RunResult:
    run_id: str
    package: str
    device_serial: str
    started_at: str
    finished_at: str = ""
    status: str = "running"
    steps: list[StepResult] = field(default_factory=list)
    fatal_error: str = ""

    def add(self, step: StepResult) -> None:
        self.steps.append(step)

    def to_json(self, path: Path) -> Path:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path


def new_run_dir(base: Path) -> tuple[str, Path]:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    path = base / run_id
    path.mkdir(parents=True, exist_ok=True)
    return run_id, path


def setup_logging(run_dir: Path) -> logging.Logger:
    logger = logging.getLogger("slowmoqa")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")

    fh = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger