# SlowmoQA Project Overview

## Purpose

SlowmoQA is a Windows-based starter project for automating quality checks on an Android game. It connects to a test device, runs configured checks, and collects evidence that can help a QA reviewer investigate the result.

This document is a non-technical project handoff. It describes the project's purpose and how to get started, but intentionally omits internal algorithms, detailed test behavior, tuning values, and implementation-level design.

## What the project provides

- A command-line entry point for running automated checks.
- A basic device and application smoke-check workflow.
- Optional image/UI automation and scene-analysis components.
- A small local dashboard for starting and observing a run.
- Per-run logs and evidence to support manual review.

The project is a starter framework, not a finished, game-independent QA product. Test coverage and reliability depend on the target game, device, and project-specific calibration.

## High-level project layout

| Location | Purpose |
|---|---|
| `run_agent.py`, `run_smoke.py` | Command-line launch points |
| `dashboard.py` | Local browser-based control page |
| `config.json`, `actions.json` | Runtime and action configuration |
| `slowmo_qa/` | Application package containing device, test, evidence, and optional analysis components |
| `slowmo_qa/Suites/` | Example test-suite configurations |
| `tests/` | Automated checks for project components |
| `artifacts/` | Generated run results and evidence |
| `requirements.txt` | Python dependency list |

Generated artifacts, sample captures, and local environment files may be present in a working copy. Review them before sharing; they are not required as part of this overview.

## Technology and prerequisites

- Windows 10 or 11
- Python 3.11
- Android SDK Platform Tools (`adb`)
- An Android device or emulator with USB debugging enabled and authorized
- The Android application to be tested installed on the device
- Python packages listed in `requirements.txt`

The project uses ADB for device interaction and includes optional Airtest, PocoUI, OpenCV, and computer-vision support. Optional integrations may require additional target-app setup and calibration.

## Getting started

Open PowerShell in the project folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
adb devices
```

Confirm that the test device appears as `device` (not `unauthorized`) before running a check.

### Run a smoke check

```powershell
python run_smoke.py
```

### Run the configured automated checks

```powershell
python run_agent.py
```

### Open the local dashboard

```powershell
python dashboard.py
```

The dashboard is intended for local use and is available at `http://127.0.0.1:8765` while running.

## Results and evidence

Runs write timestamped output under `artifacts/`. Depending on the run, this can include logs, result summaries, screenshots, device logs, and UI information. Treat captured device output as potentially sensitive and review it before distributing it.

## Current scope and limitations

- A device connection and a successful run do not by themselves prove that every game feature behaves correctly.
- Game-specific expectations and visual/UI checks need to be reviewed and calibrated for the target application.
- Optional detection or UI integrations may not work with every game or device configuration.
- Automated input may affect game state. Use a dedicated test device or account and avoid production accounts, purchases, and real ad interactions.
- Review generated evidence and test outcomes manually before using them to make release decisions.

## Suggested handoff

Before extending or operationalizing the project, the receiving team should:

1. Confirm the target application's test build and device setup.
2. Review and adapt the configuration and test coverage for that application.
3. Validate expected results against observed screenshots and device behavior.
4. Decide how artifacts should be retained, sanitized, and shared.
5. Run the existing project tests when making code changes.

For detailed setup and current project-specific operating instructions, consult `README.md`. This overview is intentionally not a substitute for source-code access or a full technical specification.
