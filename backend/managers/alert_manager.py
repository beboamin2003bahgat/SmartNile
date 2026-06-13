"""
managers/alert_manager.py
==========================
Evaluates every SensorReading and DetectionResult against configured
thresholds and emits AlertEvent objects.

Alert levels
------------
critical  — immediate danger to ecosystem / instrument out of range
warning   — approaching dangerous levels, action recommended
info      — notable event (plant detected, GPS fix lost, system event)

Deduplication / cooldown
------------------------
The same (category, level) pair is not re-issued until a configurable
cooldown expires.  This prevents alert storms when a sensor stays
outside its threshold for many consecutive readings.

Default cooldowns
-----------------
critical : 120 seconds (re-alert every 2 minutes while condition persists)
warning  : 300 seconds (5 minutes)
info     : 60  seconds (1 minute)

Integration
-----------
AlertManager receives readings via process_sensor() and process_detection().
It emits alerts via the on_alert callback, which is wired to:
  - FirebaseManager.push_alert()
  - (optionally) a Telegram / email notifier
"""

import time
import threading
from typing import Callable, Dict, List, Optional, Tuple

from config.settings import settings
from utils.logger import get_logger
from utils.validators import AlertEvent, DetectionResult, SensorReading, now

log = get_logger("alert_manager")

# cooldown seconds per alert level
_COOLDOWN: Dict[str, float] = {
    "critical": 120.0,
    "warning":  300.0,
    "info":      60.0,
}


class AlertManager:
    def __init__(
        self,
        on_alert: Optional[Callable[[AlertEvent], None]] = None,
    ):
        self._on_alert    = on_alert
        self._thresholds  = settings.THRESHOLDS
        self._mission_id  = settings.MISSION_ID

        # dedup tracking: key = (category, level) → last emitted timestamp
        self._last_alert: Dict[Tuple[str, str], float] = {}
        self._lock        = threading.Lock()

        # history (last 500 alerts kept in memory for dashboard /status)
        self._history: List[AlertEvent] = []
        self._MAX_HISTORY = 500
        self._total_alerts = 0

    # ── public API ────────────────────────────────────────────────────────────
    def process_sensor(self, reading: SensorReading) -> List[AlertEvent]:
        """
        Evaluate all sensor values in a SensorReading.
        Returns any alerts that were newly emitted (not deduplicated).
        """
        emitted = []
        fields = {
            "pH":          reading.pH,
            "tds":         reading.tds,
            "turbidity":   reading.turbidity,
            "temperature": reading.temperature,
            "ammonia":     reading.ammonia,
        }
        fix_lat = fix_lon = None   # filled later if GPS is injected

        for key, value in fields.items():
            if value is None:
                continue
            thresh = self._thresholds.get(key)
            if not thresh:
                continue
            alert = self._evaluate(
                category    = key,
                value       = value,
                threshold   = thresh,
                unit        = thresh.get("unit", ""),
                lat         = fix_lat,
                lon         = fix_lon,
            )
            if alert:
                emitted.append(alert)

        return emitted

    def process_detection(
        self,
        det: DetectionResult,
    ) -> Optional[AlertEvent]:
        """
        A plant detection always emits an alert (subject to cooldown).
        Water hyacinth and water lettuce = critical.
        Other species = warning.
        """
        level = "critical" if det.species_id in (0, 1) else "warning"
        title = f"{det.species_name.replace('_', ' ').title()} Detected"
        msg   = (
            f"{det.species_name.replace('_', ' ').title()} detected with "
            f"{det.confidence:.0%} confidence. "
            f"Location: {det.latitude:.5f}°N, {det.longitude:.5f}°E."
        )
        alert = AlertEvent(
            timestamp  = now(),
            level      = level,
            category   = "detection",
            title      = title,
            message    = msg,
            confidence = det.confidence if hasattr(det, 'confidence') else None,
            latitude   = det.latitude,
            longitude  = det.longitude,
            mission_id = self._mission_id,
        )
        return self._maybe_emit(alert)

    def process_gps_lost(self) -> Optional[AlertEvent]:
        alert = AlertEvent(
            timestamp  = now(),
            level      = "warning",
            category   = "gps",
            title      = "GPS Signal Lost",
            message    = "The GPS module has not returned a valid fix. Boat position unknown.",
            mission_id = self._mission_id,
        )
        return self._maybe_emit(alert)

    def process_system(self, title: str, message: str, level: str = "info") -> Optional[AlertEvent]:
        alert = AlertEvent(
            timestamp  = now(),
            level      = level,
            category   = "system",
            title      = title,
            message    = message,
            mission_id = self._mission_id,
        )
        return self._maybe_emit(alert)

    def get_history(self, limit: int = 100) -> List[AlertEvent]:
        with self._lock:
            return list(self._history[-limit:])

    def get_history_dicts(self, limit: int = 100) -> List[dict]:
        return [a.to_dict() for a in self.get_history(limit)]

    def status(self) -> dict:
        with self._lock:
            recent = self._history[-5:] if self._history else []
        return {
            "total_alerts":  self._total_alerts,
            "history_size":  len(self._history),
            "active_cooldowns": len(self._last_alert),
            "recent_alerts": [a.to_dict() for a in recent],
        }

    # ── threshold evaluation ──────────────────────────────────────────────────
    def _evaluate(
        self,
        category: str,
        value:    float,
        threshold: dict,
        unit:     str,
        lat:      Optional[float],
        lon:      Optional[float],
    ) -> Optional[AlertEvent]:
        level = title = message = None
        breach_thresh = None

        c_low  = threshold.get("critical_low")
        c_high = threshold.get("critical_high")
        w_low  = threshold.get("warning_low")
        w_high = threshold.get("warning_high")

        if c_low is not None and value < c_low:
            level = "critical"
            breach_thresh = c_low
            title   = f"CRITICAL: {category} too low"
            message = (
                f"{category} reading of {value:.2f} {unit} is critically below "
                f"the minimum threshold of {c_low} {unit}."
            )
        elif c_high is not None and value > c_high:
            level = "critical"
            breach_thresh = c_high
            title   = f"CRITICAL: {category} too high"
            message = (
                f"{category} reading of {value:.2f} {unit} critically exceeds "
                f"the maximum threshold of {c_high} {unit}."
            )
        elif w_low is not None and value < w_low:
            level = "warning"
            breach_thresh = w_low
            title   = f"Warning: {category} below normal range"
            message = (
                f"{category} reading of {value:.2f} {unit} is below the "
                f"warning threshold of {w_low} {unit}."
            )
        elif w_high is not None and value > w_high:
            level = "warning"
            breach_thresh = w_high
            title   = f"Warning: {category} above normal range"
            message = (
                f"{category} reading of {value:.2f} {unit} exceeds the "
                f"warning threshold of {w_high} {unit}."
            )

        if level is None:
            return None

        alert = AlertEvent(
            timestamp  = now(),
            level      = level,
            category   = category,
            title      = title,
            message    = message,
            value      = round(value, 4),
            threshold  = breach_thresh,
            unit       = unit,
            latitude   = lat,
            longitude  = lon,
            mission_id = self._mission_id,
        )
        return self._maybe_emit(alert)

    # ── deduplication ─────────────────────────────────────────────────────────
    def _maybe_emit(self, alert: AlertEvent) -> Optional[AlertEvent]:
        key      = (alert.category, alert.level)
        cooldown = _COOLDOWN.get(alert.level, 60.0)

        with self._lock:
            last = self._last_alert.get(key, 0.0)
            if (now() - last) < cooldown:
                return None   # still in cooldown
            self._last_alert[key] = now()
            self._total_alerts += 1
            self._history.append(alert)
            if len(self._history) > self._MAX_HISTORY:
                self._history = self._history[-self._MAX_HISTORY:]

        log.warning(f"[Alert] [{alert.level.upper()}] {alert.title}: {alert.message[:80]}")

        if self._on_alert:
            self._on_alert(alert)

        return alert
