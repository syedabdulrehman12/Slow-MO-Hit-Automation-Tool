"""Smoke runner (preserved) + suite runner used by run_agent.py."""
from __future__ import annotations
import datetime as _dt
import json
import sys
import time
from pathlib import Path

from .actions import Executor
from .config import load_actions, load_config
from .device import AdbError, Device
from .evidence import RunResult, new_run_dir, setup_logging


def _bootstrap():
    cfg = load_config()
    run_id, run_dir = new_run_dir(cfg.artifact_path)
    log = setup_logging(run_dir)
    return cfg, run_id, run_dir, log


def _prepare_device(cfg, log) -> Device:
    bundled_adb = Path(__file__).resolve().parent.parent / "adb.exe"
    device = Device(
        cfg.device_serial, str(bundled_adb) if bundled_adb.exists() else "adb")
    device.require_online()
    log.info("Device online: %s", cfg.device_serial or "(default)")
    if not device.is_package_installed(cfg.package):
        raise RuntimeError(
            f"Package {cfg.package} not installed. "
            f"Check README's 'Verify package installation' step.")
    if cfg.auto_dismiss_swipe_lock:
        log.info("Waking screen and checking for a swipe-only lock screen...")
        device.wake_and_dismiss_swipe_lock()
    return device


def _run_actions(cfg, device, run_dir, log, actions) -> RunResult:
    run = RunResult(
        run_id=run_dir.name,
        package=cfg.package,
        device_serial=cfg.device_serial or "(default)",
        started_at=_dt.datetime.now().isoformat(timespec="seconds"),
    )
    executor = Executor(cfg, device, run_dir, log)

    log.info("Stopping any previous instance...")
    device.stop(cfg.package)
    log.info("Launching %s ...", cfg.package)
    device.launch(cfg.package, cfg.activity)
    log.info("Waiting %ss for splash / first frame...",
             cfg.screenshot_after_launch_seconds)
    time.sleep(cfg.screenshot_after_launch_seconds)

    for action in actions:
        result = executor.execute(action)
        run.add(result)
        if result.status == "fail":
            log.warning("Stopping suite on failed step %r", action.name)
            break

    return run


def _finish(cfg, device, run_dir, run: RunResult, log) -> int:
    run.finished_at = _dt.datetime.now().isoformat(timespec="seconds")

    # Final evidence sweep (best effort).
    try:
        device.screenshot(run_dir / "final_screen.png")
    except Exception as exc:  # noqa: BLE001
        log.warning("final screenshot failed: %s", exc)
    try:
        device.logcat_dump(run_dir / "logcat.txt")
    except Exception as exc:  # noqa: BLE001
        log.warning("final logcat failed: %s", exc)
    try:
        device.dump_ui(run_dir / "final_ui_dump.xml")
    except Exception as exc:  # noqa: BLE001
        log.warning("final ui dump failed: %s", exc)

    fails = [s for s in run.steps if s.status == "fail"]
    run.status = "failed" if fails or run.fatal_error else "passed"
    run.to_json(run_dir / "results.json")
    log.info("Run %s: %s (%d steps, %d failed)",
             run.run_id, run.status.upper(), len(run.steps), len(fails))
    return 0 if run.status == "passed" else 1


def main() -> int:
    try:
        cfg, run_id, run_dir, log = _bootstrap()
    except Exception as exc:  # noqa: BLE001
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 2

    log.info("=== SlowmoQA smoke run %s ===", run_id)
    try:
        device = _prepare_device(cfg, log)
        actions = load_actions()
    except (AdbError, RuntimeError, FileNotFoundError, ValueError) as exc:
        log.error("Startup failed: %s", exc)
        return 2

    run = _run_actions(cfg, device, run_dir, log, actions)
    return _finish(cfg, device, run_dir, run, log)


# ---- suite runner, used by run_agent.py --------------------------------

def run_suite(suite_name: str) -> int:
    from pathlib import Path
    from .config import load_config, load_actions  # noqa: F401

    suite_path = Path(__file__).resolve().parent / "suites" / f"{suite_name}.json"
    if not suite_path.exists():
        print(f"Unknown suite: {suite_name}", file=sys.stderr)
        print(f"Expected file: {suite_path}", file=sys.stderr)
        return 2
    cfg = load_config()
    run_id, run_dir = new_run_dir(cfg.artifact_path)
    log = setup_logging(run_dir)
    log.info("=== SlowmoQA suite %s / run %s ===", suite_name, run_id)
    try:
        device = _prepare_device(cfg, log)
        actions = load_actions(suite_path)
    except (AdbError, RuntimeError, FileNotFoundError, ValueError) as exc:
        log.error("Startup failed: %s", exc)
        return 2
    run = _run_actions(cfg, device, run_dir, log, actions)
    return _finish(cfg, device, run_dir, run, log)