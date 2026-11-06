"""Read the uiautomator XML and query by text/content-desc/resource-id."""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def parse(xml_path: Path) -> ET.ElementTree:
    return ET.parse(str(xml_path))


def find_by_text(xml_path: Path, text: str, exact: bool = False) -> dict | None:
    tree = parse(xml_path)
    for node in tree.iter("node"):
        val = node.get("text", "")
        if (val == text) if exact else (text in val):
            return dict(node.attrib)
    return None


def find_by_desc(xml_path: Path, desc: str) -> dict | None:
    for node in parse(xml_path).iter("node"):
        if node.get("content-desc", "") == desc:
            return dict(node.attrib)
    return None


BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def center_of(bounds: str) -> tuple[int, int]:
    m = BOUNDS_RE.match(bounds)
    if not m:
        raise ValueError(f"Bad bounds {bounds!r}")
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2