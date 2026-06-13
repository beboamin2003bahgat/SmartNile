#!/usr/bin/env python3
"""
deployment/validate_rpi.py
==========================
Pre-flight validation script for Raspberry Pi 5 deployment.

Run this BEFORE the first real mission to confirm every hardware
interface and dependency is correctly configured.

Usage:
    cd backend
    python deployment/validate_rpi.py

Exit codes:
    0 — all checks passed (or only warnings)
    1 — one or more critical failures detected
"""

import importlib
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

# ── colour output ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m";  RED   = "\033[91m"
YELLOW = "\033[93m";  RESET = "\033[0m";  BOLD = "\033[1m"

def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg):  print(f"  {RED}✗{RESET}  {RED}{msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}!{RESET}  {YELLOW}{msg}{RESET}")
def head(msg):  print(f"\n{BOLD}{msg}{RESET}")

failures = 0

def check(condition, ok_msg, fail_msg, critical=True):
    global failures
    if condition:
        ok(ok_msg)
    else:
        if critical:
            fail(fail_msg)
            failures += 1
        else:
            warn(fail_msg)


# ── 1. Platform ───────────────────────────────────────────────────────────────
head("1 / 9  Platform")
check(
    sys.version_info >= (3, 10),
    f"Python {sys.version_info.major}.{sys.version_info.minor} ✓",
    f"Python 3.10+ required, found {sys.version_info.major}.{sys.version_info.minor}",
)

arch = platform.machine()
check(
    arch in ("aarch64", "armv7l", "armv8", "x86_64"),
    f"Architecture: {arch}",
    f"Unexpected architecture: {arch}",
    critical=False,
)

# Check if running on RPi
is_rpi = False
try:
    model = Path("/proc/device-tree/model").read_text()
    is_rpi = "Raspberry Pi" in model
    ok(f"Board: {model.strip()[:60]}")
except Exception:
    warn("Not running on Raspberry Pi — hardware checks will be skipped")


# ── 2. Python packages ────────────────────────────────────────────────────────
head("2 / 9  Python packages")

REQUIRED = {
    "firebase_admin": ("firebase-admin",    True),
    "serial":         ("pyserial",          True),
    "cv2":            ("opencv-python",     True),
    "numpy":          ("numpy",             True),
}
OPTIONAL = {
    "tflite_runtime": ("tflite-runtime",    False),
    "ultralytics":    ("ultralytics",       False),
    "psutil":         ("psutil",            False),
    "picamera2":      ("picamera2",         False),
    "google.generativeai": ("google-generativeai", False),
    "openai":         ("openai",            False),
}

for mod, (pkg, crit) in REQUIRED.items():
    try:
        importlib.import_module(mod)
        ok(f"{pkg}")
    except ImportError:
        if crit:
            fail(f"{pkg} not installed — run: pip install {pkg} --break-system-packages")
            failures += 1
        else:
            warn(f"{pkg} not installed (optional)")

for mod, (pkg, _) in OPTIONAL.items():
    try:
        importlib.import_module(mod)
        ok(f"{pkg} (optional)")
    except ImportError:
        warn(f"{pkg} not installed (optional — install if needed)")


# ── 3. Serial ports ───────────────────────────────────────────────────────────
head("3 / 9  Serial ports")

arduino_port = os.environ.get("ARDUINO_PORT", "/dev/ttyUSB0")
gps_port     = os.environ.get("GPS_PORT",     "/dev/ttyAMA0")

check(
    Path(arduino_port).exists(),
    f"Arduino port {arduino_port} found",
    f"Arduino port {arduino_port} not found — connect Arduino Nano via USB",
    critical=False,
)
check(
    Path(gps_port).exists(),
    f"GPS port {gps_port} found",
    f"GPS port {gps_port} not found — check UART enabled in raspi-config",
    critical=False,
)


# ── 4. 1-Wire (DS18B20) ───────────────────────────────────────────────────────
head("4 / 9  1-Wire interface (DS18B20)")

w1_base = os.environ.get("DS18B20_BASE_PATH", "/sys/bus/w1/devices")
w1_devs = list(Path(w1_base).glob("28-*")) if Path(w1_base).exists() else []

check(
    Path(w1_base).exists(),
    f"1-Wire base path exists: {w1_base}",
    "1-Wire base path not found — add 'dtoverlay=w1-gpio' to /boot/firmware/config.txt and reboot",
    critical=False,
)
check(
    len(w1_devs) > 0,
    f"DS18B20 sensor detected: {w1_devs[0].name if w1_devs else ''}",
    "No DS18B20 device found — check wiring (GPIO 4, 4.7kΩ pull-up to 3.3V)",
    critical=False,
)


# ── 5. Camera ─────────────────────────────────────────────────────────────────
head("5 / 9  Camera")

try:
    import cv2  # type: ignore  # noqa
    cap = cv2.VideoCapture(int(os.environ.get("CAMERA_INDEX", 0)))
    opened = cap.isOpened()
    cap.release()
    check(opened, "Camera opened successfully via OpenCV", "Camera not found — check cable and index", critical=False)
except Exception as e:
    warn(f"Camera check skipped: {e}")


# ── 6. Firebase credentials ───────────────────────────────────────────────────
head("6 / 9  Firebase credentials")

creds_path = os.environ.get(
    "FIREBASE_CREDENTIALS_PATH",
    str(Path(__file__).parent.parent / "config" / "firebase_credentials.json")
)
creds_exist = Path(creds_path).exists()
check(
    creds_exist,
    f"Firebase credentials found: {Path(creds_path).name}",
    f"Firebase credentials NOT found at {creds_path}\n"
    "     Download from Firebase Console → Project Settings → Service Accounts",
)
if creds_exist:
    try:
        import json
        data = json.loads(Path(creds_path).read_text())
        check("project_id" in data, f"Credentials contain project_id: {data.get('project_id')}", "Credentials file is missing 'project_id' field")
        check("private_key" in data, "Credentials contain private_key", "Credentials file is missing 'private_key' field")
    except Exception as e:
        fail(f"Could not parse credentials file: {e}")
        failures += 1


# ── 7. .env file ──────────────────────────────────────────────────────────────
head("7 / 9  Environment configuration")

env_path = Path(__file__).parent.parent.parent / ".env"
check(env_path.exists(), f".env file found at {env_path}", f".env file not found at {env_path}")

if env_path.exists():
    env_text = env_path.read_text()
    for var in ["FIREBASE_PROJECT_ID", "MISSION_ID"]:
        has_it = re.search(rf"^{var}\s*=\s*\S+", env_text, re.MULTILINE)
        check(bool(has_it), f"{var} is set", f"{var} is not set in .env", critical=False)
    sim = re.search(r"^SIMULATION_MODE\s*=\s*(\w+)", env_text, re.MULTILINE)
    if sim:
        val = sim.group(1).lower()
        if val == "true":
            warn("SIMULATION_MODE=True — set to False for real hardware")
        else:
            ok("SIMULATION_MODE=False (real hardware mode)")


# ── 8. Disk space ─────────────────────────────────────────────────────────────
head("8 / 9  Disk space")

try:
    import shutil
    total, used, free = shutil.disk_usage("/")
    free_gb = free / (1024 ** 3)
    check(
        free_gb >= 1.0,
        f"Free disk space: {free_gb:.1f} GB",
        f"Low disk space: {free_gb:.1f} GB — at least 1 GB recommended",
        critical=False,
    )
except Exception as e:
    warn(f"Could not check disk space: {e}")


# ── 9. Simulation smoke test ──────────────────────────────────────────────────
head("9 / 9  Backend import smoke test")

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SIMULATION_MODE", "True")

try:
    from config.settings import settings
    ok(f"config.settings loaded (mission={settings.MISSION_ID})")
except Exception as e:
    fail(f"config.settings import failed: {e}")
    failures += 1

for mod_name in [
    "managers.sensor_manager",
    "managers.gps_manager",
    "managers.firebase_manager",
    "managers.alert_manager",
    "managers.report_manager",
    "managers.system_monitor",
]:
    try:
        importlib.import_module(mod_name)
        ok(f"{mod_name}")
    except Exception as e:
        fail(f"{mod_name} import failed: {e}")
        failures += 1


# ── Summary ───────────────────────────────────────────────────────────────────
print()
if failures == 0:
    print(f"{GREEN}{BOLD}✓ All checks passed. Ready for deployment.{RESET}")
    print("  Start the backend: SIMULATION_MODE=False python main.py")
else:
    print(f"{RED}{BOLD}✗ {failures} critical issue(s) found. Fix before deploying.{RESET}")

sys.exit(0 if failures == 0 else 1)
