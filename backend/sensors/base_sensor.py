"""
sensors/base_sensor.py
======================
Abstract interface that every sensor driver must implement.

Adding a new sensor type = create a subclass, implement read() and close().
The SensorManager discovers drivers by importing them from this package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class BaseSensor(ABC):
    """
    All sensor drivers inherit from this base.

    Lifecycle
    ---------
    1. __init__()   — store config, do NOT open hardware yet
    2. open()       — open serial port / I2C bus / GPIO — called by manager
    3. read()       — return latest value, or None on error
    4. close()      — release hardware resources
    5. status()     — return human-readable dict for the dashboard

    Contract
    --------
    - read() must never raise.  Return None and log the exception instead.
    - open() and close() may raise — the manager handles that.
    - All values returned by read() are in the physical unit documented
      in the subclass docstring.
    """

    def __init__(self, name: str, simulation: bool = True):
        self.name       = name
        self.simulation = simulation
        self._open      = False
        self._error_count = 0
        self._last_value: Optional[float] = None

    # ── abstract ─────────────────────────────────────────────────────────────
    @abstractmethod
    def open(self) -> None:
        """Initialise hardware connection."""

    @abstractmethod
    def read(self) -> Optional[float]:
        """Return the latest sensor value, or None on error."""

    @abstractmethod
    def close(self) -> None:
        """Release hardware resources."""

    # ── concrete helpers ─────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        return {
            "name":          self.name,
            "open":          self._open,
            "simulation":    self.simulation,
            "error_count":   self._error_count,
            "last_value":    self._last_value,
        }

    def _record(self, value: Optional[float]) -> Optional[float]:
        """Store last successful value and return it."""
        if value is not None:
            self._last_value = value
        return value

    def _fail(self, exc: Exception) -> None:
        """Log a read failure without raising."""
        self._error_count += 1
        from utils.logger import get_logger
        get_logger(f"sensor.{self.name}").error(
            f"Read error #{self._error_count}: {exc}"
        )
