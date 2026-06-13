"""
utils/validators.py
===================
Canonical data models for every sensor reading and GPS fix used across
the entire Smart Nile backend.

All inter-module data exchange uses these dataclasses — never raw dicts.
This ensures:
  - Type safety between SensorManager, AlertManager, FirebaseManager
  - A single place to add new sensor types
  - Automatic JSON serialisation via .to_dict()

Classes
-------
SensorReading   — one timestamped set of all sensor values
GPSFix          — one timestamped GPS coordinate
DetectionResult — one YOLO/TFLite plant detection event
AlertEvent      — one alert (critical / warning / info)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any

# ── Physical plausibility bounds (not alert thresholds — see settings.py) ────
# Values outside these bounds are tagged as SENSOR_ERROR and discarded.
_PHYSICAL_BOUNDS: Dict[str, tuple] = {
    "pH":          (0.0,    14.0),
    "tds":         (0.0,  5000.0),
    "turbidity":   (0.0,  3000.0),
    "temperature": (-5.0,   60.0),
    "ammonia":     (0.0,   100.0),
}


@dataclass
class SensorReading:
    """
    One complete sensor sample.

    Fields set to None mean the sensor was offline or returned an error
    for that cycle. The rest of the pipeline handles None gracefully —
    it is never written to Firebase and never triggers an alert.
    """
    timestamp:   float          # Unix epoch (seconds)
    pH:          Optional[float] = None
    tds:         Optional[float] = None   # ppm
    turbidity:   Optional[float] = None   # NTU
    temperature: Optional[float] = None   # °C
    ammonia:     Optional[float] = None   # ppm
    source:      str             = "sensor"   # "sensor" | "simulation"
    errors:      Dict[str, str]  = field(default_factory=dict)
    mission_id:  str             = ""

    # ── post-init validation ────────────────────────────────────────────────
    def __post_init__(self):
        for key, (lo, hi) in _PHYSICAL_BOUNDS.items():
            val = getattr(self, key)
            if val is not None and not (lo <= val <= hi):
                self.errors[key] = f"Out of physical range: {val} not in [{lo}, {hi}]"
                setattr(self, key, None)

    @property
    def is_valid(self) -> bool:
        """At least one sensor returned a usable value."""
        return any(
            getattr(self, k) is not None
            for k in ("pH", "tds", "turbidity", "temperature", "ammonia")
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # strip None values so Firebase documents stay lean
        return {k: v for k, v in d.items() if v is not None and v != {}}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SensorReading":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class GPSFix:
    """One GPS coordinate sample from the NEO-6M module."""
    timestamp:  float
    latitude:   Optional[float] = None   # decimal degrees, WGS84
    longitude:  Optional[float] = None
    altitude:   Optional[float] = None   # metres
    speed:      Optional[float] = None   # km/h
    heading:    Optional[float] = None   # degrees true north
    satellites: Optional[int]   = None
    fix_quality: int             = 0     # 0=no fix, 1=GPS, 2=DGPS
    source:     str              = "gps"  # "gps" | "simulation"
    mission_id: str              = ""

    @property
    def has_fix(self) -> bool:
        return (
            self.latitude  is not None
            and self.longitude is not None
            and self.fix_quality > 0
        )

    @property
    def is_in_egypt(self) -> bool:
        """Loose bounding box for Egypt — used to flag GPS spoofing."""
        if not self.has_fix:
            return False
        return (22.0 <= self.latitude <= 32.0) and (24.0 <= self.longitude <= 38.0)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class DetectionResult:
    """
    One plant detection event from the YOLO / TFLite pipeline.

    species_id maps to DetectionResult.SPECIES below.
    """
    SPECIES = {
        0: "water_hyacinth",
        1: "water_lettuce",
        2: "algae_bloom",
        3: "unknown_plant",
    }

    timestamp:       float
    species_id:      int
    confidence:      float          # 0.0 – 1.0
    bounding_box:    Dict[str, int] # {x, y, w, h} in pixels
    frame_path:      Optional[str]  = None   # local path to saved JPEG
    storage_url:     Optional[str]  = None   # Firebase Storage URL after upload
    latitude:        Optional[float] = None
    longitude:       Optional[float] = None
    mission_id:      str             = ""
    reviewed:        bool            = False

    @property
    def species_name(self) -> str:
        return self.SPECIES.get(self.species_id, "unknown")

    @property
    def severity(self) -> str:
        if self.confidence >= 0.85:
            return "high"
        if self.confidence >= 0.65:
            return "medium"
        return "low"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["species_name"] = self.species_name
        d["severity"]     = self.severity
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class AlertEvent:
    """One alert generated by the AlertManager."""

    LEVELS    = ("critical", "warning", "info")
    CATEGORIES = ("pH", "tds", "turbidity", "temperature", "ammonia", "gps", "detection", "system")

    timestamp:   float
    level:       str              # "critical" | "warning" | "info"
    category:    str              # sensor name or "gps" / "detection" / "system"
    title:       str
    message:     str
    value:       Optional[float] = None
    threshold:   Optional[float] = None
    unit:        str              = ""
    confidence:  Optional[float] = None   # for detection alerts
    latitude:    Optional[float] = None
    longitude:   Optional[float] = None
    acknowledged: bool            = False
    mission_id:  str              = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


def now() -> float:
    """Consistent timestamp for the entire codebase."""
    return time.time()
