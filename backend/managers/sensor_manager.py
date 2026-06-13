"""
managers/sensor_manager.py
==========================
Orchestrates every water-quality sensor.

Responsibilities
----------------
1. Opens and owns all sensor driver instances
2. Runs a background thread that reads all sensors every SENSOR_INTERVAL
3. Parses JSON lines from the Arduino Nano over serial when not in
   simulation mode (serial format: {"sensor":"pH","value":7.34}\n)
4. Produces SensorReading dataclass instances
5. Calls an optional callback so other managers (AlertManager,
   FirebaseManager) receive readings without polling

Hardware wiring summary
-----------------------
Arduino Nano → USB serial → Raspberry Pi 5 (/dev/ttyUSB0)
    A0  →  pH probe
    A1  →  TDS probe
    A2  →  Turbidity probe
    A3  →  MQ-137 ammonia
DS18B20 → GPIO 4 (1-Wire, direct to RPi)

Thread safety
-------------
The latest SensorReading is stored in self._latest under a threading.Lock.
Callers may read it at any time with get_latest().
"""

import json
import threading
import time
from typing import Callable, Optional

from config.settings import settings
from sensors import PHSensor, TDSSensor, TurbiditySensor, DS18B20Sensor, MQ137Sensor
from utils.logger import get_logger
from utils.validators import SensorReading, now

log = get_logger("sensor_manager")


class SensorManager:
    def __init__(
        self,
        on_reading: Optional[Callable[[SensorReading], None]] = None,
    ):
        """
        Parameters
        ----------
        on_reading : callable
            Called with a SensorReading on every successful poll cycle.
            Designed to be wired to AlertManager.process() and
            FirebaseManager.push_sensor().
        """
        self._on_reading  = on_reading
        self._sim         = settings.SIMULATION_MODE
        self._interval    = settings.SENSOR_INTERVAL
        self._mission_id  = settings.MISSION_ID

        # sensor driver instances
        self._ph          = PHSensor(simulation=self._sim)
        self._tds         = TDSSensor(simulation=self._sim)
        self._turbidity   = TurbiditySensor(simulation=self._sim)
        self._temperature = DS18B20Sensor(
            base_path=settings.DS18B20_BASE_PATH,
            simulation=self._sim,
        )
        self._ammonia     = MQ137Sensor(simulation=self._sim)

        # state
        self._lock    = threading.Lock()
        self._latest: Optional[SensorReading] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._serial  = None          # serial.Serial instance when connected

        # counters
        self._total_readings = 0
        self._failed_readings = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        log.info("[SensorManager] Starting...")
        self._open_sensors()
        if not self._sim:
            self._open_serial()
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop,
            name="SensorLoop",
            daemon=True,
        )
        self._thread.start()
        log.info("[SensorManager] Running (simulation=%s, interval=%.1fs)",
                 self._sim, self._interval)

    def stop(self) -> None:
        log.info("[SensorManager] Stopping...")
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._close_sensors()
        if self._serial and self._serial.is_open:
            self._serial.close()
        log.info("[SensorManager] Stopped")

    # ── public API ────────────────────────────────────────────────────────────
    def get_latest(self) -> Optional[SensorReading]:
        with self._lock:
            return self._latest

    def status(self) -> dict:
        return {
            "running":          self._running,
            "simulation":       self._sim,
            "interval_seconds": self._interval,
            "total_readings":   self._total_readings,
            "failed_readings":  self._failed_readings,
            "serial_connected": self._serial is not None and self._serial.is_open,
            "mq137_warmed_up":  self._ammonia.is_warmed_up(),
            "mq137_warmup_remaining": self._ammonia.warmup_remaining(),
            "sensors": {
                "pH":          self._ph.status(),
                "tds":         self._tds.status(),
                "turbidity":   self._turbidity.status(),
                "temperature": self._temperature.status(),
                "ammonia":     self._ammonia.status(),
            },
        }

    # ── background loop ───────────────────────────────────────────────────────
    def _loop(self) -> None:
        while self._running:
            start = time.time()
            try:
                if not self._sim:
                    self._drain_serial()
                reading = self._poll()
                if reading and reading.is_valid:
                    with self._lock:
                        self._latest = reading
                    self._total_readings += 1
                    if self._on_reading:
                        self._on_reading(reading)
                else:
                    self._failed_readings += 1
            except Exception as exc:
                log.error(f"[SensorManager] Loop error: {exc}", exc_info=True)
                self._failed_readings += 1

            elapsed = time.time() - start
            sleep   = max(0.0, self._interval - elapsed)
            time.sleep(sleep)

    def _poll(self) -> SensorReading:
        return SensorReading(
            timestamp   = now(),
            pH          = self._ph.read(),
            tds         = self._tds.read(),
            turbidity   = self._turbidity.read(),
            temperature = self._temperature.read(),
            ammonia     = self._ammonia.read(),
            source      = "simulation" if self._sim else "sensor",
            mission_id  = self._mission_id,
        )

    # ── Arduino serial ────────────────────────────────────────────────────────
    def _open_serial(self) -> None:
        try:
            import serial  # type: ignore
            self._serial = serial.Serial(
                port     = settings.ARDUINO_PORT,
                baudrate = settings.ARDUINO_BAUD,
                timeout  = 1.0,
            )
            log.info(f"[SensorManager] Serial open on {settings.ARDUINO_PORT}")
        except Exception as exc:
            log.error(f"[SensorManager] Could not open serial: {exc}")
            log.warning("[SensorManager] Falling back to simulation for serial sensors")
            self._serial = None

    def _drain_serial(self) -> None:
        """
        Read all available lines from the Arduino serial port and inject
        values into the appropriate sensor driver.
        Expected line format:  {"sensor": "pH", "value": 7.34}
        """
        if not self._serial or not self._serial.is_open:
            return
        _injectors = {
            "pH":        self._ph.inject,
            "tds":       self._tds.inject,
            "turbidity": self._turbidity.inject,
            "ammonia":   self._ammonia.inject,
        }
        try:
            while self._serial.in_waiting > 0:
                raw = self._serial.readline().decode("utf-8", errors="ignore").strip()
                if not raw:
                    continue
                payload = json.loads(raw)
                sensor_name = payload.get("sensor")
                value       = float(payload.get("value", 0))
                if sensor_name in _injectors:
                    _injectors[sensor_name](value)
        except json.JSONDecodeError as exc:
            log.debug(f"[SensorManager] Serial parse error: {exc}")
        except Exception as exc:
            log.warning(f"[SensorManager] Serial drain error: {exc}")

    # ── sensor init / teardown ────────────────────────────────────────────────
    def _open_sensors(self) -> None:
        for s in (self._ph, self._tds, self._turbidity, self._temperature, self._ammonia):
            try:
                s.open()
            except Exception as exc:
                log.error(f"[SensorManager] Could not open {s.name}: {exc}")

    def _close_sensors(self) -> None:
        for s in (self._ph, self._tds, self._turbidity, self._temperature, self._ammonia):
            try:
                s.close()
            except Exception as exc:
                log.warning(f"[SensorManager] Error closing {s.name}: {exc}")
