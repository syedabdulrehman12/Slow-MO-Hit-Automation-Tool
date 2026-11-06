"""Agent orchestrator: ordered suites + summary."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

from .config import load_config
from .evidence import new_run_dir, setup_logging
from .runner import run_suite
from .device import AdbError, Device


DEFAULT_ORDER = ["gameplay", "monkey"]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cfg = load_config()
    run_id, run_dir = new_run_dir(cfg.artifact_path)
    log = setup_logging(run_dir)
    log.info("=== SlowmoQA agent run %s ===", run_id)

    suites = argv or DEFAULT_ORDER
    summary = {"run_id": run_id, "suites": [], "started_at": time.time()}

    for suite in suites:
        log.info("---- suite: %s ----", suite)
        rc = run_suite(suite)
        summary["suites"].append({"suite": suite, "exit_code": rc})
        if rc != 0:
            log.warning("Suite %s returned %d; continuing", suite, rc)

    summary["finished_at"] = time.time()
    summary["duration_s"] = round(summary["finished_at"] - summary["started_at"], 2)
    (run_dir / "agent_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    log.info("Agent summary: %s", run_dir / "agent_summary.json")
    return 0 if all(s["exit_code"] == 0 for s in summary["suites"]) else 1