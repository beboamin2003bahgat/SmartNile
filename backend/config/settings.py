"""
config/settings.py
==================
Single source of truth for every constant, pin number, threshold, and
environment variable in the Smart Nile backend.

All values are read from the .env file at project root.  Anything not
set in .env falls back to a safe default so the system can still run in
simulation mode on a development machine without any hardware attached.

Usage:
    from config.settings import settings
    print(settings.FIREBASE_PROJECT_ID)
    print(settings.THRESHOLDS["pH"]["critical_low"])
"""

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any

# ── locate .env (project root is one level above backend/) ──────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ROOT_DIR    = _BACKEND_DIR.parent
_ENV_FILE    = _ROOT_DIR / ".env"

def _load_env(path: Path) -> None:
    """Minimal .env parser — no external dependency needed at boot time."""
    if not path.exists():
        logging.warning(f"[Settings] .env not found at {path}. Using defaults.")
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:   # don't override real env vars
                os.environ[key] = value

_load_env(_ENV_FILE)


# ── helpers ──────────────────────────────────────────────────────────────────
def _env(key: str, default: Any = None) -> Any:
    return os.environ.get(key, default)

def _bool(key: str, default: bool = False) -> bool:
    return _env(key, str(default)).lower() in ("1", "true", "yes")

def _int(key: str, default: int = 0) -> int:
    try:
        return int(_env(key, default))
    except (TypeError, ValueError):
        return default

def _float(key: str, default: float = 0.0) -> float:
    try:
        return float(_env(key, default))
    except (TypeError, ValueError):
        return default


# ── main settings class ───────────────────────────────────────────────────────
@dataclass
class Settings:
    # ── System ──────────────────────────────────────────────────────────────
    SYSTEM_NAME: str        = field(default_factory=lambda: _env("SYSTEM_NAME", "SmartNile"))
    LOG_LEVEL: str          = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    SIMULATION_MODE: bool   = field(default_factory=lambda: _bool("SIMULATION_MODE", True))
    MISSION_ID: str         = field(default_factory=lambda: _env("MISSION_ID", "mission_001"))

    # ── Firebase ────────────────────────────────────────────────────────────
    FIREBASE_PROJECT_ID: str         = field(default_factory=lambda: _env("FIREBASE_PROJECT_ID", ""))
    FIREBASE_CREDENTIALS_PATH: str   = field(default_factory=lambda: _env(
        "FIREBASE_CREDENTIALS_PATH",
        str(_BACKEND_DIR / "config" / "firebase_credentials.json")
    ))
    FIREBASE_DATABASE_URL: str       = field(default_factory=lambda: _env("FIREBASE_DATABASE_URL", ""))
    FIREBASE_STORAGE_BUCKET: str     = field(default_factory=lambda: _env("FIREBASE_STORAGE_BUCKET", ""))
    FIREBASE_BATCH_SIZE: int         = field(default_factory=lambda: _int("FIREBASE_BATCH_SIZE", 20))
    FIREBASE_FLUSH_INTERVAL: float   = field(default_factory=lambda: _float("FIREBASE_FLUSH_INTERVAL", 10.0))

    # ── AI / LLM ────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str     = field(default_factory=lambda: _env("GEMINI_API_KEY", ""))
    OPENAI_API_KEY: str     = field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    AI_PROVIDER: str        = field(default_factory=lambda: _env("AI_PROVIDER", "gemini"))  # "gemini"|"openai"

    # ── YOLO / Camera ────────────────────────────────────────────────────────
    MODEL_PATH: str         = field(default_factory=lambda: _env(
        "MODEL_PATH",
        str(_BACKEND_DIR / "models" / "plant_detect.tflite")
    ))
    MODEL_CONFIDENCE: float = field(default_factory=lambda: _float("MODEL_CONFIDENCE", 0.60))
    CAMERA_INDEX: int       = field(default_factory=lambda: _int("CAMERA_INDEX", 0))
    CAMERA_WIDTH: int       = field(default_factory=lambda: _int("CAMERA_WIDTH", 640))
    CAMERA_HEIGHT: int      = field(default_factory=lambda: _int("CAMERA_HEIGHT", 480))
    CAMERA_FPS: int         = field(default_factory=lambda: _int("CAMERA_FPS", 5))
    DETECTION_DEBOUNCE: float = field(default_factory=lambda: _float("DETECTION_DEBOUNCE", 5.0))  # seconds

    # ── GPS ─────────────────────────────────────────────────────────────────
    GPS_PORT: str           = field(default_factory=lambda: _env("GPS_PORT", "/dev/ttyAMA0"))
    GPS_BAUD: int           = field(default_factory=lambda: _int("GPS_BAUD", 9600))
    GPS_TIMEOUT: float      = field(default_factory=lambda: _float("GPS_TIMEOUT", 2.0))
    GPS_INTERVAL: float     = field(default_factory=lambda: _float("GPS_INTERVAL", 1.0))   # seconds between reads

    # ── Sensor serial / I2C ─────────────────────────────────────────────────
    ARDUINO_PORT: str       = field(default_factory=lambda: _env("ARDUINO_PORT", "/dev/ttyUSB0"))
    ARDUINO_BAUD: int       = field(default_factory=lambda: _int("ARDUINO_BAUD", 9600))
    SENSOR_INTERVAL: float  = field(default_factory=lambda: _float("SENSOR_INTERVAL", 2.0))  # seconds

    # ── DS18B20 (1-Wire) ────────────────────────────────────────────────────
    DS18B20_BASE_PATH: str  = field(default_factory=lambda: _env(
        "DS18B20_BASE_PATH", "/sys/bus/w1/devices"
    ))

    # ── Local offline buffer ─────────────────────────────────────────────────
    SQLITE_PATH: str        = field(default_factory=lambda: _env(
        "SQLITE_PATH",
        str(_BACKEND_DIR / "data" / "offline_buffer.db")
    ))

    # ── Snapshots & exports ─────────────────────────────────────────────────
    SNAPSHOTS_DIR: str      = field(default_factory=lambda: _env(
        "SNAPSHOTS_DIR",
        str(_BACKEND_DIR / "data" / "snapshots")
    ))
    EXPORTS_DIR: str        = field(default_factory=lambda: _env(
        "EXPORTS_DIR",
        str(_BACKEND_DIR / "data" / "exports")
    ))
    LOGS_DIR: str           = field(default_factory=lambda: _env(
        "LOGS_DIR",
        str(_BACKEND_DIR / "data" / "logs")
    ))

    # ── Alert thresholds ─────────────────────────────────────────────────────
    # Each sensor has: critical_low, warning_low, warning_high, critical_high
    # None = threshold not applicable for that side
    THRESHOLDS: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "pH": {
            "unit":          "pH",
            "critical_low":  4.0,
            "warning_low":   6.5,
            "warning_high":  8.5,
            "critical_high": 10.0,
            "description":   "Water acidity/alkalinity",
        },
        "tds": {
            "unit":          "ppm",
            "critical_low":  None,
            "warning_low":   None,
            "warning_high":  500.0,
            "critical_high": 1000.0,
            "description":   "Total dissolved solids",
        },
        "turbidity": {
            "unit":          "NTU",
            "critical_low":  None,
            "warning_low":   None,
            "warning_high":  50.0,
            "critical_high": 100.0,
            "description":   "Water clarity",
        },
        "temperature": {
            "unit":          "°C",
            "critical_low":  5.0,
            "warning_low":   10.0,
            "warning_high":  35.0,
            "critical_high": 40.0,
            "description":   "Water temperature",
        },
        "ammonia": {
            "unit":          "ppm",
            "critical_low":  None,
            "warning_low":   None,
            "warning_high":  0.5,
            "critical_high": 2.0,
            "description":   "Ammonia concentration",
        },
    })

    # ── Google Maps (used by frontend, exposed via Firebase) ─────────────────
    GOOGLE_MAPS_API_KEY: str = field(default_factory=lambda: _env("GOOGLE_MAPS_API_KEY", ""))

    def validate(self) -> list[str]:
        """
        Returns a list of validation warnings.  Does NOT raise —
        the system can still run in simulation mode with missing keys.
        """
        warnings = []
        if not self.SIMULATION_MODE:
            if not self.FIREBASE_PROJECT_ID:
                warnings.append("FIREBASE_PROJECT_ID is not set. Firebase writes will fail.")
            if not self.FIREBASE_CREDENTIALS_PATH or not Path(self.FIREBASE_CREDENTIALS_PATH).exists():
                warnings.append(f"Firebase credentials not found at {self.FIREBASE_CREDENTIALS_PATH}")
            if not self.GEMINI_API_KEY and not self.OPENAI_API_KEY:
                warnings.append("No AI API key set. AI Advisor will be disabled.")
        return warnings


# ── module-level singleton ────────────────────────────────────────────────────
settings = Settings()
