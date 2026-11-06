"""Cheap, non-flaky assertions."""
from __future__ import annotations
import time
from .device import Device


def assert_process_alive(device: Device, package: str) -> bool:
    return device.pid_of(package) is not None


def wait_for_process(device: Device, package: str, timeout_s: float,
                     poll_s: float = 0.5) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if assert_process_alive(device, package):
            return True
        time.sleep(poll_s)
    return False