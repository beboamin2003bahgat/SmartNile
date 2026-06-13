"""
managers/gps_manager.py
=======================
Reads NMEA sentences from the NEO-6M GPS module and emits GPSFix objects.

Hardware path
-------------
NEO-6M TX → RPi UART RX → /dev/ttyAMA0 (9600 baud)

On Raspberry Pi 5 you must disable the serial console first:
    sudo raspi-config → Interface Options → Serial Port
    "Would you like a login shell accessible over serial?" → No
    "Would you like the serial port hardware to be enabled?" → Yes

NMEA sentences parsed
---------------------
$GPRMC  → lat, lon, speed, heading, date/time
$GPGGA  → lat, lon, altitude, satellites, fix quality

Simulation mode
---------------
The boat follows a realistic 2 km route along the Nile starting near
Cairo (30.05°N, 31.23°E), moving slowly north-east with gentle course
variations to mimic real propulsion.
"""

import math
import random
import threading
import time
from typing import Callable, Deque, List, Optional
from collections import deque

from config.settings import settings
from utils.logger import get_logger
from utils.validators import GPSFix, now

log = get_logger("gps_manager")

# Cairo-area Nile starting coordinates
_SIM_START_LAT = 30.0500
_SIM_START_LON = 31.2300
_SIM_SPEED_KPH = 4.0        # ~2 knots
_MAX_ROUTE_HISTORY = 2000   # GPS fixes kept in memory


class GPSManager:
    def __init__(
        self,
        on_fix: Optional[Callable[[GPSFix], None]] = None,
    ):
        self._on_fix       = on_fix
        self._sim          = settings.SIMULATION_MODE
        self._interval     = settings.GPS_INTERVAL
        self._mission_id   = settings.MISSION_ID

        self._lock         = threading.Lock()
        self._latest: Optional[GPSFix] = None
        self._route: Deque[GPSFix]     = deque(maxlen=_MAX_ROUTE_HISTORY)
        self._running      = False
        self._thread: Optional[threading.Thread] = None
        self._serial       = None

        # simulation state
        self._sim_lat      = _SIM_START_LAT
        self._sim_lon      = _SIM_START_LON
        self._sim_heading  = 45.0   # north-east
        self._sim_elapsed  = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        log.info("[GPSManager] Starting (simulation=%s)", self._sim)
        if not self._sim:
            self._open_serial()
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop,
            name="GPSLoop",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._serial and self._serial.is_open:
            self._serial.close()
        log.info("[GPSManager] Stopped")

    # ── public API ────────────────────────────────────────────────────────────
    def get_latest(self) -> Optional[GPSFix]:
        with self._lock:
            return self._latest

    def get_route(self) -> List[GPSFix]:
        with self._lock:
            return list(self._route)

    def get_route_dicts(self) -> List[dict]:
        """Serialisable route for Firebase / dashboard."""
        return [f.to_dict() for f in self.get_route()]

    def status(self) -> dict:
        latest = self.get_latest()
        return {
            "running":        self._running,
            "simulation":     self._sim,
            "has_fix":        latest.has_fix if latest else False,
            "fix_quality":    latest.fix_quality if latest else 0,
            "satellites":     latest.satellites if latest else 0,
            "route_points":   len(self._route),
            "latitude":       latest.latitude if latest else None,
            "longitude":      latest.longitude if latest else None,
        }

    # ── background loop ───────────────────────────────────────────────────────
    def _loop(self) -> None:
        while self._running:
            start = time.time()
            try:
                fix = self._sim_fix() if self._sim else self._read_hardware()
                if fix:
                    if not fix.is_in_egypt and not self._sim:
                        log.warning("[GPSManager] Fix outside Egypt bounding box — ignored")
                    else:
                        with self._lock:
                            self._latest = fix
                            self._route.append(fix)
                        if self._on_fix:
                            self._on_fix(fix)
            except Exception as exc:
                log.error(f"[GPSManager] Loop error: {exc}", exc_info=True)

            elapsed = time.time() - start
            time.sleep(max(0.0, self._interval - elapsed))

    # ── hardware read (NMEA) ──────────────────────────────────────────────────
    def _open_serial(self) -> None:
        try:
            import serial  # type: ignore
            self._serial = serial.Serial(
                port     = settings.GPS_PORT,
                baudrate = settings.GPS_BAUD,
                timeout  = settings.GPS_TIMEOUT,
            )
            log.info(f"[GPSManager] Serial open on {settings.GPS_PORT}")
        except Exception as exc:
            log.error(f"[GPSManager] Could not open GPS serial: {exc}")
            self._serial = None

    def _read_hardware(self) -> Optional[GPSFix]:
        if not self._serial or not self._serial.is_open:
            return None
        lat = lon = alt = speed = heading = None
        satellites = 0
        fix_quality = 0

        try:
            for _ in range(20):     # read up to 20 lines per interval
                raw = self._serial.readline().decode("ascii", errors="ignore").strip()
                if raw.startswith("$GPRMC"):
                    lat, lon, speed, heading = self._parse_rmc(raw)
                elif raw.startswith("$GPGGA"):
                    lat, lon, alt, satellites, fix_quality = self._parse_gga(raw)
        except Exception as exc:
            log.warning(f"[GPSManager] NMEA parse error: {exc}")

        return GPSFix(
            timestamp   = now(),
            latitude    = lat,
            longitude   = lon,
            altitude    = alt,
            speed       = speed,
            heading     = heading,
            satellites  = satellites,
            fix_quality = fix_quality,
            source      = "gps",
            mission_id  = self._mission_id,
        )

    # ── NMEA parsers ──────────────────────────────────────────────────────────
    @staticmethod
    def _nmea_to_decimal(raw: str, direction: str) -> Optional[float]:
        """Convert NMEA ddmm.mmmm + N/S/E/W to decimal degrees."""
        try:
            raw = raw.strip()
            if not raw:
                return None
            dot_pos = raw.index(".")
            deg = int(raw[:dot_pos - 2])
            minutes = float(raw[dot_pos - 2:])
            decimal = deg + minutes / 60.0
            if direction in ("S", "W"):
                decimal = -decimal
            return round(decimal, 7)
        except Exception:
            return None

    def _parse_rmc(self, sentence: str):
        """$GPRMC,hhmmss,A,lat,N,lon,E,speed,heading,date,,,*checksum"""
        try:
            parts = sentence.split(",")
            if len(parts) < 9 or parts[2] != "A":
                return None, None, None, None
            lat     = self._nmea_to_decimal(parts[3], parts[4])
            lon     = self._nmea_to_decimal(parts[5], parts[6])
            speed   = round(float(parts[7]) * 1.852, 2) if parts[7] else None  # knots→km/h
            heading = round(float(parts[8]), 1) if parts[8] else None
            return lat, lon, speed, heading
        except Exception:
            return None, None, None, None

    def _parse_gga(self, sentence: str):
        """$GPGGA,hhmmss,lat,N,lon,E,quality,sats,hdop,alt,M,..."""
        try:
            parts       = sentence.split(",")
            lat         = self._nmea_to_decimal(parts[2], parts[3])
            lon         = self._nmea_to_decimal(parts[4], parts[5])
            fix_quality = int(parts[6]) if parts[6] else 0
            satellites  = int(parts[7]) if parts[7] else 0
            alt         = round(float(parts[9]), 1) if parts[9] else None
            return lat, lon, alt, satellites, fix_quality
        except Exception:
            return None, None, None, 0, 0

    # ── simulation ────────────────────────────────────────────────────────────
    def _sim_fix(self) -> GPSFix:
        self._sim_elapsed += self._interval
        # gentle heading variation
        self._sim_heading += random.gauss(0, 2.0)
        self._sim_heading %= 360

        # move boat: convert speed (km/h) and elapsed time to lat/lon delta
        dist_km = (_SIM_SPEED_KPH * self._interval) / 3600
        heading_rad = math.radians(self._sim_heading)
        delta_lat = (dist_km / 111.32) * math.cos(heading_rad)
        delta_lon = (dist_km / (111.32 * math.cos(math.radians(self._sim_lat)))) * math.sin(heading_rad)

        self._sim_lat += delta_lat
        self._sim_lon += delta_lon

        # wrap back to start after ~ 2 km
        if abs(self._sim_lat - _SIM_START_LAT) > 0.01 or abs(self._sim_lon - _SIM_START_LON) > 0.01:
            self._sim_lat = _SIM_START_LAT + random.gauss(0, 0.0001)
            self._sim_lon = _SIM_START_LON + random.gauss(0, 0.0001)
            self._sim_heading = random.uniform(0, 360)

        return GPSFix(
            timestamp   = now(),
            latitude    = round(self._sim_lat + random.gauss(0, 0.00002), 7),
            longitude   = round(self._sim_lon + random.gauss(0, 0.00002), 7),
            altitude    = round(18.0 + random.gauss(0, 0.3), 1),
            speed       = round(_SIM_SPEED_KPH + random.gauss(0, 0.2), 2),
            heading     = round(self._sim_heading, 1),
            satellites  = random.randint(6, 12),
            fix_quality = 1,
            source      = "simulation",
            mission_id  = self._mission_id,
        )
