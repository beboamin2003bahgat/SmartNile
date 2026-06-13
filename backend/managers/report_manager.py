"""
managers/report_manager.py
==========================
Generates daily summary reports from the mission data collected during
the current run and from the local SQLite offline buffer.

Report formats produced
-----------------------
1. JSON  — full machine-readable summary (used by the React dashboard)
2. CSV   — tabular sensor readings (opens in Excel / Google Sheets)

Reports are saved to:
    data/exports/YYYY-MM-DD_{mission_id}.{json|csv}

When Firebase is connected, the FirebaseManager is called to upload the
JSON report to Firestore (collection: reports/) and the CSV to Storage.

Scheduling
----------
ReportManager runs its own background thread that wakes every
REPORT_INTERVAL_HOURS (default: 24) and produces a new report.
main.py may also call generate_now() at mission end.

Report content
--------------
{
  "mission_id":   "...",
  "generated_at": "ISO timestamp",
  "period_hours": 24,
  "sensor_stats": {
      "pH":          { "min", "max", "mean", "stddev", "samples" },
      "tds":         { ... },
      "turbidity":   { ... },
      "temperature": { ... },
      "ammonia":     { ... }
  },
  "gps_summary": {
      "total_fixes":    N,
      "distance_km":    X.X,
      "start":          { lat, lon },
      "end":            { lat, lon }
  },
  "alerts_summary": {
      "total":    N,
      "critical": N,
      "warning":  N,
      "info":     N
  },
  "detections_summary": {
      "total":            N,
      "water_hyacinth":   N,
      "water_lettuce":    N,
      "algae_bloom":      N
  }
}
"""

import csv
import json
import math
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config.settings import settings
from utils.logger import get_logger
from utils.validators import AlertEvent, DetectionResult, GPSFix, SensorReading, now

log = get_logger("report_manager")

REPORT_INTERVAL_HOURS = float(os.environ.get("REPORT_INTERVAL_HOURS", "24"))


class ReportManager:
    def __init__(
        self,
        on_report_ready: Optional[Callable[[str, dict], None]] = None,
    ):
        """
        Parameters
        ----------
        on_report_ready : callable(json_path: str, report: dict)
            Called after each report is generated. Wired to
            FirebaseManager.push_report() in main.py.
        """
        self._on_report  = on_report_ready
        self._mission_id = settings.MISSION_ID
        self._exports    = Path(settings.EXPORTS_DIR)
        self._exports.mkdir(parents=True, exist_ok=True)

        # in-memory accumulators (appended to by manager callbacks)
        self._lock        = threading.Lock()
        self._readings:   List[SensorReading]   = []
        self._fixes:      List[GPSFix]           = []
        self._alerts:     List[AlertEvent]       = []
        self._detections: List[DetectionResult]  = []

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_report_time = time.time()

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(
            target=self._scheduler_loop,
            name="ReportScheduler",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "[ReportManager] Started (interval=%.0fh, exports=%s)",
            REPORT_INTERVAL_HOURS, self._exports,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    # ── data ingestion (called by sensor/gps/alert/ai callbacks) ─────────────
    def record_reading(self, reading: SensorReading) -> None:
        with self._lock:
            self._readings.append(reading)
            # cap at 50 k readings to avoid OOM on long missions
            if len(self._readings) > 50_000:
                self._readings = self._readings[-40_000:]

    def record_fix(self, fix: GPSFix) -> None:
        with self._lock:
            self._fixes.append(fix)
            if len(self._fixes) > 50_000:
                self._fixes = self._fixes[-40_000:]

    def record_alert(self, alert: AlertEvent) -> None:
        with self._lock:
            self._alerts.append(alert)

    def record_detection(self, det: DetectionResult) -> None:
        with self._lock:
            self._detections.append(det)

    # ── on-demand generation ──────────────────────────────────────────────────
    def generate_now(self) -> Optional[str]:
        """
        Generate a report immediately (e.g. at mission end).
        Returns the path of the JSON report file, or None on failure.
        """
        return self._generate()

    def status(self) -> dict:
        with self._lock:
            return {
                "running":         self._running,
                "readings_stored": len(self._readings),
                "fixes_stored":    len(self._fixes),
                "alerts_stored":   len(self._alerts),
                "detections_stored": len(self._detections),
                "exports_dir":     str(self._exports),
                "last_report_ago_s": round(time.time() - self._last_report_time, 0),
            }

    # ── scheduler ─────────────────────────────────────────────────────────────
    def _scheduler_loop(self) -> None:
        interval_s = REPORT_INTERVAL_HOURS * 3600
        while self._running:
            elapsed = time.time() - self._last_report_time
            if elapsed >= interval_s:
                self._generate()
            time.sleep(60)   # wake every minute to check

    # ── report builder ────────────────────────────────────────────────────────
    def _generate(self) -> Optional[str]:
        log.info("[ReportManager] Generating report...")
        ts = datetime.now(timezone.utc)

        with self._lock:
            readings   = list(self._readings)
            fixes      = list(self._fixes)
            alerts     = list(self._alerts)
            detections = list(self._detections)

        try:
            report = {
                "mission_id":         self._mission_id,
                "generated_at":       ts.isoformat(),
                "generated_at_epoch": now(),
                "period_hours":       REPORT_INTERVAL_HOURS,
                "sensor_stats":       self._sensor_stats(readings),
                "gps_summary":        self._gps_summary(fixes),
                "alerts_summary":     self._alerts_summary(alerts),
                "detections_summary": self._detections_summary(detections),
            }

            date_str  = ts.strftime("%Y-%m-%d_%H%M")
            stem      = f"{date_str}_{self._mission_id}"
            json_path = self._exports / f"{stem}.json"
            csv_path  = self._exports / f"{stem}_sensors.csv"

            # write JSON
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2, default=str)

            # write CSV
            self._write_csv(readings, csv_path)

            log.info(f"[ReportManager] Report saved → {json_path.name}")
            self._last_report_time = time.time()

            if self._on_report:
                self._on_report(str(json_path), report)

            return str(json_path)

        except Exception as exc:
            log.error(f"[ReportManager] Generation failed: {exc}", exc_info=True)
            return None

    # ── statistics helpers ────────────────────────────────────────────────────
    @staticmethod
    def _stats_for(values: List[float]) -> Dict[str, Any]:
        if not values:
            return {"min": None, "max": None, "mean": None, "stddev": None, "samples": 0}
        n    = len(values)
        mn   = min(values)
        mx   = max(values)
        mean = sum(values) / n
        var  = sum((v - mean) ** 2 for v in values) / n
        return {
            "min":     round(mn,   4),
            "max":     round(mx,   4),
            "mean":    round(mean, 4),
            "stddev":  round(math.sqrt(var), 4),
            "samples": n,
        }

    def _sensor_stats(self, readings: List[SensorReading]) -> Dict[str, Any]:
        buckets: Dict[str, List[float]] = defaultdict(list)
        for r in readings:
            for field in ("pH", "tds", "turbidity", "temperature", "ammonia"):
                val = getattr(r, field, None)
                if val is not None:
                    buckets[field].append(val)
        return {k: self._stats_for(v) for k, v in buckets.items()}

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance in km."""
        R  = 6371.0
        φ1 = math.radians(lat1);  φ2 = math.radians(lat2)
        Δφ = math.radians(lat2 - lat1)
        Δλ = math.radians(lon2 - lon1)
        a  = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _gps_summary(self, fixes: List[GPSFix]) -> Dict[str, Any]:
        valid = [f for f in fixes if f.has_fix]
        if not valid:
            return {"total_fixes": 0, "valid_fixes": 0, "distance_km": 0.0}
        dist = 0.0
        for i in range(1, len(valid)):
            prev = valid[i - 1]
            curr = valid[i]
            if None not in (prev.latitude, prev.longitude, curr.latitude, curr.longitude):
                dist += self._haversine_km(
                    prev.latitude, prev.longitude,
                    curr.latitude, curr.longitude,
                )
        return {
            "total_fixes":  len(fixes),
            "valid_fixes":  len(valid),
            "distance_km":  round(dist, 3),
            "start":        {"lat": valid[0].latitude,  "lon": valid[0].longitude},
            "end":          {"lat": valid[-1].latitude, "lon": valid[-1].longitude},
        }

    @staticmethod
    def _alerts_summary(alerts: List[AlertEvent]) -> Dict[str, Any]:
        by_level: Dict[str, int] = defaultdict(int)
        by_cat:   Dict[str, int] = defaultdict(int)
        for a in alerts:
            by_level[a.level]    += 1
            by_cat[a.category]   += 1
        return {
            "total":    len(alerts),
            "critical": by_level.get("critical", 0),
            "warning":  by_level.get("warning",  0),
            "info":     by_level.get("info",     0),
            "by_category": dict(by_cat),
        }

    @staticmethod
    def _detections_summary(dets: List[DetectionResult]) -> Dict[str, Any]:
        by_species: Dict[str, int] = defaultdict(int)
        for d in dets:
            by_species[d.species_name] += 1
        return {
            "total":          len(dets),
            "water_hyacinth": by_species.get("water_hyacinth", 0),
            "water_lettuce":  by_species.get("water_lettuce",  0),
            "algae_bloom":    by_species.get("algae_bloom",    0),
            "unknown_plant":  by_species.get("unknown_plant",  0),
        }

    # ── CSV writer ────────────────────────────────────────────────────────────
    @staticmethod
    def _write_csv(readings: List[SensorReading], path: Path) -> None:
        if not readings:
            return
        fieldnames = ["timestamp", "utc", "pH", "tds", "turbidity",
                      "temperature", "ammonia", "source", "mission_id"]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in readings:
                row = r.to_dict()
                row["utc"] = datetime.fromtimestamp(
                    r.timestamp, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow(row)
        log.info(f"[ReportManager] CSV saved → {path.name} ({len(readings)} rows)")
