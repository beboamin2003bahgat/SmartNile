"""
sensors/water_sensors.py
========================
Four sensor drivers in one file — they share the same Arduino serial
injection pattern and simulation logic structure.

TDS Sensor
----------
Connected to Arduino A1.  TDS module outputs analog voltage proportional
to total dissolved solids (ppm).
    voltage = (adc / 1023.0) * 5.0
    tds_ppm = (133.42 * voltage³ - 255.86 * voltage² + 857.39 * voltage) * 0.5

TurbidityProbeSensor
--------------------
Connected to Arduino A2.  The SEN0189 module outputs 0–4.5V inversely
proportional to turbidity.
    voltage  = (adc / 1023.0) * 5.0
    ntu = -1120.4 * voltage² + 5742.3 * voltage - 4352.9   (negative = 0)

DS18B20TemperatureSensor
------------------------
Connected directly to Raspberry Pi GPIO 4 (1-Wire).
The kernel driver exposes readings at:
    /sys/bus/w1/devices/<device_id>/w1_slave
This driver reads that file directly — no Arduino involved.

MQ137AmmoniaSensor
------------------
Connected to Arduino A3.  MQ-137 is a metal-oxide sensor.
    voltage   = (adc / 1023.0) * 5.0
    ppm_raw   = MQ137_CURVE_A * (voltage ** MQ137_CURVE_B)
Values require a warm-up period (60 s) and temperature/humidity
compensation for production accuracy.
"""

import glob
import math
import os
import random
import time
from typing import Optional

from sensors.base_sensor import BaseSensor
from utils.logger import get_logger

log = get_logger("sensors")

# MQ-137 empirical curve constants (calibrated for 20°C, 65% RH)
MQ137_CURVE_A = 102.2
MQ137_CURVE_B = -1.386


# ── TDS ─────────────────────────────────────────────────────────────────────
class TDSSensor(BaseSensor):
    """Returns TDS in parts-per-million (ppm).  0 = pure, >1000 = very polluted."""

    def __init__(self, simulation: bool = True):
        super().__init__("tds", simulation)
        self._start_time = time.time()
        self._external_value: Optional[float] = None

    def open(self) -> None:
        self._open = True

    def read(self) -> Optional[float]:
        try:
            if self.simulation:
                return self._record(self._simulate())
            return self._record(self._external_value)
        except Exception as exc:
            self._fail(exc)
            return None

    def close(self) -> None:
        self._open = False

    def inject(self, value: float) -> None:
        self._external_value = value

    def _simulate(self) -> float:
        elapsed = time.time() - self._start_time
        base  = 220 + 80 * math.sin(2 * math.pi * elapsed / 420)
        noise = random.gauss(0, 8)
        if random.random() < 0.015:
            base += random.uniform(200, 600)   # pollution spike
        return round(max(0.0, base + noise), 1)


# ── Turbidity ────────────────────────────────────────────────────────────────
class TurbiditySensor(BaseSensor):
    """Returns turbidity in NTU.  0 = crystal clear, >100 = very murky."""

    def __init__(self, simulation: bool = True):
        super().__init__("turbidity", simulation)
        self._start_time = time.time()
        self._external_value: Optional[float] = None

    def open(self) -> None:
        self._open = True

    def read(self) -> Optional[float]:
        try:
            if self.simulation:
                return self._record(self._simulate())
            return self._record(self._external_value)
        except Exception as exc:
            self._fail(exc)
            return None

    def close(self) -> None:
        self._open = False

    def inject(self, value: float) -> None:
        self._external_value = value

    def _simulate(self) -> float:
        elapsed = time.time() - self._start_time
        base  = 15 + 10 * math.sin(2 * math.pi * elapsed / 600)
        noise = random.gauss(0, 1.5)
        if random.random() < 0.01:
            base += random.uniform(30, 80)
        return round(max(0.0, base + noise), 2)


# ── DS18B20 Temperature ──────────────────────────────────────────────────────
class DS18B20Sensor(BaseSensor):
    """
    Returns water temperature in °C.

    Reads from the kernel 1-Wire interface at
    /sys/bus/w1/devices/<device_id>/w1_slave
    On RPi 5, enable 1-Wire with:
        echo "dtoverlay=w1-gpio" >> /boot/config.txt
    then reboot.
    """

    def __init__(self, base_path: str = "/sys/bus/w1/devices", simulation: bool = True):
        super().__init__("temperature", simulation)
        self._base_path   = base_path
        self._device_file: Optional[str] = None
        self._start_time  = time.time()

    def open(self) -> None:
        if not self.simulation:
            devices = glob.glob(os.path.join(self._base_path, "28-*", "w1_slave"))
            if devices:
                self._device_file = devices[0]
                log.info(f"[DS18B20] Found device at {self._device_file}")
            else:
                log.warning("[DS18B20] No 1-Wire device found — check wiring and dtoverlay")
        self._open = True

    def read(self) -> Optional[float]:
        try:
            if self.simulation:
                return self._record(self._simulate())
            return self._record(self._read_hardware())
        except Exception as exc:
            self._fail(exc)
            return None

    def _read_hardware(self) -> Optional[float]:
        if not self._device_file:
            return None
        with open(self._device_file) as fh:
            lines = fh.readlines()
        if len(lines) < 2 or "YES" not in lines[0]:
            return None
        # format: "t=23456" → 23.456°C
        raw = lines[1].strip().split("t=")[-1]
        return round(int(raw) / 1000.0, 2)

    def close(self) -> None:
        self._open = False

    def _simulate(self) -> float:
        elapsed = time.time() - self._start_time
        # daily temperature cycle simulation (period = 24 h compressed to 10 min)
        base  = 24 + 4 * math.sin(2 * math.pi * elapsed / 600)
        noise = random.gauss(0, 0.2)
        return round(base + noise, 2)


# ── MQ-137 Ammonia ───────────────────────────────────────────────────────────
class MQ137Sensor(BaseSensor):
    """
    Returns ammonia concentration in ppm.
    Safe: < 0.5 ppm.  Dangerous: > 2.0 ppm.

    The sensor requires a 60-second warm-up before readings are reliable.
    is_warmed_up() must return True before values are used.
    """

    WARMUP_SECONDS = 60

    def __init__(self, simulation: bool = True):
        super().__init__("ammonia", simulation)
        self._open_time: Optional[float] = None
        self._start_time = time.time()
        self._external_value: Optional[float] = None

    def open(self) -> None:
        self._open_time = time.time()
        self._open = True
        log.info("[MQ137] Warming up — readings unavailable for 60 s")

    def read(self) -> Optional[float]:
        try:
            if not self.is_warmed_up():
                return None
            if self.simulation:
                return self._record(self._simulate())
            return self._record(self._external_value)
        except Exception as exc:
            self._fail(exc)
            return None

    def close(self) -> None:
        self._open = False

    def inject(self, value: float) -> None:
        self._external_value = value

    def is_warmed_up(self) -> bool:
        if self._open_time is None:
            return False
        return (time.time() - self._open_time) >= self.WARMUP_SECONDS

    def warmup_remaining(self) -> float:
        if self._open_time is None:
            return float(self.WARMUP_SECONDS)
        remaining = self.WARMUP_SECONDS - (time.time() - self._open_time)
        return max(0.0, remaining)

    def _simulate(self) -> float:
        elapsed = time.time() - self._start_time
        base  = 0.08 + 0.04 * math.sin(2 * math.pi * elapsed / 800)
        noise = random.gauss(0, 0.005)
        if random.random() < 0.01:
            base += random.uniform(0.5, 3.0)
        return round(max(0.0, base + noise), 4)
