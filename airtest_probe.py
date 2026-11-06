"""Optional Airtest/Poco connectivity probe. Run after ADB is authorized."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

try:
    from airtest.core.api import connect_device, snapshot, device
    serial = cfg.get("device_serial", "").strip()
    uri = f"Android:///{serial}" if serial else "Android:///"
    connect_device(uri)
    print("Airtest connected:", device().uuid)
    result = snapshot(filename=str(ROOT / "artifacts" / "airtest_probe.png"))
    print("Airtest screenshot:", result)
except Exception as exc:
    print("Airtest probe failed:", repr(exc))
    print("ADB-based runner can still work. Check `adb devices` and Airtest Android setup.")
    raise
