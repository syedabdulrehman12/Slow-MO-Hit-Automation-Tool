# SlowmoQA — Android game QA automation starter

Target package: `com.gdm.slowmo`

This is a starter framework for Windows + ADB + Airtest + PocoUI. The first runner uses ADB for stable device operations and leaves Airtest/Poco probes optional. It does not assume the game's UI layout or claim to verify game-specific outcomes without calibrated assertions.

## Requirements

- Windows 10/11
- Python 3.11
- Android SDK Platform Tools (`adb.exe`) on PATH
- Android phone with USB debugging enabled and authorized
- Slow Motion installed on the device

## Install

Open PowerShell in this folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
adb devices
```

The device status must be `device`, not `unauthorized`.

Verify package installation:

```powershell
adb shell pm path com.gdm.slowmo
```

If no APK path is returned, install the game from Google Play and retry.

## Run smoke test

```powershell
python run_smoke.py
```

The runner checks the device, verifies the package is installed, launches the game, waits, confirms the process exists, captures screenshots, collects logcat and UI hierarchy evidence, and writes `results.json` in a timestamped folder under `artifacts`.

## Run automated game tests

```powershell
python run_agent.py
```

The agent runs the gameplay check followed by the randomized monkey stress test. The gameplay check sends a tap and verifies the before/after screenshots changed; the monkey suite runs for 30 minutes with an even mix of taps and swipes, selecting 9,600 actions per burst (10 times the earlier 960 setting) with no pause between bursts. Swipes include horizontal and vertical motions, both downward diagonals, bottom-center-left to center-right diagonals, top- and bottom-edge horizontal motions, and eight-segment circles. Circle patterns are selected 12% of the time; each swipe lasts 120–180 ms so gestures are less likely to be dropped as imperceptibly short. The runner checks game focus before every batch and stops rather than sending input to another app. Ad detection and ad-specific pausing are not used; random input may interact with whatever is displayed in the game window. Actual throughput depends on the device and is not guaranteed. Use a dedicated QA device and calibrate gameplay first, since random inputs can change progress or activate in-game controls.

## Live dashboard

Start the local web page with one button for the full agent test:

```powershell
python dashboard.py
```

The page opens at `http://127.0.0.1:8765`. Click **Start test** to run the monkey suite using `.venv\Scripts\python.exe -u -c "from slowmo_qa.runner import run_suite; raise SystemExit(run_suite('monkey'))"`. Click **Stop test** to terminate the active run. The test's console output is shown in the page, and run logs and evidence are written under `artifacts`. The dashboard does not capture or display the device screen.

## Airtest probe

```powershell
python airtest_probe.py
```

If Airtest cannot connect, check the device's ADB authorization and install/setup requirements for your Airtest version. The ADB runner is independent of the probe.

## Configure the device

Edit `config.json`:
- `device_serial`: set this to the serial shown by `adb devices` if more than one device is connected.
- `activity`: leave empty to launch through Android's launcher intent. Otherwise provide the activity name expected by `am start`.
- `screen_size`: informational only; actual dimensions are queried from ADB.
- `coordinates_are_normalized`: if `true`, coordinates in `actions.json` are fractions from 0.0 to 1.0; if `false`, they are screen pixels.
- `auto_dismiss_swipe_lock`: wakes the display and dismisses a swipe-only lock screen before launching the game. It does not enter or bypass a PIN, password, pattern, or biometric lock. For unattended tests, use a dedicated QA device or emulator configured without a secure lock. Set this to `false` to disable this preflight if your Android build does not expose lock-screen state through `dumpsys window policy`.

This startup-only lock-screen swipe is separate from gameplay input. All gameplay taps and swipes require the game's window to be focused and remain within its reported window bounds.

## Configure action sequences

Edit `actions.json`. Supported actions:
- `wait`: `seconds`
- `screenshot`: optional `file`
- `tap`: `point: [x, y]`
- `swipe`: `start: [x, y]`, `end: [x, y]`, optional `duration_ms`
- `assert_screen`: optional screenshot diff limits; `before_file` and `after_file` compare existing screenshots.
- `back`
- `assert_process`
- `dump_ui`: optional `file`

Normalized example: `[0.5, 0.8]` taps the middle of the screen, 80% down. **Do not use sample coordinates as gameplay assertions until you have inspected screenshots and mapped the real UI.** Remove or adjust actions that might purchase items, spend currency, delete progress, or trigger ads.

The randomized `monkey` action defaults to 120 action selections per burst; `slowmo_qa/Suites/monkey.json` configures 9,600 selections, with 50% taps and 50% swipes. Taps sample the game window, while swipes are spread across directional patterns plus eight-segment circles. Inputs are sent in ADB batches of at most 64 gestures to reduce per-batch overhead and produce progress logs. The game foreground is verified before each batch, and every tap and swipe endpoint is checked against the focused game's window bounds. Input is refused if Android cannot provide those bounds or the game loses focus before a batch. Run results report tap, swipe-segment, and per-pattern counts; actual throughput depends on the device.

### Live scene analysis and targeted swipes

The monkey runner captures a gameplay frame every three seconds (up to 600 frames per run) into `artifacts/<run-id>/scene_dataset/images/`. These are training samples, **not a trained detector**. YOLO detection stays off until you label screenshots and train a model.

To label and train a game-specific detector:

1. Install dependencies from the project virtual environment:

   ```powershell
   pip install -r requirements.txt
   ```

2. Open the screenshots in the labeling window:

   ```powershell
   python -m slowmo_qa.label_scene_dataset artifacts\<run-id>\scene_dataset\images
   ```

   Drag a box around one object, then press `1` for the player, `2` for an enemy, or `3` for a projectile. Use `U` to undo, `N` or Space to save and move forward, `K` to skip a frame without labeling it, `B` to save and go back, `S` to save, and `Q` to save and quit. Use `N` without any boxes only for a frame you reviewed and confirmed has no objects. Labels are written to `scene_dataset\labels`.

3. Label a varied set of frames, including different enemy appearances and projectile sizes/positions, then train:

   ```powershell
   python -m slowmo_qa.train_detector artifacts\<run-id>\scene_dataset\images artifacts\<run-id>\scene_dataset\labels
   ```

   Training needs at least two labeled images; that is only a technical minimum, not enough to expect reliable detection. The first run downloads the small `yolo11n.pt` starting weights. Training exports its best model to `slowmo_qa\models\game_detector.pt`.

4. Start a new monkey run. When the model file exists, scene analysis uses it to detect the `player`, `enemy`, and `projectile` classes. Review `scene_analysis.jsonl` and the captured screenshots to check missed detections and false positives. Accuracy depends on the quality and variety of your labels; do not rely on detection-driven input until you have validated it on your game.

Without a trained model, the existing OpenCV template detector can still compare screenshots against labeled image templates and track their centers between observations. Alternatively, add tightly cropped, native-resolution example images under:

```text
slowmo_qa/templates/scene/player/
slowmo_qa/templates/scene/enemies/
slowmo_qa/templates/scene/projectiles/
```

Use one clear object per PNG, with descriptive filenames (for example `hero.png`, `slime.png`, `dart.png`). Add templates for different appearances, scales, and animation frames when needed. A targeted swipe is sent only when both a player and an enemy/projectile match; projectiles are prioritized. Each observation, match score, center, and estimated movement vector is appended to `scene_analysis.jsonl` in the run's artifact directory. Without a trained model or templates, the runner captures dataset frames but cannot identify objects. The existing `templates/enemies/enemy1.png` is not assumed to be a valid gameplay-object template. Template matching is visual and needs calibration against real gameplay screenshots; review its detections before relying on automated targeting.

## PocoUI

PocoUI works only when a supported SDK/integration exposes the game's UI tree. For Unity games this may require the appropriate Unity integration; custom-rendered games may expose few or no useful elements. Use Airtest image recognition or ADB coordinate actions when Poco cannot see the control. Do not assume an empty Poco hierarchy means a bug.

## Evidence

Each run produces:
- `run.log`
- `results.json`
- screenshots
- `logcat.txt`
- `final_ui_dump.xml`

Logcat is broad device output and may contain unrelated system messages. Check timestamps and process/package context before attributing a crash to the game. The current crash check only confirms whether the app process remains present; it is not a complete crash classifier.

## Next step: calibrate game-specific tests

1. Run the smoke test.
2. Inspect `01_after_launch.png` and `02_initial_screen.png`.
3. Map the tutorial, main menu, gameplay, pause, retry, and level-complete screens.
4. Add screenshot templates and/or Poco selectors for visible controls.
5. Define expected outcomes for each test case, then run repeated tests and compare screenshots/state.

Do not automate ad clicks or purchases in production accounts. Use a test environment and test ad configuration where available.
