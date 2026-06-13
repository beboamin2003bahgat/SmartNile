"""
main.py
=======
Smart Nile backend entry point.

This module:
  1. Reads .env / environment configuration
  2. Validates settings and warns about missing keys
  3. Instantiates all managers in dependency order
  4. Wires callback chains between managers
  5. Starts all managers
  6. Runs until SIGINT / SIGTERM
  7. Performs graceful shutdown in reverse order

Data flow wired here
--------------------
SensorManager ──on_reading──► AlertManager.process_sensor()
                           └─► ReportManager.record_reading()
                           └─► FirebaseManager.push_sensor()

GPSManager ────on_fix──────► ReportManager.record_fix()
                          └─► FirebaseManager.push_gps()
                          └─► AIManager (injected via GPS ref)

AIManager ─────on_detection► AlertManager.process_detection()
                          └─► ReportManager.record_detection()
                          └─► FirebaseManager.push_detection()

AlertManager ──on_alert────► ReportManager.record_alert()
                          └─► FirebaseManager.push_alert()

ReportManager──on_report───► FirebaseManager.push_report() (JSON upload)

Usage
-----
    # Simulation mode (no hardware needed)
    SIMULATION_MODE=True python main.py

    # Production
    SIMULATION_MODE=False python main.py

    # Background (via systemd)
    see deployment/smartnile.service
"""

import signal
import sys
import time
from typing import Optional

from config.settings import settings
from managers import (
    AIManager,
    AlertManager,
    CameraManager,
    FirebaseManager,
    GPSManager,
    ReportManager,
    SensorManager,
)
from managers.system_monitor import SystemMonitor
from utils.logger import configure_logging, get_logger
from utils.validators import AlertEvent, DetectionResult, GPSFix, SensorReading

# ── bootstrap logging before anything else ────────────────────────────────────
configure_logging(level=settings.LOG_LEVEL, logs_dir=settings.LOGS_DIR)
log = get_logger("main")


# ─────────────────────────────────────────────────────────────────────────────
class SmartNileMission:
    """
    Owns all manager instances and their wiring.
    Call start() to begin the mission, stop() to end it cleanly.
    """

    def __init__(self):
        self._running   = False

        # ── 1. Firebase (starts first so other callbacks can push immediately) ─
        self._firebase  = FirebaseManager()

        # ── 2. Alert manager (needs firebase reference for its callback) ────────
        self._alerts    = AlertManager(
            on_alert=self._on_alert,
        )

        # ── 3. Report manager ────────────────────────────────────────────────────
        self._reports   = ReportManager(
            on_report_ready=self._on_report_ready,
        )

        # ── 4. GPS manager ───────────────────────────────────────────────────────
        self._gps       = GPSManager(
            on_fix=self._on_gps_fix,
        )

        # ── 5. Camera manager ────────────────────────────────────────────────────
        self._camera    = CameraManager()

        # ── 6. AI manager (needs camera + gps references) ────────────────────────
        self._ai        = AIManager(
            camera=self._camera,
            gps=self._gps,
            on_detection=self._on_detection,
        )

        # ── 7. Sensor manager (started last — it begins emitting data immediately)
        self._sensors   = SensorManager(
            on_reading=self._on_sensor_reading,
        )

        # ── 8. System monitor (CPU / RAM / temp — appended to heartbeat) ─────────
        self._sysmon    = SystemMonitor(interval=10.0)

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        log.info("=" * 60)
        log.info("  SMART NILE — Mission starting")
        log.info(f"  Mission ID   : {settings.MISSION_ID}")
        log.info(f"  Simulation   : {settings.SIMULATION_MODE}")
        log.info(f"  Firebase     : {settings.FIREBASE_PROJECT_ID or 'not configured'}")
        log.info("=" * 60)

        # validate settings and print warnings
        warnings = settings.validate()
        for w in warnings:
            log.warning(f"[Config] {w}")

        # start in dependency order
        self._firebase.start()
        self._reports.start()
        self._gps.start()
        self._camera.start()
        self._ai.start()
        self._sensors.start()   # begins emitting readings — must be last
        self._sysmon.start()    # non-blocking, populates cache immediately

        self._running = True
        self._alerts.process_system(
            title   = "Mission Started",
            message = f"Smart Nile mission {settings.MISSION_ID} started successfully.",
            level   = "info",
        )
        log.info("[Main] All systems online. Running...")

    def stop(self) -> None:
        if not self._running:
            return
        log.info("[Main] Shutting down...")
        self._running = False

        self._alerts.process_system(
            title   = "Mission Ended",
            message = f"Mission {settings.MISSION_ID} ended. Generating final report.",
            level   = "info",
        )

        # generate final report before closing Firebase
        final_report = self._reports.generate_now()
        if final_report:
            log.info(f"[Main] Final report: {final_report}")

        # stop in reverse order
        self._sysmon.stop()
        self._sensors.stop()
        self._ai.stop()
        self._camera.stop()
        self._gps.stop()
        self._reports.stop()
        self._firebase.stop()   # last — flushes remaining writes

        log.info("[Main] Shutdown complete.")

    def run_forever(self) -> None:
        """Block until SIGINT / SIGTERM."""
        self.start()
        try:
            while self._running:
                self._print_status()
                time.sleep(30)
        except KeyboardInterrupt:
            log.info("[Main] KeyboardInterrupt received")
        finally:
            self.stop()

    def status(self) -> dict:
        return {
            "mission_id": settings.MISSION_ID,
            "simulation": settings.SIMULATION_MODE,
            "sensors":    self._sensors.status(),
            "gps":        self._gps.status(),
            "camera":     self._camera.status(),
            "ai":         self._ai.status(),
            "alerts":     self._alerts.status(),
            "firebase":   self._firebase.status(),
            "reports":    self._reports.status(),
        }

    # ── callback implementations ──────────────────────────────────────────────
    def _on_sensor_reading(self, reading: SensorReading) -> None:
        """Fires every SENSOR_INTERVAL seconds with a fresh SensorReading."""
        # alert evaluation
        self._alerts.process_sensor(reading)
        # report accumulation
        self._reports.record_reading(reading)
        # push to Firebase
        self._firebase.push_sensor(reading)

    def _on_gps_fix(self, fix: GPSFix) -> None:
        """Fires every GPS_INTERVAL seconds with a fresh GPSFix."""
        self._reports.record_fix(fix)
        self._firebase.push_gps(fix)

        # check for GPS signal loss (fix quality 0)
        if not fix.has_fix:
            self._alerts.process_gps_lost()

    def _on_detection(self, det: DetectionResult) -> None:
        """Fires when AIManager identifies a plant species above confidence threshold."""
        self._alerts.process_detection(det)
        self._reports.record_detection(det)
        self._firebase.push_detection(det)

    def _on_alert(self, alert: AlertEvent) -> None:
        """Fires for every new deduplicated alert."""
        self._reports.record_alert(alert)
        self._firebase.push_alert(alert)

    def _on_report_ready(self, json_path: str, report: dict) -> None:
        """Called by ReportManager when a report file is written."""
        log.info(f"[Main] Report ready: {json_path}")
        # push JSON summary doc to Firestore reports/ collection
        from utils.validators import now
        report_doc = {
            "path":       json_path,
            "mission_id": settings.MISSION_ID,
            "generated":  now(),
            **{k: v for k, v in report.items() if k != "mission_id"},
        }
        from managers.firebase_manager import _WriteJob
        self._firebase._enqueue(
            _WriteJob(collection="reports", data=report_doc)
        )

    # ── periodic status print + heartbeat ────────────────────────────────────
    def _print_status(self) -> None:
        s      = self.status()
        latest = self._sensors.get_latest()
        gps    = self._gps.get_latest()
        sys_m  = self._sysmon.snapshot()

        # push system metrics inside the heartbeat document
        self._firebase.push_heartbeat(extra=sys_m)

        log.info("-" * 50)
        if latest:
            log.info(
                f"  Sensors  pH={latest.pH}  TDS={latest.tds}  "
                f"Turb={latest.turbidity}  Temp={latest.temperature}  NH3={latest.ammonia}"
            )
        if gps and gps.has_fix:
            log.info(
                f"  GPS      lat={gps.latitude:.5f}  lon={gps.longitude:.5f}  "
                f"sats={gps.satellites}  speed={gps.speed} km/h"
            )
        if sys_m:
            log.info(
                f"  System   CPU={sys_m.get('cpu_pct')}%  "
                f"RAM={sys_m.get('ram_pct')}%  "
                f"Temp={sys_m.get('cpu_temp_c')}°C  "
                f"Battery={sys_m.get('battery_pct')}%"
            )
        log.info(
            f"  Firebase queue={s['firebase']['queue_size']}  "
            f"writes={s['firebase']['total_writes']}  "
            f"offline={s['firebase']['offline_buffer_rows']}"
        )
        log.info(
            f"  Alerts   total={s['alerts']['total_alerts']}  "
            f"detections={s['ai']['total_detections']}"
        )
        log.info("-" * 50)


# ── signal handling ───────────────────────────────────────────────────────────
_mission: Optional[SmartNileMission] = None

def _handle_signal(signum, frame):
    log.info(f"[Main] Signal {signum} received — initiating shutdown")
    if _mission:
        _mission.stop()
    sys.exit(0)


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _mission = SmartNileMission()
    _mission.run_forever()
