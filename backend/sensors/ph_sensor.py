"""
sensors/ph_sensor.py
====================
pH sensor driver.

Hardware path
-------------
The analog pH probe connects to the Arduino Nano's A0 pin.  The Nano
performs a 10-point rolling average, converts the ADC value to pH using
the calibration formula below, and sends a JSON line over serial:

    {"sensor": "pH", "value": 7.34}\n

The SensorManager reads these lines via ArduinoSerial (see
managers/sensor_manager.py).  This driver wraps that value.

Calibration formula (standard pH ORP module)
--------------------------------------------
    voltage  = (adc_value / 1023.0) * 5.0   -- Arduino 5V reference
    pH_value = 3.5 * voltage + calibration_offset

Simulation mode
---------------
Returns a realistic sinusoidal drift around neutral (7.0 ± 0.8)
with added Gaussian noise to mimic real river data.
"""

import math
import random
import time
from typing import Optional

from sensors.base_sensor import BaseSensor


class PHSensor(BaseSensor):
    """
    Returns pH in range 0–14.
    Typical clean Nile water: 7.5–8.5
    Polluted / industrial discharge: < 6.0 or > 9.5
    """

    def __init__(self, simulation: bool = True):
        super().__init__("pH", simulation)
        self._start_time = time.time()
        # Will be populated by SensorManager from its serial buffer
        self._external_value: Optional[float] = None

    def open(self) -> None:
        self._open = True

    def read(self) -> Optional[float]:
        try:
            if self.simulation:
                return self._record(self._simulate())
            # Real hardware: value is injected by SensorManager
            # after parsing the Arduino serial JSON line
            if self._external_value is not None:
                return self._record(self._external_value)
            return None
        except Exception as exc:
            self._fail(exc)
            return None

    def close(self) -> None:
        self._open = False

    def inject(self, value: float) -> None:
        """Called by SensorManager when it parses a pH line from Arduino."""
        self._external_value = value

    # ── simulation ────────────────────────────────────────────────────────────
    def _simulate(self) -> float:
        elapsed = time.time() - self._start_time
        # slow drift with a 5-minute period, ± 0.8 around 7.4
        drift    = 0.8 * math.sin(2 * math.pi * elapsed / 300)
        noise    = random.gauss(0, 0.05)
        # occasional pollution spike
        if random.random() < 0.02:
            noise += random.choice([-2.0, 2.0])
        raw = 7.4 + drift + noise
        return round(max(0.0, min(14.0, raw)), 2)
