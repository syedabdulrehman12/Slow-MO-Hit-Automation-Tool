"""Screenshot analysis: template matching and region stats.

Template matching uses Airtest's OpenCV-backed helpers. If you prefer
plain OpenCV, swap the import — the interface is the same.
"""
from __future__ import annotations
from pathlib import Path

try:
    import cv2
    import numpy as np
    _HAVE_CV = True
except ImportError:
    _HAVE_CV = False


def load_bgr(path: Path):
    if not _HAVE_CV:
        raise RuntimeError("cv2 not installed; add opencv-python to requirements")
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Could not read image {path}")
    return img


def find_template(screen: Path, template: Path, threshold: float = 0.85):
    """Return (x, y, w, h, score) of best match, or None."""
    hay = load_bgr(screen)
    needle = load_bgr(template)
    if needle.shape[0] > hay.shape[0] or needle.shape[1] > hay.shape[1]:
        return None
    res = cv2.matchTemplate(hay, needle, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < threshold:
        return None
    x, y = max_loc
    h, w = needle.shape[:2]
    return (x, y, w, h, float(max_val))


def region_mean(screen: Path, rect: tuple[int, int, int, int]):
    """Mean BGR of a rect region, for cheap color/state checks."""
    img = load_bgr(screen)
    x, y, w, h = rect
    roi = img[y:y + h, x:x + w]
    if roi.size == 0:
        raise ValueError(f"Empty ROI {rect} on {screen}")
    mean = roi.reshape(-1, 3).mean(axis=0)
    return tuple(float(v) for v in mean)


def pixel_diff_ratio(a: Path, b: Path, tol: int = 12) -> float:
    """Fraction of pixels differing beyond tol (0.0 = identical)."""
    ia, ib = load_bgr(a), load_bgr(b)
    if ia.shape != ib.shape:
        raise ValueError("Screenshots differ in size")
    diff = np.abs(ia.astype(np.int16) - ib.astype(np.int16))
    changed = (diff > tol).any(axis=2)
    return float(changed.mean())