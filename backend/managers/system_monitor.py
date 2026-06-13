"""
managers/system_monitor.py
==========================
Reads Raspberry Pi 5 system metrics and appends them to the heartbeat
document that FirebaseManager writes every 15 seconds.

Metrics collected
-----------------
- CPU usage     %  (1-second sample)
- RAM used/total MB
- CPU temperature °C  (RPi thermal zone)
- Disk usage    %  (/home partition)
- Uptime        seconds
- Battery %     (if INA219 or UPS HAT exposes a /sys path; falls back to None)

Usage (called from main.py)
----------------------------
    from managers.system_monitor import SystemMonitor
    monitor = SystemMonitor()
    monitor.start()

    # In push_heartbeat extra dict:
    firebase.push_heartbeat(extra=monitor.snapshot())

The snapshot() method is non-blocking — it returns the last cached reading.
"""

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger

log = get_logger("system_monitor")

# Raspberry Pi thermal zone for CPU temperature
_THERMAL_ZONE = "/sys/class/thermal/thermal_zone0/temp"

# Common UPS HAT / INA219 battery capacity paths (check yours)
_BATTERY_PATHS = [
    "/sys/class/power_supply/BAT0/capacity",
    "/sys/class/power_supply/battery/capacity",
    "/sys/class/power_supply/rpi-poe-hat/capacity",
]


class SystemMonitor:
    def __init__(self, interval: float = 10.0):
        self._interval = interval
        self._lock     = threading.Lock()
        self._cache: Dict[str, Any] = {}
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._psutil_available = False

        try:
            import psutil  # type: ignore  # noqa
            self._psutil_available = True
        except ImportError:
            log.warning("[SystemMonitor] psutil not installed — using /proc fallback")

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        self._running = True
        self._refresh()   # populate immediately on start
        self._thread = threading.Thread(
            target=self._loop, name="SysMonitor", daemon=True
        )
        self._thread.start()
        log.info("[SystemMonitor] Started (interval=%.0fs)", self._interval)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    # ── public API ────────────────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        """Non-blocking — returns last cached metrics dict."""
        with self._lock:
            return dict(self._cache)

    # ── background loop ───────────────────────────────────────────────────────
    def _loop(self) -> None:
        while self._running:
            time.sleep(self._interval)
            try:
                self._refresh()
            except Exception as exc:
                log.debug(f"[SystemMonitor] Refresh error: {exc}")

    def _refresh(self) -> None:
        data: Dict[str, Any] = {
            "uptime_s":    self._uptime(),
            "cpu_temp_c":  self._cpu_temp(),
            "battery_pct": self._battery(),
        }

        if self._psutil_available:
            import psutil  # type: ignore
            data["cpu_pct"]      = psutil.cpu_percent(interval=1)
            vm                   = psutil.virtual_memory()
            data["ram_used_mb"]  = round(vm.used / 1024 / 1024, 1)
            data["ram_total_mb"] = round(vm.total / 1024 / 1024, 1)
            data["ram_pct"]      = vm.percent
            try:
                du = psutil.disk_usage("/")
                data["disk_pct"] = du.percent
            except Exception:
                data["disk_pct"] = None
        else:
            data.update(self._proc_stats())

        with self._lock:
            self._cache = data

    # ── individual metric readers ─────────────────────────────────────────────
    @staticmethod
    def _uptime() -> float:
        try:
            with open("/proc/uptime") as fh:
                return float(fh.read().split()[0])
        except Exception:
            return 0.0

    @staticmethod
    def _cpu_temp() -> Optional[float]:
        try:
            raw = Path(_THERMAL_ZONE).read_text().strip()
            return round(int(raw) / 1000.0, 1)
        except Exception:
            return None

    @staticmethod
    def _battery() -> Optional[float]:
        for path in _BATTERY_PATHS:
            try:
                val = int(Path(path).read_text().strip())
                return float(val)
            except Exception:
                continue
        return None

    @staticmethod
    def _proc_stats() -> Dict[str, Any]:
        """Fallback using /proc when psutil is unavailable."""
        result: Dict[str, Any] = {
            "cpu_pct":      None,
            "ram_used_mb":  None,
            "ram_total_mb": None,
            "ram_pct":      None,
            "disk_pct":     None,
        }
        try:
            # /proc/meminfo
            mem: Dict[str, int] = {}
            with open("/proc/meminfo") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) >= 2:
                        mem[parts[0].rstrip(":")] = int(parts[1])
            total = mem.get("MemTotal", 0)
            avail = mem.get("MemAvailable", 0)
            used  = total - avail
            if total:
                result["ram_total_mb"] = round(total / 1024, 1)
                result["ram_used_mb"]  = round(used  / 1024, 1)
                result["ram_pct"]      = round(used / total * 100, 1)
        except Exception:
            pass
        return result
