"""Post-run logcat scanning. Conservative: only Fatal/ANR on our package."""
from __future__ import annotations
import re
from pathlib import Path

CRASH_RE = re.compile(
    r"FATAL EXCEPTION|ANR in|Force finishing activity|"
    r"java\.lang\.(RuntimeException|NullPointerException|"
    r"IllegalStateException|OutOfMemoryError)"
)


def scan_for_crash(logcat: Path, package: str) -> list[str]:
    hits: list[str] = []
    if not logcat.exists():
        return hits
    for line in logcat.read_text(encoding="utf-8", errors="replace").splitlines():
        if CRASH_RE.search(line) and package in line:
            hits.append(line.strip())
    return hits